"""One-off: why does evaluate() score XAGUSD SHORT=1 while the watchlist
said 5?  Prints every score component for both paths + reruns GBP (the
prob=None crash case) after the fix."""
import config
import strategy
from scanner import Scanner


def main():
    s = Scanner()
    s.refresh_context(force=True)
    from yf_data import SOURCE

    ctx = s.class_ctx["metal"]
    daily = SOURCE.candles_1d("XAGUSD")
    c2m = SOURCE.trigger_2m("XAGUSD", config.TRIGGER_TF_CANDLES)
    reg = strategy.coin_daily(daily)

    print("--- metal ctx ---")
    print("  bench:", getattr(ctx, "bench_name", None),
          "| session_open:", getattr(ctx, "session_open", None))
    print("  btc/bench regime: ok", ctx.btc.ok, "cross", ctx.btc.cross,
          "above", ctx.btc.above_ema120, "rsi", round(ctx.btc.rsi, 1))
    print("  bench_above:", strategy._bench_above(ctx),
          "| flow:", ctx.flow.money_flow,
          "| senti:", ctx.sentiment.value,
          "| news:", ctx.news.status)
    print("--- XAGUSD daily ---")
    print("  ok", reg.ok, "| above", reg.above_ema120,
          "| rsi", round(reg.rsi, 1), "| bb", reg.bb_state)
    print("  daily regime/dip (SHORT):",
          strategy._daily_supports(reg, "SHORT"))
    print("--- scores for SHORT ---")
    print("  score_setup     :", strategy.score_setup(ctx, reg, "SHORT"))
    print("  opportunity     :", strategy.opportunity(ctx, reg, "SHORT"))
    forced = strategy.Trigger(fired="SHORT", age=1)
    sig, reason = strategy.evaluate(ctx, "XAGUSD", reg, forced, c2m)
    print("  evaluate        :",
          (f"score {sig.score} grade {sig.grade} p={sig.prob}") if sig
          else reason)

    print("--- GBPUSD (prob=None case, post-fix) ---")
    ctxf = s.class_ctx["forex"]
    d2 = SOURCE.candles_1d("GBPUSD")
    c2 = SOURCE.trigger_2m("GBPUSD", config.TRIGGER_TF_CANDLES)
    reg2 = strategy.coin_daily(d2)
    forced2 = strategy.Trigger(fired="SHORT", age=1)
    sig2, reason2 = strategy.evaluate(ctxf, "GBPUSD", reg2, forced2, c2)
    if sig2:
        print(f"  SIGNAL {sig2.grade} score {sig2.score} "
              f"p={sig2.prob} (None-safe)")
    else:
        print("  blocked:", reason2)


if __name__ == "__main__":
    main()
