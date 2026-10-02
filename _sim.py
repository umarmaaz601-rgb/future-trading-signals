"""
One-off diagnostic: if a FRESH cross fired right now on each ready
A-grade candidate, would evaluate() produce a signal (prob gate and all)?

    python _sim.py

Prints: real trigger state + what a forced age-1 cross would yield.
"""
import config
import strategy
from scanner import Scanner


def main():
    import config as _config
    _config.STRONG_ONLY = True          # same rules as the running app
    s = Scanner()
    s.refresh_context(force=True)
    targets = [
        ("AAPL", "stock", "LONG"), ("NVDA", "stock", "LONG"),
        ("TSLA", "stock", "LONG"), ("GOOGL", "stock", "LONG"),
        ("COIN", "stock", "LONG"), ("SPY", "stock", "LONG"),
        ("QQQ", "stock", "LONG"), ("MSFT", "stock", "LONG"),
        ("META", "stock", "LONG"),
        ("XAGUSD", "metal", "SHORT"), ("XAUUSD", "metal", "SHORT"),
        ("GBPUSD", "forex", "SHORT"), ("EURUSD", "forex", "SHORT"),
        ("USDCHF", "forex", "LONG"),
    ]
    import dataclasses
    from yf_data import bench_inverted
    ok = blocked = 0
    for sym, cls, side in targets:
        base = s.class_ctx.get(cls)
        if base is None:
            print(f"{sym:8} - no {cls} context")
            continue
        ctx = dataclasses.replace(base,          # per-instrument inversion
                                  bench_inverted=bench_inverted(sym, cls))
        try:
            from yf_data import SOURCE
            daily = SOURCE.candles_1d(sym)
            trig_candles = SOURCE.trigger_2m(sym, config.TRIGGER_TF_CANDLES)
        except Exception as e:
            print(f"{sym:8} - data error: {e}")
            continue
        if len(trig_candles) < config.TRIGGER_SLOW + 5:
            print(f"{sym:8} - not enough 2m history")
            continue
        coin_reg = strategy.coin_daily(daily)
        real = strategy.detect_trigger(trig_candles)
        forced = strategy.Trigger(fired=side, age=1)
        sig, reason = strategy.evaluate(ctx, sym, coin_reg, forced,
                                        trig_candles)
        rstate = (f"fired={real.fired} age={real.age}" if real.fired
                  else "no recent cross")
        rsi = coin_reg.rsi if coin_reg.ok else float("nan")
        if sig:
            ok += 1
            p = f"{sig.prob:.0%}" if sig.prob is not None else "-"
            print(f"{sym:8} {side:5} dailyRSI={rsi:4.0f} [{rstate:18}] "
                  f"-> SIGNAL {sig.grade} score={sig.score} p={p}")
        else:
            blocked += 1
            print(f"{sym:8} {side:5} dailyRSI={rsi:4.0f} [{rstate:18}] "
                  f"-> blocked: {reason}")
    print(f"\n{ok} of {ok + blocked} candidates would signal "
          f"on a fresh cross right now")


if __name__ == "__main__":
    main()
