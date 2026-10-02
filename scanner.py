"""
================================================================
  FUTURE TRADING SIGNAL SCANNER
  Runs the whole checklist on a loop and sends LONG / SHORT
  signals to Telegram.

  Run once (one full scan, then exit):   python scanner.py --once
  Normal mode (scans all day):           python scanner.py
  Test telegram:                         python scanner.py --test-telegram
================================================================
"""
import argparse
import sys
import time
import traceback

import config


def parse_args():
    p = argparse.ArgumentParser(description="Future trading signal scanner")
    p.add_argument("--once", action="store_true", help="scan once and exit")
    p.add_argument("--test-telegram", action="store_true",
                   help="send a test message to Telegram and exit")
    p.add_argument("--provider", choices=["auto", "binance", "okx"],
                   default=None, help="force a data provider")
    p.add_argument("--coins", type=int, default=None,
                   help="max number of coins to scan (0 = all)")
    p.add_argument("--balance", type=float, default=None,
                   help="account balance in USDT for position sizing")
    p.add_argument("--min-grade", choices=["A+", "A", "B", "C"],
                   default=None,
                   help="lowest signal grade to send (C = every "
                        "tradeable setup)")
    return p.parse_args()


def apply_args(args):
    if args.provider:
        config.DATA_PROVIDER = args.provider
    if args.coins is not None:
        config.MAX_COINS = args.coins
    if args.balance:
        config.ACCOUNT_BALANCE = args.balance
    if args.min_grade:
        config.MIN_GRADE = args.min_grade


# ------------------------------------------------------------------
def in_cooldown(state, symbol, side):
    key = f"{symbol}:{side}"
    last = state.get("cooldowns", {}).get(key, 0)
    return (time.time() - last) < config.SIGNAL_COOLDOWN_MIN * 60


def set_cooldown(state, symbol, side):
    state.setdefault("cooldowns", {})[f"{symbol}:{side}"] = time.time()
    # keep the dict small
    if len(state["cooldowns"]) > 2000:
        now = time.time()
        state["cooldowns"] = {
            k: v for k, v in state["cooldowns"].items()
            if now - v < config.SIGNAL_COOLDOWN_MIN * 60
        }


# ------------------------------------------------------------------
class Scanner:
    """
    The signal engine.

    It can run two ways:
      * CLI mode  -> prints to console, sends Telegram   (callbacks = None)
      * App mode  -> app.py passes on_signal / on_context / on_log callbacks
                     so the desktop window can display everything live.
    """
    def __init__(self, on_signal=None, on_context=None, on_log=None,
                 on_progress=None, on_watch=None):
        from market_data import DataHub
        import context as ctx_mod
        self.hub = DataHub()
        self.ctx_mod = ctx_mod
        self.state = ctx_mod.load_state()
        self.ctx = None
        self.class_ctx = {}          # {"forex": Context, "metal": ..., "stock": ...}
        self._session_state = {}     # cls -> last open/closed (for logging)
        self.last_context = 0.0
        self.last_scan = 0.0
        self.stats = {"scanned": 0, "blocked": {}, "signals": 0, "errors": 0}
        # GUI callbacks
        self.on_signal = on_signal      # fn(signal, telegram_ok)
        self.on_context = on_context    # fn(context)
        self.on_log = on_log            # fn(text)
        self.on_progress = on_progress  # fn(done, total) - scan progress bar
        self.on_watch = on_watch        # fn(watch_row) - ready & waiting list
        import threading
        self._stats_lock = threading.Lock()

    def _log(self, text=""):
        if self.on_log:
            self.on_log(str(text))
        else:
            print(text)

    def _progress(self, done, total):
        if self.on_progress:
            try:
                self.on_progress(done, total)
            except Exception:
                pass

    # -------------------------------------------------- context refresh
    def refresh_context(self, force=False):
        if self.ctx and not force and \
                time.time() - self.last_context < config.CONTEXT_REFRESH_SEC:
            return self.ctx
        self._log(f"[{time.strftime('%H:%M:%S')}] refreshing news / dominance / "
                  f"fear&greed / BTC daily ...")
        self.ctx = self.ctx_mod.build_context(self.hub, self.state)
        self.last_context = time.time()
        self._log(self.ctx_mod.dashboard(self.ctx))
        self._refresh_class_contexts()
        if self.on_context:
            self.on_context(self.ctx)
        return self.ctx

    # ------------------------------------------- forex / metals / stocks
    def _refresh_class_contexts(self):
        """Market layer for the non-crypto classes: DXY for forex+gold,
        SPY for stocks (daily bars, cached 6h by the yahoo source)."""
        from yf_data import SOURCE, ALL_CLASSES, bench_symbol, instruments
        for cls in ALL_CLASSES:
            if not instruments(cls):
                continue
            bench = bench_symbol(cls)
            try:
                regime = self.ctx_mod.analyse_daily(
                    SOURCE.candles_1d(bench), bench)
            except Exception as e:
                regime = self.ctx_mod.BtcRegime(ok=False, note=str(e))
                self._log(f"  [data] {cls} benchmark {bench}: {e}")
            self.class_ctx[cls] = self.ctx_mod.build_class_context(cls, regime)

    def _instrument_tasks(self):
        """[(symbol, class_context)] for forex/metals/stocks whose session
        is open right now - closed markets are skipped (logged once)."""
        import dataclasses
        from yf_data import (ALL_CLASSES, session_status, instruments,
                             bench_inverted)
        tasks = []
        for cls in ALL_CLASSES:
            syms = instruments(cls)
            if not syms:
                continue
            open_ok, note = session_status(cls)
            if self._session_state.get(cls) is not open_ok:
                self._session_state[cls] = open_ok
                msg = (f"session OPEN - {len(syms)} instruments"
                       if open_ok else note)
                self._log(f"  [{cls}] {msg}")
            if not open_ok:
                continue
            base = self.class_ctx.get(cls)
            if base is None:
                continue
            for s in syms:
                if bench_inverted(s, cls):
                    tasks.append((s, dataclasses.replace(
                        base, bench_inverted=True)))
                else:
                    tasks.append((s, base))
        return tasks

    # -------------------------------------------------- watchlist row
    def _emit_watch(self, symbol, ctx, coin_reg, trig, sig, reason):
        """
        Tell the desktop app which sides of this coin are worth watching:
        score >= WATCH_MIN_SCORE on the best side, OR a live 2-min cross.
        This is what fills the "READY & WAITING" panel - read only, it
        never sends anything by itself.
        """
        if not self.on_watch:
            return
        import strategy
        fired = trig.fired
        for side in ("LONG", "SHORT"):
            score, blk = strategy.opportunity(ctx, coin_reg, side)
            if score <= -99:                     # no daily data
                continue
            if fired == side:
                if sig is not None and sig.side == side:
                    status = ("cross NOW - cooldown (sent earlier)"
                              if in_cooldown(self.state, symbol, side)
                              else f"TRIGGERED -> grade {sig.grade} sent")
                elif reason == "cooldown":
                    status = "cross NOW - cooldown (30 min)"
                elif blk:
                    status = f"cross NOW - {blk}"
                else:
                    status = f"cross NOW - {reason or 'not tradeable'}"
                include = True
            elif blk:
                status = blk
                include = score >= config.WATCH_MIN_SCORE
            else:
                status = "waiting for cross"
                include = score >= config.WATCH_MIN_SCORE
            if not include:
                continue
            self.on_watch({
                "key": f"{symbol}:{side}",
                "sym": symbol,
                "side": side,
                "mkt": getattr(ctx, "cls", "crypto"),
                "score": score,
                "grade": strategy.grade_of(score, getattr(ctx, "cls", "crypto")),
                "status": status,
                "ready": (not blk) and
                         strategy.GRADE_ORDER[strategy.grade_of(
                             score, getattr(ctx, "cls", "crypto"))] >=
                         strategy.GRADE_ORDER[config.MIN_GRADE],
                "ts": time.time(),
            })

    # -------------------------------------------------- one coin
    def scan_coin(self, symbol, ctx):
        import strategy
        cls = getattr(ctx, "cls", "crypto")

        try:
            if cls == "crypto":
                daily = self.hub.daily_candles(symbol)
                trig_candles = self.hub.trigger_candles(symbol)
            else:
                # forex / metals / stocks -> yahoo, same chart shapes
                from yf_data import SOURCE
                daily = SOURCE.candles_1d(symbol)
                trig_candles = SOURCE.trigger_2m(
                    symbol, config.TRIGGER_TF_CANDLES)
        except Exception as e:
            self.stats["errors"] += 1
            if self.stats["errors"] <= 5:
                self._log(f"  [data] {symbol}: {e}")
            return None, f"data error: {e}"

        if len(trig_candles) < config.TRIGGER_SLOW + 5:
            return None, "not enough 2m history for this coin"

        coin_reg = strategy.coin_daily(daily)
        trig = strategy.detect_trigger(trig_candles)
        sig, reason = strategy.evaluate(ctx, symbol, coin_reg, trig, trig_candles)
        try:
            self._emit_watch(symbol, ctx, coin_reg, trig, sig, reason)
        except Exception:
            pass                            # watch must never break a scan
        if sig is None:
            if reason and not reason.startswith("data error"):
                with self._stats_lock:
                    self.stats["blocked"][reason] = \
                        self.stats["blocked"].get(reason, 0) + 1
            return None, reason
        if in_cooldown(self.state, symbol, sig.side):
            return None, "cooldown"

        sig.ts = time.time()
        return sig, reason

    # -------------------------------------------------- full scan
    def run_scan(self):
        """
        One full pass over ALL coins. Uses SCAN_WORKERS parallel threads
        so the whole market is covered every ~15 seconds instead of
        waiting minutes - while staying inside exchange rate limits.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        ctx = self.refresh_context()
        try:
            coins = self.hub.universe()
        except Exception as e:
            self._log(f"[data] coin list failed: {e}")
            return

        tasks = [(sym, ctx) for sym in coins]
        extra = self._instrument_tasks()          # forex / metals / stocks
        tasks += extra
        total = len(tasks)
        self.stats["scanned"] = total
        self._log(f"[{time.strftime('%H:%M:%S')}] scanning {len(coins)} "
                  f"crypto + {len(extra)} forex/gold/stocks "
                  f"on {self.hub.provider_name}+yahoo with "
                  f"{config.SCAN_WORKERS} workers "
                  f"(trigger {config.TRIGGER_TF} "
                  f"EMA{config.TRIGGER_FAST}/{config.TRIGGER_SLOW}, "
                  f"leverage {config.MAX_LEVERAGE}x) ...")
        self._progress(0, total)

        from notifier import print_signal, signal_message, send_text, log_signal
        found = 0
        done = 0

        def handle(sig):
            """Runs in this thread - telegram + file log + display."""
            nonlocal found
            found += 1
            with self._stats_lock:
                self.stats["signals"] += 1
            set_cooldown(self.state, sig.symbol, sig.side)
            ok = send_text(signal_message(sig))     # always
            log_signal(sig)                         # always
            if self.on_signal:
                self.on_signal(sig, ok)
            else:
                print_signal(sig)
                self._log(f"  -> telegram "
                          f"{'sent' if ok else 'NOT configured/failed'}")

        workers = max(1, int(config.SCAN_WORKERS))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.scan_coin, sym, c): sym
                       for sym, c in tasks}
            for fut in as_completed(futures):
                sym = futures[fut]
                done += 1
                try:
                    sig, why = fut.result()
                except Exception:
                    with self._stats_lock:
                        self.stats["errors"] += 1
                    self._log(f"  [error] {sym}: {traceback.format_exc()}")
                    sig = None
                if sig:
                    handle(sig)
                if done % 5 == 0 or done == total:
                    self._progress(done, total)
                    if done % 25 == 0 and done != total:
                        self._log(f"   ... {done}/{total}")
                if not config.UNIT_TEST:      # normal pacing
                    time.sleep(config.REQUEST_PAUSE_SEC)

        self.ctx_mod.save_state(self.state)
        self.last_scan = time.time()
        self._progress(0, 0)                  # hide / reset the bar
        self._log(f"[{time.strftime('%H:%M:%S')}] scan done: {total} symbols, "
                  f"{found} new signal(s), {self.stats['errors']} data errors, "
                  f"provider={self.hub.provider_name}")
        if found == 0:
            blocked = self.stats.get("blocked") or {}
            top = sorted(blocked.items(), key=lambda kv: -kv[1])[:3]
            if top:
                self._log("  mostly blocked by: "
                          + ", ".join(f"{k} x{v}" for k, v in top))


# ------------------------------------------------------------------
def test_telegram():
    from notifier import send_text
    msg = ("<b>Signal system test</b>\n"
           "Assalam-o-Alaikum! Your future trading scanner is connected. "
           "Long/short alerts will arrive here.")
    ok = send_text(msg)
    print("Telegram test: SENT" if ok else
          "Telegram test: FAILED - check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
          "in config.py")
    return 0 if ok else 1


def main():
    args = parse_args()
    apply_args(args)

    if args.test_telegram:
        sys.exit(test_telegram())

    scanner = Scanner()

    if args.once:
        scanner.refresh_context(force=True)
        scanner.run_scan()
        return

    print("=" * 62)
    print("  SIGNAL SCANNER STARTED  (24/7 mode - checks every second)")
    print(f"  coins: {'ALL' if not config.MAX_COINS else config.MAX_COINS} "
          f"(min 24h vol ${config.MIN_QUOTE_VOLUME_24H / 1e6:.0f}M) "
          f"with {config.SCAN_WORKERS} parallel workers")
    print(f"  leverage: {config.MAX_LEVERAGE}x   "
          f"risk: {config.RISK_PER_TRADE_PCT}% per trade   "
          f"balance: {config.ACCOUNT_BALANCE:,.0f} USDT")
    print(f"  min grade: {config.MIN_GRADE}   "
          f"new scan every {config.SCAN_INTERVAL_SEC}s")
    print("=" * 62)

    scanner.refresh_context(force=True)
    while True:
        try:
            now = time.time()
            if now - scanner.last_context >= config.CONTEXT_REFRESH_SEC:
                scanner.refresh_context(force=True)
            if now - scanner.last_scan >= config.SCAN_INTERVAL_SEC:
                scanner.run_scan()
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nstopped. your state was saved.")
            from context import save_state
            save_state(scanner.state)
            break
        except Exception:
            traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
