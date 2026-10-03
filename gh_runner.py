"""
HEADLESS SCANNER for GitHub Actions (the 24/7 cloud runner).

Runs exactly one full pass - context refresh + one scan - then writes
dashboard/data.json (the JSON the mobile web dashboard reads) and exits.

    python gh_runner.py            one scan, then exit
    python gh_runner.py --skip-yf  crypto only (fallback if Yahoo blocks us)

Telegram fires through the same path as the desktop app: run_scan()
itself calls notifier.send_text(), so it works whenever the environment
variables TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set (config.py reads
them via os.getenv).
"""
import json
import os
import sys
import time
import traceback

import config

DASH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
DATA = os.path.join(DASH, "data.json")

new_signals = []
watch_rows = {}


def apply_settings():
    """
    Keep the cloud runner on the SAME rules as the desktop app:
      1. app_settings.json  (exists locally / in your own checkout)
      2. env vars STRONG_ONLY / MIN_GRADE / PROB_MIN (set in scan.yml,
         because app_settings.json is not committed)
      3. config.py defaults
    """
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "app_settings.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    mapping = {"min_grade": ("MIN_GRADE", str),
               "strong": ("STRONG_ONLY", bool),
               "leverage": ("MAX_LEVERAGE", int)}
    for key, (attr, cast) in mapping.items():
        if key in data:
            try:
                setattr(config, attr, cast(data[key]))
            except (TypeError, ValueError):
                pass
    if "MIN_GRADE" in os.environ:
        config.MIN_GRADE = os.environ["MIN_GRADE"]
    if "STRONG_ONLY" in os.environ:
        config.STRONG_ONLY = os.environ["STRONG_ONLY"].strip().lower() \
            in ("1", "true", "yes", "on")
    if "PROB_MIN" in os.environ:
        try:
            config.PROB_MIN = float(os.environ["PROB_MIN"])
        except ValueError:
            pass
    print(f"[gh] rules: min_grade={config.MIN_GRADE} "
          f"strong={config.STRONG_ONLY} prob_min={config.PROB_MIN:.0%} "
          f"tp1={config.TP1_R}R", flush=True)


def on_signal(sig, ok):
    d = {k: v for k, v in sig.__dict__.items() if not k.startswith("_")}
    d["take_profits"] = list(d.get("take_profits") or ())
    d["checklist"] = [[n, bool(o), str(t)] for n, o, t in
                      (d.get("checklist") or ())]
    d["telegram_ok"] = bool(ok)
    new_signals.append(d)


def take_desktop_signals():
    """
    Signals the DESKTOP app detected arrive as the workflow input
    `extra_signals` (the app runs `gh workflow run -f extra_signals=...`
    on every signal).  The heartbeat's 5-minute cloud scan alone can
    miss a cross that only lives ~10 minutes - EURUSD/USDSEK on Oct 2
    never reached the phone that way - so the desktop hands them over.
    """
    raw = (os.getenv("EXTRA_SIGNALS") or "").strip()
    if not raw:
        return 0
    try:
        items = json.loads(raw)
    except ValueError:
        print(f"[in] extra_signals is not valid JSON: {raw[:80]}",
              flush=True)
        return 0
    added = 0
    for d in items if isinstance(items, list) else [items]:
        if not isinstance(d, dict) or not d.get("symbol") or not d.get("side"):
            continue
        new_signals.append(d)
        added += 1
        print(f"[in] desktop signal injected: {d.get('symbol')} "
              f"{d.get('side')} grade={d.get('grade')}", flush=True)
    return added


def collapse_reposts(signals, window=300):
    """
    The desktop push and the cloud scan can detect the SAME cross
    seconds apart (different ts), and the old history can hold a copy
    too - keep only the earliest copy.  Cooldown is 30 min per side, so
    a repeat within `window` seconds can only be a re-detection.
    """
    kept = []
    for d in sorted(signals, key=lambda x: x.get("ts") or 0):
        if any(k.get("symbol") == d.get("symbol")
               and k.get("side") == d.get("side")
               and abs((k.get("ts") or 0) - (d.get("ts") or 0)) <= window
               for k in kept):
            continue
        kept.append(d)
    return kept


def on_watch(w):
    try:
        watch_rows[w["key"]] = {k: v for k, v in w.items()
                                if not str(k).startswith("_")}
    except Exception:
        pass


def on_log(text):
    print(text, flush=True)


def _ctx_summary(scanner):
    out = {}
    c = scanner.ctx
    if c is not None:
        out["btc"] = {"price": c.btc.price, "ema120": c.btc.ema120,
                      "above": c.btc.above_ema120, "cross": c.btc.cross,
                      "rsi": round(c.btc.rsi, 1)}
        out["news"] = {"status": c.news.status, "note": c.news.note}
        out["flow"] = {"money_flow": c.flow.money_flow,
                       "dominance": round(c.flow.dominance, 2),
                       "mcap_24h": round(c.flow.mcap_delta_pct, 2)}
        out["sentiment"] = {"value": c.sentiment.value,
                            "label": c.sentiment.label}
    sessions = {"crypto": "open (24/7)"}
    try:
        # ask the session gate itself - class contexts keep the default
        from yf_data import session_status
        for cls in ("forex", "metal", "stock"):
            ok, note = session_status(cls)
            sessions[cls] = "open" if ok else (note or "closed")
    except Exception as exc:                     # pragma: no cover
        sessions["error"] = str(exc)[:60]
    out["sessions"] = sessions
    return out


def main():
    from scanner import Scanner
    s = Scanner(on_signal=on_signal, on_context=None, on_log=on_log,
                on_progress=None, on_watch=on_watch)

    if "--skip-yf" in sys.argv:
        config.ENABLE_FOREX = False
        config.ENABLE_METAL = False
        config.ENABLE_STOCKS = False
        print("[gh] Yahoo disabled - crypto only", flush=True)

    t0 = time.time()
    apply_settings()
    s.refresh_context(force=True)
    s.run_scan()
    take_desktop_signals()
    took = time.time() - t0

    # ---- merge with the previous data.json (keep history) ----
    prev = []
    try:
        with open(DATA, "r", encoding="utf-8") as f:
            prev = json.load(f).get("signals", []) or []
    except (OSError, ValueError):
        pass
    seen = {(d.get("ts"), d.get("symbol"), d.get("side"))
            for d in new_signals}
    merged = new_signals + [d for d in prev
                            if (d.get("ts"), d.get("symbol"),
                                d.get("side")) not in seen]
    merged = sorted(collapse_reposts(merged),
                    key=lambda d: d.get("ts") or 0,
                    reverse=True)[:40]

    # ---- TP/SL outcome of every tracked signal (the mobile app shows it)
    try:
        from outcomes import update_outcomes
        update_outcomes(merged, hub=s.hub, log=on_log)
    except Exception:
        traceback.print_exc()

    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC",
                                 time.gmtime()),
        "epoch": int(time.time()),
        "took_sec": round(took, 1),
        "filters": {
            "min_grade": config.MIN_GRADE,
            "strong": bool(getattr(config, "STRONG_ONLY", False)),
            "prob_min": getattr(config, "PROB_MIN", 0),
            "tp1_r": getattr(config, "TP1_R", 2),
            "leverage": config.MAX_LEVERAGE,
        },
        "context": _ctx_summary(s),
        "stats": {"scanned": s.stats.get("scanned", 0),
                  "errors": s.stats.get("errors", 0),
                  "signals_new": len(new_signals)},
        "signals": merged,
        "watch": sorted(watch_rows.values(),
                        key=lambda w: -(w.get("score") or -99)),
    }
    os.makedirs(DASH, exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)

    print(f"[gh] scan done in {took:.0f}s - "
          f"{len(new_signals)} new signal(s), "
          f"{len(watch_rows)} watch rows, "
          f"{s.stats.get('errors', 0)} data errors "
          f"-> dashboard/data.json",
          flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
