"""
================================================================
  DESKTOP APP - ALL LONG & SHORT SIGNALS ON ONE SCREEN (24/7)

  Run:   python app.py          (or double-click run_app.bat)
  Test:  python app.py --smoke  (opens, checks it works, closes)

  ROW 1  header        title, status light, live clock
  ROW 2  toolbar       start / stop / scan now / telegram / settings
  ROW 3  banner        money flow: longs favored or shorts only
  ROW 4  KPI cards     flow, signals today, fear&greed, BTC, last signal
  ROW 5  checklist +   the 8 morning checks + live activity log
         log
  ROW 6  tables        LONG (green) / SHORT (red), filter + sort + right-click
  ROW 7  detail        entry, stop, TP1-3, size, checklist of clicked row
  ROW 8  status bar    provider, coins, progress bar, next check countdown
================================================================
"""
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

import config

SETTINGS_FILE = "app_settings.json"

# --------------------------------------------------------------- settings
VALID_SETTINGS = {
    "balance": ("ACCOUNT_BALANCE", float),
    "leverage": ("MAX_LEVERAGE", int),
    "risk_pct": ("RISK_PER_TRADE_PCT", float),
    "min_grade": ("MIN_GRADE", str),
    "max_coins": ("MAX_COINS", int),
    "min_vol_m": ("MIN_QUOTE_VOLUME_24H", float),   # stored in millions
    "scan_sec": ("SCAN_INTERVAL_SEC", int),
    "telegram": ("TELEGRAM_ENABLED", bool),
    "autostart": ("AUTO_START", bool),
    "keep_awake": ("KEEP_AWAKE", bool),
    "strong": ("STRONG_ONLY", bool),
}


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def apply_settings(data):
    for key, (attr, cast) in VALID_SETTINGS.items():
        if key not in data:
            continue
        try:
            val = cast(data[key])
            if key == "min_vol_m":
                val = float(val) * 1_000_000
            elif key == "scan_sec":
                val = max(0, min(300, int(val)))
            setattr(config, attr, val)
        except (TypeError, ValueError):
            pass


def store_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except OSError:
        pass


# --------------------------------------------------------------- colours
BG = "#0b0e13"
PANEL = "#161b22"
PANEL2 = "#1c2129"
CARD = "#12171e"
LINE = "#21262d"
FG = "#e6edf3"
MUTED = "#8b949e"
GREEN = "#26a69a"
GREEN_BG = "#0d3b33"
RED = "#ef5350"
RED_BG = "#4a1512"
YELLOW = "#d29922"
BLUE = "#58a6ff"
PURPLE = "#d2a8ff"
BANNER = {
    "ROTATING_IN": ("#0b3d20", "#3fb950",
                    "MONEY ROTATING INTO ALTS   ->   LONGS FAVORED"),
    "BTC_SEASON": ("#0b2d4d", "#58a6ff",
                   "MONEY ENTERING (BITCOIN LEADS)   ->   LONGS FAVORED"),
    "LEAVING": ("#4d2b0b", "#f0883e",
                "MONEY LEAVING THE MARKET   ->   SHORTS ONLY, BE CAREFUL"),
    "PANIC": ("#4a1512", "#ef5350",
              "PANIC: TOTAL CAP DOWN + DOMINANCE UP   ->   SHORTS ONLY"),
    "UNKNOWN": ("#161b22", "#8b949e", "MONEY FLOW: WAITING FOR DATA"),
}

LOG_LINE = re.compile(
    r"^(?P<ts>[\d\-]{5,} [\d:]{6,8}) \| (?P<side>LONG|SHORT) (?P<sym>\S+) "
    r"grade=(?P<grade>\S+) score=(?P<score>-?\d+) entry=(?P<entry>\S+) "
    r"sl=(?P<sl>\S+) tp=(?P<tp>[\d.,]+) lev=(?P<lev>\d+)x"
    r"(?: p=(?P<prob>\d{1,3})%)?(?: mkt=(?P<mkt>\S+))?\s*$")

GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}

MKT_LABEL = {"crypto": "CRYP", "forex": "FX", "metal": "GOLD", "stock": "STK"}
MKT_FILTER = {"ALL": None, "CRYPTO": "crypto", "FOREX": "forex",
              "GOLD": "metal", "STOCKS": "stock"}


def mkt_label(cls):
    return MKT_LABEL.get(cls, str(cls)[:4].upper())


def num(v, digits=6):
    try:
        return f"{float(v):.{digits}g}"
    except (TypeError, ValueError):
        return str(v)


def set_awake(on):
    """Stop Windows from sleeping while the 24/7 scanner is running."""
    if not getattr(config, "KEEP_AWAKE", True) or sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


APP_TITLE = "Future Trading Signals - Long / Short"
MUTEX_NAME = "Local\\TenupFutureSignalApp"


def _acquire_single_instance():
    """
    Only ONE app may run at a time (two instances = double API load and
    racing state writes). Returns (handle, already_running).
    """
    if sys.platform != "win32":
        return None, False
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return None, False
        already = ctypes.get_last_error() == 183   # ERROR_ALREADY_EXISTS
        return (handle, already) if not already else (None, True)
    except Exception:
        return None, False


def _focus_existing_window():
    """Bring the already-running window to the front."""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, APP_TITLE)
        if hwnd:
            u32.ShowWindow(hwnd, 9)            # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
        return bool(hwnd)
    except Exception:
        return False


def _redirect_output():
    """
    Always leave a breadcrumb in app_console.log (session start), and when
    launched with pythonw.exe (no black console) send stdout/stderr there
    too, so nothing can vanish silently.
    """
    try:
        with open("app_console.log", "a", encoding="utf-8") as f:
            f.write(f"===== app session "
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} start =====\n")
    except OSError:
        pass
    if sys.stdout is None or sys.stderr is None:
        try:
            f = open("app_console.log", "a", buffering=1,
                     encoding="utf-8", errors="replace")
            if sys.stdout is None:
                sys.stdout = f
            if sys.stderr is None:
                sys.stderr = f
        except OSError:
            pass


def _crash_log():
    try:
        with open("app_crash.log", "a", encoding="utf-8") as f:
            f.write(f"\n===== CRASH {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"=====\n")
            f.write(traceback.format_exc())
    except OSError:
        pass


# =============================================================== APP
class SignalApp(tk.Tk):
    def __init__(self, smoke=False):
        super().__init__()
        apply_settings(load_settings())
        self.smoke = smoke
        self.title(APP_TITLE)
        self.geometry("1440x920")
        self.minsize(1120, 720)
        self.configure(bg=BG)

        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.scan_request = threading.Event()
        self.worker = None
        self.scanner = None
        self.sound_on = True
        self._ctx_seen = False

        # signal storage (newest first)
        self.signals = {"LONG": [], "SHORT": []}
        self.rows = {"LONG": {}, "SHORT": {}}
        self.filter_var = {"LONG": tk.StringVar(), "SHORT": tk.StringVar()}
        self.market_var = tk.StringVar(value="ALL")   # market filter dropdown
        self.sort_state = {"LONG": (None, False), "SHORT": (None, False)}
        self.trees = {}
        self.watch = {}                 # key "SYM:SIDE" -> watch row
        self._watch_dirty = False
        self._res_dirty = False         # an outcome changed -> redraw
        self._res_busy = False          # outcome worker running?
        self._last_res_run = 0.0

        self._build()
        self._load_history()
        self._set_status("STOPPED", MUTED)
        self._set_bar("idle")
        self.after(350, self._poll)
        self.after(1000, self._tick)          # 1-second heartbeat
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if config.AUTO_START:
            self._append_log("auto-start ON - scanner begins in a moment...", "head")
            self.after(400, self.start)

        # bring the window to the front when it opens (it can launch
        # behind other windows), then stop being "always on top"
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(2500, lambda: self.attributes("-topmost", False))

    # =================================================== UI
    def _build(self):
        # ---------------- header
        hdr = tk.Frame(self, bg="#080b0f", height=54)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        tk.Label(hdr, text="📡  FUTURE TRADING SIGNALS",
                 bg="#080b0f", fg=FG,
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=(16, 8))
        tk.Label(hdr, text="LONG / SHORT  •  24/7  •  50x mode",
                 bg="#080b0f", fg=MUTED,
                 font=("Segoe UI", 10)).pack(side="left")
        self.lbl_clock = tk.Label(hdr, text="", bg="#080b0f", fg=BLUE,
                                  font=("Consolas", 13, "bold"))
        self.lbl_clock.pack(side="right", padx=16)
        self.lbl_status = tk.Label(hdr, text="● STOPPED", bg="#080b0f",
                                   fg=MUTED, font=("Segoe UI", 11, "bold"))
        self.lbl_status.pack(side="right", padx=10)

        # ---------------- toolbar
        bar = tk.Frame(self, bg=PANEL, height=46)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        buttons = [
            ("▶  START", "Start.TButton", self.start),
            ("■  STOP", "Stop.TButton", self.stop),
            ("⟳  SCAN NOW", "TButton", self.scan_now),
            ("✈  TELEGRAM TEST", "TButton", self.telegram_test),
            ("⚙  SETTINGS", "TButton", self.open_settings),
        ]
        for text, style, cmd in buttons:
            ttk.Button(bar, text=text, style=style, command=cmd
                       ).pack(side="left", padx=(8, 4), pady=7)
        self.sound_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="🔊 Sound", variable=self.sound_var,
                        command=lambda: setattr(self, "sound_on",
                                                self.sound_var.get())
                        ).pack(side="left", padx=12)
        tk.Label(bar, text="market:", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 2))
        self.market_var.trace_add("write", lambda *_: self._market_changed())
        ttk.OptionMenu(bar, self.market_var, "ALL", "ALL", "CRYPTO", "FOREX",
                       "GOLD", "STOCKS").pack(side="left")
        self.lbl_counts = tk.Label(bar, text="LONG 0    SHORT 0",
                                   bg=PANEL, fg=FG,
                                   font=("Segoe UI", 12, "bold"))
        self.lbl_counts.pack(side="right", padx=16)

        # ---------------- banner
        self.banner = tk.Label(self, text="   MONEY FLOW: WAITING FOR DATA",
                               bg=BANNER["UNKNOWN"][0], fg=BANNER["UNKNOWN"][1],
                               font=("Segoe UI", 14, "bold"), pady=10)
        self.banner.grid(row=2, column=0, sticky="ew")

        # ---------------- KPI cards
        cards = tk.Frame(self, bg=BG)
        cards.grid(row=3, column=0, sticky="ew", padx=8, pady=(8, 0))
        self.cards = {}
        for key, caption in (("flow", "MONEY FLOW"),
                             ("today", "SIGNALS TODAY"),
                             ("results", "RESULTS (TP1 vs SL)"),
                             ("fg", "FEAR & GREED"),
                             ("btc", "BTC TREND"),
                             ("last", "LAST SIGNAL")):
            self.cards[key] = self._card(cards, caption)

        # ---------------- checklist + log
        mid = ttk.Frame(self)
        mid.grid(row=4, column=0, sticky="nsew", padx=8, pady=8)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=2)
        self.rowconfigure(5, weight=3)
        self.rowconfigure(6, weight=2)
        mid.columnconfigure(0, weight=5)
        mid.columnconfigure(1, weight=6)

        left = ttk.Frame(mid)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(left, text="📋  MORNING CHECKLIST  (big frame first)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        self.txt_check = tk.Text(left, wrap="word", height=12,
                                 bg=PANEL2, fg=FG, insertbackground=FG,
                                 font=("Consolas", 10), relief="flat",
                                 padx=10, pady=8, highlightthickness=1,
                                 highlightbackground=LINE)
        self.txt_check.pack(fill="both", expand=True)
        for tag, col in (("ok", GREEN), ("warn", YELLOW), ("bad", RED),
                         ("head", BLUE), ("dim", MUTED)):
            self.txt_check.tag_configure(tag, foreground=col)

        right = ttk.Frame(mid)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(right, text="📰  ACTIVITY LOG",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        self.txt_log = tk.Text(right, wrap="word", height=12,
                               bg=PANEL2, fg=MUTED, insertbackground=FG,
                               font=("Consolas", 9), relief="flat",
                               padx=10, pady=8, highlightthickness=1,
                               highlightbackground=LINE)
        self.txt_log.pack(fill="both", expand=True)
        self.txt_log.tag_configure("err", foreground=RED)
        self.txt_log.tag_configure("sig", foreground=GREEN)
        self.txt_log.tag_configure("head", foreground=BLUE)

        # ---------------- signal tables
        tables = ttk.Frame(self)
        tables.grid(row=5, column=0, sticky="nsew", padx=8, pady=(0, 8))
        tables.columnconfigure(0, weight=1)
        tables.columnconfigure(1, weight=1)
        tables.rowconfigure(0, weight=1)
        self._build_table(tables, "LONG", 0, GREEN, "🟢")
        self._build_table(tables, "SHORT", 1, RED, "🔴")

        # ---------------- detail + watchlist
        det_row = ttk.Frame(self)
        det_row.grid(row=6, column=0, sticky="nsew", padx=8, pady=(0, 8))
        det_row.columnconfigure(0, weight=3)
        det_row.columnconfigure(1, weight=2)
        det_row.rowconfigure(0, weight=1)

        det = ttk.Frame(det_row)
        det.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(det, text="🔎  SIGNAL DETAIL   (click a row - right-click for "
                            "more options)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        self.txt_detail = tk.Text(det, wrap="word", bg=PANEL2, fg=FG,
                                  font=("Consolas", 10), relief="flat",
                                  padx=10, pady=8, highlightthickness=1,
                                  highlightbackground=LINE)
        self.txt_detail.pack(fill="both", expand=True)
        for tag, col in (("ok", GREEN), ("warn", YELLOW), ("bad", RED),
                         ("head", BLUE), ("dim", MUTED)):
            self.txt_detail.tag_configure(tag, foreground=col)
        self.txt_detail.insert(
            "end", f"Waiting for a signal. The scanner checks every "
                   f"{config.TICK_EVERY_SEC}s and passes all "
                   f"{config.SCAN_WORKERS} workers over the whole market "
                   "continuously.\n", ("dim",))

        # right side: READY & WAITING watchlist
        self._build_watch(det_row)

        # ---------------- status bar
        sbar = tk.Frame(self, bg=PANEL, height=30)
        sbar.grid(row=7, column=0, sticky="ew")
        sbar.grid_propagate(False)
        self.lbl_bar = tk.Label(sbar, text="  idle", bg=PANEL, fg=MUTED,
                                font=("Consolas", 9))
        self.lbl_bar.pack(side="left", padx=10)
        self.pbar = ttk.Progressbar(sbar, length=260, mode="determinate")
        self.pbar.pack(side="right", padx=10, pady=5)
        self.lbl_next = tk.Label(sbar, text="", bg=PANEL, fg=BLUE,
                                 font=("Consolas", 9, "bold"))
        self.lbl_next.pack(side="right", padx=10)

    # ---- helper: KPI card
    def _card(self, parent, caption):
        fr = tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                      highlightthickness=1, padx=14, pady=9)
        fr.pack(side="left", expand=True, fill="x", padx=4)
        tk.Label(fr, text=caption, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        val = tk.Label(fr, text="—", bg=CARD, fg=FG,
                       font=("Segoe UI", 15, "bold"))
        val.pack(anchor="w")
        sub = tk.Label(fr, text="", bg=CARD, fg=MUTED,
                       font=("Segoe UI", 8))
        sub.pack(anchor="w")
        return {"val": val, "sub": sub, "bg": CARD}

    def _card_set(self, key, value, colour=FG, sub=""):
        c = self.cards[key]
        c["val"].configure(text=value, foreground=colour)
        c["sub"].configure(text=sub)

    # ---- helper: signal table
    def _build_table(self, parent, side, col, colour, emoji):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=0, column=col, sticky="nsew",
                 padx=(0, 6) if col == 0 else (6, 0))

        top = tk.Frame(box, bg=BG)
        top.pack(fill="x", pady=(0, 4))
        tk.Label(top, text=f"{emoji}  {side} SIGNALS", bg=BG, fg=colour,
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        if not hasattr(self, "count_lbls"):
            self.count_lbls = {}
        lbl = tk.Label(top, text="0", bg=BG, fg=colour,
                       font=("Segoe UI", 12, "bold"))
        lbl.pack(side="left", padx=8)
        self.count_lbls[side] = lbl

        btn = ttk.Button(top, text="✕ Clear",
                         command=lambda: self._clear_side(side))
        btn.pack(side="right", padx=(6, 0))
        ent = ttk.Entry(top, textvariable=self.filter_var[side], width=16)
        ent.pack(side="right")
        ent.bind("<KeyRelease>", lambda e: self._render(side))
        tk.Label(top, text="filter:", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="right", padx=(0, 4))

        cols = ("coin", "mkt", "grade", "res", "entry", "stop", "stop%",
                "tp1", "tp2", "tp3", "lev", "time")
        widths = {"coin": 92, "mkt": 46, "grade": 56, "res": 44, "entry": 92,
                  "stop": 92, "stop%": 62, "tp1": 92, "tp2": 92, "tp3": 92,
                  "lev": 56, "time": 66}
        heads = {"coin": "COIN", "mkt": "MKT", "grade": "GRADE", "res": "RESULT",
                 "entry": "ENTRY", "stop": "STOP", "stop%": "STOP%", "tp1": "TP1",
                 "tp2": "TP2", "tp3": "TP3", "lev": "LEV", "time": "TIME"}
        tree = ttk.Treeview(box, columns=cols, show="headings", height=7,
                            selectmode="browse")
        for c in cols:
            tree.heading(c, text=heads[c],
                         command=lambda c=c, s=side: self._sort_by(s, c))
            tree.column(c, width=widths[c],
                        anchor="center" if c in ("coin", "mkt", "grade",
                                                 "res", "time")
                        else "e")
        vs = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        tree.tag_configure("long", background=GREEN_BG)
        tree.tag_configure("short", background=RED_BG)
        tree.tag_configure("hist", foreground="#7d8590")
        tree.tag_configure("won", foreground="#3fb950")
        tree.tag_configure("lost", foreground="#f85149")
        tree.tag_configure("running", foreground="#e3b341")
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Button-3>", lambda e, s=side: self._ctx_menu(e, s))
        self.trees[side] = tree

    # ---- helper: watchlist (READY & WAITING panel)
    def _build_watch(self, parent):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        top = tk.Frame(box, bg=BG)
        top.pack(fill="x", pady=(0, 4))
        tk.Label(top, text="👀  WATCHLIST", bg=BG, fg="#e3b341",
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        self.watch_count_lbl = tk.Label(top, text="0", bg=BG, fg="#e3b341",
                                        font=("Segoe UI", 12, "bold"))
        self.watch_count_lbl.pack(side="left", padx=8)
        tk.Label(top, text="fires automatically when a cross + rules match",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")

        cols = ("coin", "mkt", "side", "score", "grade", "status")
        tree = ttk.Treeview(box, columns=cols, show="headings", height=6,
                            selectmode="browse")
        widths = {"coin": 86, "mkt": 44, "side": 52, "score": 46,
                  "grade": 46, "status": 195}
        heads = {"coin": "COIN", "mkt": "MKT", "side": "SIDE", "score": "SCORE",
                 "grade": "GRADE", "status": "STATUS"}
        for c in cols:
            tree.heading(c, text=heads[c])
            tree.column(c, width=widths[c],
                        anchor="w" if c == "status" else "center")
        vs = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        tree.tag_configure("ready", background="#0d3b33", foreground="#3fb950")
        tree.tag_configure("near", background="#3a2e0b", foreground="#e3b341")
        tree.tag_configure("blocked", background="#1a1d21",
                           foreground="#6e7681")
        self.tree_watch = tree

    def _render_watch(self):
        tree = self.tree_watch
        # drop rows the scanner has not refreshed for 90s (stale data)
        cutoff = time.time() - 90
        for k in [k for k, r in self.watch.items()
                  if r.get("ts", 0) < cutoff]:
            del self.watch[k]
        rows = sorted(self.watch.values(),
                      key=lambda r: (-r["score"], r["sym"]))[:60]
        mc = self._market_cls()
        tree.delete(*tree.get_children())
        for r in rows:
            if mc is not None and r.get("mkt", "crypto") != mc:
                continue
            st = r.get("status", "")
            if "blocks" in st or "HALT" in st or "closed" in st:
                tag = "blocked"
            elif r.get("ready"):
                tag = "ready"
            else:
                tag = "near"
            tree.insert("", "end",
                        values=(r["sym"], mkt_label(r.get("mkt", "crypto")),
                                r["side"], str(r["score"]),
                                r["grade"], st[:40]),
                        tags=(tag,))
        self.watch_count_lbl.configure(text=str(len(self.watch)))
        self._watch_dirty = False

    # =================================================== rendering
    @staticmethod
    def _res_text(d):
        res = d.get("res")
        if res == "SKIP":
            return ""
        if not res:
            return "·" if d.get("ts") else ""
        if res == "SL":
            return "✗ SL"
        if res.startswith("TP"):
            return f"✓ {res}"
        return res[:5]

    @staticmethod
    def _res_tag(d):
        res = d.get("res")
        if res == "SL":
            return "lost"
        if res and res.startswith("TP"):
            return "won"
        if res == "SKIP":
            return ""
        return "running"

    def _signal_row(self, d):
        stop_pct = abs(d["entry"] - d["stop_loss"]) / d["entry"] * 100 \
            if d.get("entry") else 0.0
        tps = d.get("take_profits") or (0, 0, 0)
        return (d["symbol"], mkt_label(d.get("cls", "crypto")),
                d.get("grade", ""), self._res_text(d), num(d["entry"]),
                num(d["stop_loss"]), f"{stop_pct:.2f}%",
                num(tps[0]), num(tps[1]), num(tps[2]),
                f"{d.get('leverage', 0)}x",
                time.strftime("%H:%M", time.localtime(d.get("ts", 0)))
                if d.get("ts") else "--:--")

    def _market_cls(self):
        return MKT_FILTER.get(self.market_var.get())

    def _market_changed(self):
        try:
            self._render("LONG")
            self._render("SHORT")
            self._render_watch()
        except Exception:
            pass                       # widgets not built yet

    @staticmethod
    def _sort_key(col, d):
        tps = d.get("take_profits") or (0, 0, 0)
        e = d.get("entry") or 0
        if col == "coin":
            return d["symbol"]
        if col == "mkt":
            return d.get("cls", "crypto")
        if col == "grade":
            return GRADE_RANK.get(d.get("grade"), 9)
        if col == "res":
            res = d.get("res") or ""
            if res == "SL":
                return 0
            if res.startswith("TP"):
                return 2
            return 1
        if col == "entry":
            return e
        if col == "stop":
            return d.get("stop_loss") or 0
        if col == "stop%":
            return abs(e - (d.get("stop_loss") or 0)) / e if e else 0
        if col == "tp1":
            return tps[0]
        if col == "tp2":
            return tps[1]
        if col == "tp3":
            return tps[2]
        if col == "lev":
            return d.get("leverage") or 0
        if col == "time":
            return d.get("ts") or 0
        return 0

    def _sort_by(self, side, col):
        cur_col, cur_desc = self.sort_state[side]
        if cur_col == col:
            self.sort_state[side] = (col, not cur_desc)
        else:
            self.sort_state[side] = (col, True)      # first click: descending
        self._render(side)

    def _clear_side(self, side):
        self.signals[side] = []
        self.sort_state[side] = (None, False)
        self.filter_var[side].set("")
        self._render(side)
        self._append_log(f"{side.lower()} table cleared")

    def _render(self, side):
        tree = self.trees[side]
        query = self.filter_var[side].get().strip().upper()
        mc = self._market_cls()
        items = [d for d in self.signals[side]
                 if (mc is None or d.get("cls", "crypto") == mc)
                 and (not query or query in d["symbol"].upper())]
        col, desc = self.sort_state[side]
        if col:
            items = sorted(items, key=lambda d: self._sort_key(col, d),
                           reverse=desc)
        tree.delete(*tree.get_children())
        self.rows[side] = {}
        tag = "long" if side == "LONG" else "short"
        for d in items:
            tags = ("hist",) if d.get("_hist") else (tag,)
            rt = self._res_tag(d)
            if rt:
                tags = tags + (rt,)          # outcome colour last
            iid = tree.insert("", "end", values=self._signal_row(d),
                              tags=tags)
            self.rows[side][iid] = d
        self.count_lbls[side].configure(text=str(len(items)))
        total = len(self.signals["LONG"]) + len(self.signals["SHORT"])
        self.lbl_counts.configure(
            text=f"LONG {len(self.signals['LONG'])}    "
                 f"SHORT {len(self.signals['SHORT'])}")
        self._update_today_card()

    def _update_today_card(self):
        today = time.strftime("%Y-%m-%d")
        n = sum(1 for side in ("LONG", "SHORT") for d in self.signals[side]
                if d.get("ts") and
                time.strftime("%Y-%m-%d", time.localtime(d["ts"])) == today)
        self._card_set("today", str(n), FG,
                       f"all time: {len(self.signals['LONG'])} long / "
                       f"{len(self.signals['SHORT'])} short")
        self._update_results_card()

    # ---- signal outcomes: did price reach TP1 or SL first? ------------
    def _resolve_outcomes(self):
        """Start a background check (max 8 fetches per pass, every 60s)."""
        if self._res_busy:
            return
        now = time.time()
        todo = []
        for side in ("LONG", "SHORT"):
            for d in list(self.signals[side]):
                if d.get("res"):
                    continue                  # decided or SKIP already
                age = now - float(d.get("ts") or 0)
                if age < 75:
                    continue                  # give the trade a moment
                if age > 48 * 3600:
                    d["res"] = "SKIP"         # outside 1-minute data reach
                    continue
                if not d.get("stop_loss") or not d.get("take_profits"):
                    d["res"] = "SKIP"
                    continue
                todo.append(d)
        if not todo:
            self._update_results_card()
            return
        self._res_busy = True
        import threading
        threading.Thread(target=self._resolve_worker, args=(todo[:8],),
                         daemon=True).start()

    def _resolve_worker(self, todo):
        try:
            for d in todo:
                try:
                    res = self._outcome_of(d)
                except Exception:
                    res = None                # network hiccup -> retry later
                if res:
                    d["res"] = res
        finally:
            self._res_busy = False
            self._res_dirty = True            # redraw on the next tick

    def _outcome_of(self, d):
        """Walk 1-minute candles after the signal: SL or TP touched first?
        Conservative: a candle touching both counts as SL."""
        sym = d["symbol"]
        t0 = float(d.get("ts") or 0) * 1000.0
        if d.get("cls", "crypto") == "crypto":
            if not self.scanner:
                return None
            data = self.scanner.hub._call(lambda p: p.klines(sym, "1m", 250))
        else:
            import yf_data
            data = yf_data.SOURCE.candles_1m(sym, 400)
        if data is None or len(data.ts) == 0:
            return None
        if float(data.ts[0]) > t0 + 180000.0:
            return "SKIP"                     # signal older than the data
        sl = float(d["stop_loss"])
        tps = [float(x) for x in (d.get("take_profits") or ())]
        long_ = d.get("side") == "LONG"
        for i in range(len(data.ts)):
            if float(data.ts[i]) <= t0:
                continue                      # skip the signal minute itself
            hi, lo = float(data.high[i]), float(data.low[i])
            if long_:
                if lo <= sl:
                    return "SL"
                hit = [k for k, t in enumerate(tps) if hi >= t]
                if hit:
                    return f"TP{max(hit) + 1}"
            else:
                if hi >= sl:
                    return "SL"
                hit = [k for k, t in enumerate(tps) if lo <= t]
                if hit:
                    return f"TP{max(hit) + 1}"
        return None                           # still running

    def _update_results_card(self):
        w = l = open_ = 0
        now = time.time()
        for side in ("LONG", "SHORT"):
            for d in self.signals[side]:
                res = d.get("res")
                if res == "SL":
                    l += 1
                elif res and res.startswith("TP"):
                    w += 1
                elif res not in ("SKIP", "SL") and not (
                        res or "").startswith("TP") and \
                        now - float(d.get("ts") or 0) > 75:
                    open_ += 1
        if w + l:
            rate = 100.0 * w / (w + l)
            colour = GREEN if rate >= 50 else RED
            self._card_set("results", f"{w}W {l}L", colour,
                           f"{rate:.0f}% won • {open_} running")
        else:
            self._card_set("results", "—", FG,
                           f"first result pending • {open_} running")

    def _add_signal(self, sig, telegram_ok=None, history=False):
        d = dict(sig.__dict__) if hasattr(sig, "__dict__") else dict(sig)
        d.setdefault("ts", time.time())
        if history:
            d["_hist"] = True
        side = d["side"]
        self.signals[side].insert(0, d)
        if len(self.signals[side]) > 500:
            self.signals[side] = self.signals[side][:500]
        self._render(side)
        if history:
            return
        tree = self.trees[side]
        kids = tree.get_children()
        if kids:
            tree.selection_set(kids[0])
            tree.see(kids[0])
            self._show_detail(self.rows[side][kids[0]], telegram_ok)
        colour = GREEN if side == "LONG" else RED
        self._card_set("last", f"{side} {d['symbol']}", colour,
                       f"grade {d.get('grade')} • "
                       f"{time.strftime('%H:%M')}")
        self._set_status(f"NEW {side}: {d['symbol']} "
                         f"[{d.get('grade', '')}]", colour)
        self._beep()
        self._append_log(
            f"{side} {d['symbol']}  grade {d.get('grade')}  "
            f"entry {num(d['entry'])}  stop {num(d['stop_loss'])}  "
            + ("telegram SENT" if telegram_ok else "telegram not configured"),
            "sig")

    def _load_history(self):
        if not os.path.exists(config.LOG_FILE):
            return
        try:
            with open(config.LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return
        seen = 0
        for line in reversed(lines[-400:]):
            m = LOG_LINE.match(line.strip())
            if not m:
                continue
            try:
                tps = tuple(float(x) for x in m.group("tp").split(","))
            except ValueError:
                tps = ()
            d = {"symbol": m.group("sym"), "side": m.group("side"),
                 "grade": m.group("grade"), "score": int(m.group("score")),
                 "entry": float(m.group("entry")),
                 "stop_loss": float(m.group("sl")), "take_profits": tps,
                 "leverage": int(m.group("lev")), "ts": 0, "_hist": True,
                 "cls": m.group("mkt") or "crypto"}
            if m.group("prob"):
                d["prob"] = int(m.group("prob")) / 100.0
            try:
                d["ts"] = time.mktime(time.strptime(m.group("ts"),
                                                    "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                d["ts"] = 0
            self.signals[d["side"]].append(d)
            seen += 1
        self._render("LONG")
        self._render("SHORT")
        if seen:
            self._append_log(f"loaded {seen} past signal(s) from "
                             f"{config.LOG_FILE}", "head")

    # =================================================== detail
    def _on_select(self, event):
        side = "LONG" if event.widget is self.trees["LONG"] else "SHORT"
        sel = event.widget.selection()
        if sel:
            d = self.rows[side].get(sel[0])
            if d:
                self._show_detail(d)

    def _show_detail(self, d, telegram_ok=None):
        t = self.txt_detail
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f"{d['side']}  {d['symbol']}", ("head",))
        t.insert("end", f"    grade {d.get('grade', '?')}  "
                        f"(score {d.get('score', '?')})")
        if d.get("ts"):
            stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(d["ts"]))
            t.insert("end", f"    {stamp}", ("dim",))
        t.insert("end", "\n")
        e, sl = d.get("entry", 0), d.get("stop_loss", 0)
        tps = d.get("take_profits") or ()
        pct = lambda x: f"{(x - e) / e * 100:+.2f}%" if e else ""
        t.insert("end", f"  Entry (market) : {num(e)}\n")
        t.insert("end", f"  Stop loss      : {num(sl)}   {pct(sl)}\n", ("bad",))
        for i, tp in enumerate(tps, 1):
            t.insert("end", f"  TP{i}            : {num(tp)}   {pct(tp)}\n",
                     ("ok",))
        if d.get("size_usdt"):
            t.insert("end",
                     f"  Leverage       : {d.get('leverage')}x    "
                     f"position {d['size_usdt']:,.0f} USDT   "
                     f"margin {d.get('margin', 0):,.1f} USDT\n")
            t.insert("end", f"  Risk           : "
                            f"{config.RISK_PER_TRADE_PCT}% of "
                            f"{config.ACCOUNT_BALANCE:,.0f} USDT account\n")
        t.insert("end", "\n  CHECKLIST\n", ("head",))
        ck = d.get("checklist")
        if ck:
            for name, ok, detail in ck:
                t.insert("end", "    " + ("✅ " if ok else "⚠️  "))
                t.insert("end", f"{name}: ")
                t.insert("end", f"{detail}\n", ("ok" if ok else "warn",))
        else:
            t.insert("end", "    loaded from signals.log (history entry)\n",
                     ("dim",))
        if telegram_ok is not None:
            t.insert("end", "\n  Telegram: ", ("dim",))
            t.insert("end", "SENT ✅\n" if telegram_ok else
                     "not configured / failed (set token in config.py)\n",
                     ("ok" if telegram_ok else "warn",))
        t.insert("end", "\n  ⚠️ Not financial advice. Set the stop-loss the "
                        "moment you enter. Keep funds in your wallet.\n",
                 ("dim",))
        t.configure(state="disabled")

    # =================================================== context / cards
    def _update_context(self, ctx):
        self._ctx_seen = True
        f, s, b, n = ctx.flow, ctx.sentiment, ctx.btc, ctx.news

        # banner
        if n.status == "HALT":
            self.banner.configure(bg="#3d1354", fg=PURPLE,
                                  text="🛑  NEWS HALT - CRITICAL HEADLINES - "
                                       "NO TRADING")
            self._card_set("flow", "NEWS HALT", PURPLE, n.note)
        else:
            bg, fg, txt = BANNER.get(f.money_flow, BANNER["UNKNOWN"])
            self.banner.configure(bg=bg, fg=fg, text="   " + txt)
            flow_colour = {"ROTATING_IN": GREEN, "BTC_SEASON": BLUE,
                           "LEAVING": YELLOW, "PANIC": RED}.get(f.money_flow,
                                                                MUTED)
            self._card_set("flow", f.money_flow, flow_colour,
                           f"dom {f.dominance:.1f}% {f.dominance_trend} • "
                           f"cap 24h {f.mcap_delta_pct:+.1f}%")

        # fear & greed card
        if s.value >= 0:
            colour = YELLOW if (s.value <= 25 or s.value >= 75) else FG
            self._card_set("fg", f"{s.value}", colour, s.label)
        else:
            self._card_set("fg", "—", MUTED, "no data")

        # BTC card
        if b.ok:
            self._card_set("btc", "BULLISH" if b.above_ema120 else "BEARISH",
                           GREEN if b.above_ema120 else RED,
                           f"{b.price:,.0f} vs EMA120 {b.ema120:,.0f} • "
                           f"{b.cross} cross")

        # checklist text
        t = self.txt_check
        t.configure(state="normal")
        t.delete("1.0", "end")

        def row(label, value, tag, extra=""):
            t.insert("end", f"{label:<22}", ("dim",))
            t.insert("end", value, (tag,))
            if extra:
                t.insert("end", f"\n     {extra}", ("dim",))
            t.insert("end", "\n")

        t.insert("end", "1. NEWS\n", ("head",))
        row("   status", n.status,
            "bad" if n.status == "HALT" else
            ("warn" if n.status == "WARNING" else "ok"), n.note)
        if n.status != "OK" and n.bad_items:
            for h in n.bad_items[:3]:
                t.insert("end", f"     - {h[:64]}\n", ("warn",))
        row("2. BTC DOMINANCE",
            f"{f.dominance:.1f}%   {f.dominance_trend}",
            "bad" if f.dominance_trend == "RISING" else
            ("ok" if f.dominance_trend == "FALLING" else "warn"),
            f"{f.dominance_delta:+.1f} pts   ({f.method})")
        row("3. TOTAL MARKET CAP",
            f"${f.total_mcap / 1e12:.2f}T   24h {f.mcap_delta_pct:+.1f}%",
            "ok" if f.mcap_delta_pct > config.STABLE_MCAP_PCT else "bad")
        row("4. MONEY FLOW", f.money_flow,
            "ok" if f.money_flow in ("ROTATING_IN", "BTC_SEASON") else
            ("bad" if f.money_flow in ("LEAVING", "PANIC") else "warn"),
            f.note)
        row("5. FEAR & GREED",
            (f"{s.value}  {s.label}" if s.value >= 0 else "no data"),
            "warn" if 0 <= s.value <= 30 or s.value >= 75 else "ok", s.note)
        row("6. BTC ABOVE EMA120?",
            ("YES - BULLISH" if b.above_ema120 else "NO - BEARISH"),
            "ok" if b.above_ema120 else "bad",
            f"price {b.price:,.0f}  vs  EMA120 {b.ema120:,.0f}")
        row("7. GOLDEN / DEATH CROSS", b.cross,
            "ok" if b.cross == "GOLDEN" else
            ("bad" if b.cross == "DEATH" else "warn"))
        row("8. DAILY BOLLINGER + RSI",
            f"RSI {b.rsi:.0f}   {b.bb_state}",
            "warn" if b.bb_state != "INSIDE" or b.rsi <= 30 or
            b.rsi >= 70 else "ok")
        t.configure(state="disabled")

    # =================================================== log / status
    def _append_log(self, text, tag=None):
        stamp = time.strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        for line in str(text).splitlines() or [""]:
            self.txt_log.insert("end", f"{stamp}  {line}\n", tag or ())
        if int(self.txt_log.index("end-1c").split(".")[0]) > 900:
            self.txt_log.delete("1.0", "400.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_status(self, text, colour=MUTED):
        self.lbl_status.configure(text=f"● {text}", foreground=colour)

    def _set_bar(self, text, right=None):
        self.lbl_bar.configure(text=f"  {text}")
        if right is not None:
            self.lbl_next.configure(text=right)

    def _beep(self):
        if not self.sound_on:
            return
        def go():
            try:
                import winsound
                winsound.Beep(1200, 260)
                time.sleep(0.12)
                winsound.Beep(1600, 260)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    # =================================================== worker
    def _cb_log(self, text):
        self.q.put(("log", text))

    def _cb_context(self, ctx):
        self.q.put(("context", ctx))

    def _cb_signal(self, sig, ok):
        self.q.put(("signal", sig, ok))

    def _cb_progress(self, done, total):
        self.q.put(("progress", done, total))

    def _cb_watch(self, row):
        self.q.put(("watch", row))

    def start(self):
        if self.worker and self.worker.is_alive():
            self._append_log("already running")
            return
        self.stop_evt.clear()
        set_awake(True)
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        self._set_status("STARTING...", YELLOW)

    def stop(self):
        self.stop_evt.set()
        set_awake(False)
        self._set_status("STOPPING...", YELLOW)
        self._append_log("stop requested - finishing current scan...")

    def scan_now(self):
        if self.worker and self.worker.is_alive():
            self.scan_request.set()
            self._append_log("scan requested")
        else:
            self._append_log("starting the scanner first...")
            self.start()
            self.scan_request.set()

    def _worker_loop(self):
        try:
            from scanner import Scanner
            self.scanner = Scanner(on_signal=self._cb_signal,
                                   on_context=self._cb_context,
                                   on_log=self._cb_log,
                                   on_progress=self._cb_progress,
                                   on_watch=self._cb_watch)
        except Exception:
            self.q.put(("log", traceback.format_exc()))
            self.q.put(("status", ("ERROR", RED)))
            return
        self.q.put(("status", ("RUNNING", GREEN)))
        tick = max(0.2, float(config.TICK_EVERY_SEC))
        try:
            self.scanner.refresh_context(force=True)
            while not self.stop_evt.is_set():
                try:
                    if self.scan_request.is_set():
                        self.scan_request.clear()
                        self.scanner.run_scan()
                    now = time.time()
                    if now - self.scanner.last_context >= config.CONTEXT_REFRESH_SEC:
                        self.scanner.refresh_context(force=True)
                    if now - self.scanner.last_scan >= config.SCAN_INTERVAL_SEC:
                        self.scanner.run_scan()
                except Exception:
                    self.q.put(("log", traceback.format_exc()))
                    time.sleep(5)
                # 24/7 heartbeat: wake up every second, check again
                for _ in range(int(tick / 0.2) or 1):
                    if self.stop_evt.is_set():
                        break
                    time.sleep(0.2)
        finally:
            try:
                from context import save_state
                save_state(self.scanner.state)
            except Exception:
                pass
            set_awake(False)
            self.q.put(("status", ("STOPPED", MUTED)))
            self.q.put(("log", "scanner stopped - state saved"))

    def telegram_test(self):
        def go():
            try:
                from notifier import send_text
                ok = send_text("<b>Desktop app test</b>\n"
                               "Assalam-o-Alaikum! Your signal window is "
                               "connected. LONG/SHORT alerts will arrive here.")
                self.q.put(("log", "telegram: SENT ✅" if ok else
                            "telegram: FAILED - check TELEGRAM_BOT_TOKEN / "
                            "TELEGRAM_CHAT_ID in config.py"))
            except Exception:
                self.q.put(("log", traceback.format_exc()))
        threading.Thread(target=go, daemon=True).start()
        self._append_log("sending telegram test...")

    # =================================================== settings
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg=PANEL)
        win.geometry("440x560")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        fields = [
            ("balance", "Account balance (USDT)",
             str(int(config.ACCOUNT_BALANCE))),
            ("leverage", "Leverage (max 50)", str(config.MAX_LEVERAGE)),
            ("risk_pct", "Risk per trade (% of balance)",
             str(config.RISK_PER_TRADE_PCT)),
            ("min_vol_m", "Min 24h volume (millions $)",
             str(config.MIN_QUOTE_VOLUME_24H / 1_000_000)),
            ("max_coins", "Max coins to scan (0 = ALL)", str(config.MAX_COINS)),
            ("scan_sec", "Pause between scans (seconds)",
             str(config.SCAN_INTERVAL_SEC)),
        ]
        vars_ = {}
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        for key, label, val in fields:
            ttk.Label(body, text=label).pack(anchor="w", pady=(7, 0))
            var = tk.StringVar(value=val)
            vars_[key] = var
            ttk.Entry(body, textvariable=var, width=30).pack(anchor="w")

        ttk.Label(body, text="Minimum signal grade").pack(anchor="w",
                                                          pady=(9, 0))
        grade = tk.StringVar(value=config.MIN_GRADE)
        ttk.Combobox(body, textvariable=grade,
                     values=("A+", "A", "B", "C"),
                     state="readonly", width=8).pack(anchor="w")
        ttk.Label(body, text="C = max signals (any tradeable setup)  •  "
                             "B = solid  •  A/A+ = strongest only",
                  foreground="#8b949e", font=("Segoe UI", 8),
                  wraplength=280).pack(anchor="w", pady=(2, 0))

        strong = tk.BooleanVar(value=getattr(config, "STRONG_ONLY", False))
        ttk.Checkbutton(body, text="STRONG setups only (grade A + clean news"
                                   " + daily dip/top + fresh cross)",
                        variable=strong).pack(anchor="w", pady=(8, 0))
        tg = tk.BooleanVar(value=config.TELEGRAM_ENABLED)
        ttk.Checkbutton(body, text="Send signals to Telegram",
                        variable=tg).pack(anchor="w", pady=(8, 0))
        auto = tk.BooleanVar(value=config.AUTO_START)
        ttk.Checkbutton(body, text="Auto-start scanning when app opens",
                        variable=auto).pack(anchor="w", pady=(2, 0))
        awake = tk.BooleanVar(value=config.KEEP_AWAKE)
        ttk.Checkbutton(body, text="Keep PC awake while scanning (24/7)",
                        variable=awake).pack(anchor="w", pady=(2, 0))

        def save():
            data = load_settings()
            try:
                data["balance"] = float(vars_["balance"].get())
                data["leverage"] = max(1, min(50, int(vars_["leverage"].get())))
                data["risk_pct"] = float(vars_["risk_pct"].get())
                data["min_vol_m"] = float(vars_["min_vol_m"].get())
                data["max_coins"] = max(0, int(vars_["max_coins"].get()))
                data["scan_sec"] = max(0, min(300,
                                              int(vars_["scan_sec"].get())))
            except ValueError:
                messagebox.showerror("Settings", "Please enter valid numbers.",
                                     parent=win)
                return
            data["min_grade"] = grade.get()
            data["strong"] = bool(strong.get())
            data["telegram"] = bool(tg.get())
            data["autostart"] = bool(auto.get())
            data["keep_awake"] = bool(awake.get())
            store_settings(data)
            apply_settings(data)
            self.sound_on = self.sound_var.get()
            self._append_log(
                f"settings saved: {int(data['balance'])} USDT, "
                f"{data['leverage']}x, risk {data['risk_pct']}%, "
                f"grade {data['min_grade']}, "
                f"{'ALL' if data['max_coins'] == 0 else data['max_coins']} coins, "
                f"pause {data['scan_sec']}s", "head")
            win.destroy()

        btns = ttk.Frame(body)
        btns.pack(side="bottom", pady=14, fill="x")
        ttk.Button(btns, text="SAVE", command=save).pack(side="right", padx=6)
        ttk.Button(btns, text="CANCEL", command=win.destroy).pack(side="right")

    # =================================================== right-click menu
    def _ctx_menu(self, event, side):
        tree = self.trees[side]
        iid = tree.identify_row(event.y)
        if not iid:
            return
        tree.selection_set(iid)
        d = self.rows[side].get(iid)
        if not d:
            return
        self._show_detail(d)
        menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=FG,
                       activebackground=BLUE, activeforeground="#ffffff")

        def copy():
            tps = ", ".join(num(x) for x in (d.get("take_profits") or ()))
            text = (f"{d['side']} {d['symbol']} grade {d.get('grade')} | "
                    f"entry {num(d['entry'])} | stop {num(d['stop_loss'])} | "
                    f"TP: {tps} | {d.get('leverage')}x")
            self.clipboard_clear()
            self.clipboard_append(text)
            self._append_log("signal copied to clipboard")

        def chart():
            sym = d["symbol"]
            webbrowser.open("https://www.tradingview.com/chart/?symbol="
                            f"BINANCE:{sym}")
            self._append_log(f"opening TradingView chart for {sym}")

        menu.add_command(label="📋  Copy signal text", command=copy)
        menu.add_command(label="📈  Open chart in TradingView", command=chart)
        menu.add_separator()
        menu.add_command(label="🗑  Clear this table",
                         command=lambda: self._clear_side(side))
        menu.tk_popup(event.x_root, event.y_root)

    # =================================================== queue pump + tick
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    text = msg[1]
                    tag = "err" if ("Traceback" in str(text) or
                                    str(text).lower().startswith("failed")) \
                        else None
                    self._append_log(text, tag)
                elif kind == "context":
                    self._update_context(msg[1])
                elif kind == "signal":
                    self._add_signal(msg[1], telegram_ok=msg[2])
                elif kind == "status":
                    text, colour = msg[1]
                    self._set_status(text, colour)
                elif kind == "watch":
                    w = msg[1]
                    self.watch[w["key"]] = w
                    self._watch_dirty = True
                elif kind == "progress":
                    done, total = msg[1], msg[2]
                    if total:
                        self.pbar.configure(maximum=total, value=done)
                        if done < total:
                            self._set_bar(f"scanning {done}/{total} coins...")
                    else:
                        self.pbar.configure(value=0)
        except queue.Empty:
            pass
        self.after(250, self._poll)

    def _tick(self):
        """1-second heartbeat: clock, watchlist redraw, next-scan countdown."""
        self.lbl_clock.configure(text=time.strftime("%H:%M:%S"))
        if self._watch_dirty:
            try:
                self._render_watch()
            except Exception:
                pass
        # ---- signal outcomes: check TP1 vs SL every minute
        if time.time() - self._last_res_run > 60:
            self._last_res_run = time.time()
            try:
                self._resolve_outcomes()
            except Exception:
                pass
        if self._res_dirty:
            self._res_dirty = False
            try:
                self._update_results_card()
                self._render("LONG")
                self._render("SHORT")
            except Exception:
                pass
        if self.worker and self.worker.is_alive() and self.scanner:
            left = config.SCAN_INTERVAL_SEC - (time.time() -
                                               self.scanner.last_scan)
            if self.scanner.last_scan and left > 0:
                self.lbl_next.configure(text=f"next scan in {int(left)}s")
            else:
                self.lbl_next.configure(text="scanning now...")
            provider = self.hub_name() if self.scanner else ""
            self._set_bar(f"{provider} • {config.SCAN_WORKERS} workers • "
                          f"tick {config.TICK_EVERY_SEC}s • "
                          f"min grade {config.MIN_GRADE}"
                          f"{' +STRONG' if getattr(config, 'STRONG_ONLY', False) else ''} • "
                          f"watch {len(self.watch)}")
        self.after(1000, self._tick)

    def hub_name(self):
        try:
            return f"provider {self.scanner.hub.provider_name}"
        except Exception:
            return "provider -"

    # =================================================== close
    def _on_close(self):
        if self.worker and self.worker.is_alive() and \
                not messagebox.askyesno("Quit",
                                        "Stop scanning and close the app?"):
            return
        self.stop_evt.set()
        set_awake(False)
        # make sure the market state is written even if the worker is
        # still busy scanning when we close
        try:
            if self.scanner:
                from context import save_state
                save_state(self.scanner.state)
        except Exception:
            pass
        w = self.worker
        if w and w.is_alive():
            w.join(timeout=2.0)
        self.destroy()

    # =================================================== smoke test
    def run_smoke(self):
        """Opens the window, starts the scanner, waits for live data, exits."""
        print("[smoke] opening window + starting scanner ...")
        if not (self.worker and self.worker.is_alive()):
            self.start()
        self._smoke_start = time.time()
        self.after(500, self._smoke_check)

    def _smoke_check(self):
        waited = time.time() - self._smoke_start
        if not self._ctx_seen:
            if waited > 120:
                return self._finish_smoke()
            return self.after(500, self._smoke_check)
        # watch rows stream in during the first scan - wait for them
        if not self.watch and waited < 90:
            return self.after(500, self._smoke_check)
        if waited < 6:
            return self.after(500, self._smoke_check)
        if self._res_busy or self._res_dirty:   # outcome worker/ redraw pending
            return self.after(500, self._smoke_check)
        rows = sum(len(self.trees[s].get_children()) for s in self.trees)
        try:
            self._render_watch()
        except Exception:
            pass
        wrows = len(self.tree_watch.get_children())
        cards_ok = all(k in self.cards for k in
                       ("flow", "today", "results", "fg", "btc", "last"))
        print(f"[smoke] live checklist received after {waited:.1f}s")
        print(f"[smoke] UI ready: {rows} signal row(s), {wrows} watch row(s), "
              f"cards={cards_ok}")
        print(f"[smoke] results card: "
              f"{self.cards['results']['val'].cget('text')}  "
              f"({self.cards['results']['sub'].cget('text')})")
        print(f"[smoke] RESULT: {'PASS' if wrows else 'FAIL'}"
              f"{'' if wrows else ' (watchlist empty)'}")
        self.stop_evt.set()
        self.after(1200, self.destroy)

    def _finish_smoke(self):
        print("[smoke] RESULT: FAIL (no live checklist within 120s)")
        self.stop_evt.set()
        self.after(800, self.destroy)


# ---------------------------------------------------------------- cloud
def _cloud_heartbeat(app, first_delay=60, interval=300):
    """
    Kick the GitHub Actions scanner (scan.yml) every `interval` seconds.

    The phone app only sees signals the CLOUD run publishes, and GitHub's
    cron schedule has proven unreliable (most 5-minute ticks never fired),
    so the desktop - which is on 24/7 anyway - triggers the workflow as a
    backup heartbeat.  Errors are logged to the app LOG pane; the real
    cron still runs whenever GitHub honours it.
    """
    import shutil
    import subprocess
    gh = shutil.which("gh")
    if not gh:
        app.q.put(("log", "[cloud] gh CLI not found - cloud heartbeat OFF "
                          "(GitHub cron is the only trigger)"))
        return
    time.sleep(first_delay)
    app.q.put(("log", f"[cloud] heartbeat on - triggering cloud scan every "
                      f"{interval // 60} min (phone feed)"))
    fails = 0
    while True:
        try:
            r = subprocess.run([gh, "workflow", "run", "scan.yml",
                                "--ref", "main"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                if fails:
                    fails = 0
                    app.q.put(("log", "[cloud] heartbeat trigger OK again"))
            else:
                fails += 1
                if fails <= 3:
                    app.q.put(("log", "[cloud] heartbeat trigger failed: "
                                      + (r.stderr or "").strip()[:120]))
        except Exception as e:
            fails += 1
            if fails <= 3:
                app.q.put(("log", f"[cloud] heartbeat error: {e}"))
        time.sleep(interval)


def main():
    _redirect_output()
    smoke = "--smoke" in sys.argv

    # only one instance allowed - if it is already open, just focus it
    mutex, already = _acquire_single_instance()
    if already:
        _focus_existing_window()
        print("app already running - window brought to the front")
        return

    try:
        app = SignalApp(smoke=smoke)
        if smoke:
            app.run_smoke()
        else:
            # keep the phone feed alive even when GitHub's cron skips
            threading.Thread(target=_cloud_heartbeat, args=(app,),
                             daemon=True).start()
        app.mainloop()
    except SystemExit:
        raise
    except Exception:
        _crash_log()          # keep a copy on disk - console may not exist
        raise
    finally:
        if mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(mutex)
            except Exception:
                pass


if __name__ == "__main__":
    main()
