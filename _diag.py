"""
FULL MARKET OPPORTUNITY REPORT - checks EVERY coin (no limit) and
shows which ones have a real opportunity right now / are about to.

  python _diag.py          full report

It never sends telegram and never writes signals.log - read only.
"""
import time
from collections import Counter

import config

from scanner import Scanner
import strategy

B = "\033[1m"
R = "\033[0m"


def market_score(ctx, side):
    """Same math as strategy.evaluate - the MARKET part of the score."""
    sc = 1                                   # the trigger itself
    if side == "LONG":
        sc += 1 if ctx.btc.above_ema120 else -1
        sc += 1 if ctx.btc.cross == "GOLDEN" else (-1 if ctx.btc.cross == "DEATH" else 0)
    else:
        sc += 1 if not ctx.btc.above_ema120 else -1
        sc += 1 if ctx.btc.cross == "DEATH" else (-1 if ctx.btc.cross == "GOLDEN" else 0)
    sc += strategy._flow_supports(ctx.flow.money_flow, side)
    sc += strategy._sentiment_supports(ctx.sentiment.value, side)
    sc += -1 if ctx.news.status == "WARNING" else 1
    return sc


def grade_of(score):
    import strategy
    return strategy.grade_of(score, "crypto")


def main():
    s = Scanner()
    ctx = s.refresh_context(force=True)
    coins = s.hub.universe()
    print(f"\nchecking ALL {len(coins)} coins on {s.hub.provider_name} "
          f"(no limit) ...\n")

    rows = []
    err = 0
    for i, sym in enumerate(coins, 1):
        try:
            daily = s.hub.daily_candles(sym)
            trig_c = s.hub.trigger_candles(sym)
        except Exception:
            err += 1
            continue
        if len(trig_c) < config.TRIGGER_SLOW + 5:
            continue
        reg = strategy.coin_daily(daily)
        trig = strategy.detect_trigger(trig_c)
        if not reg.ok:
            continue

        # how many 2m crosses in the whole fetched history (16h)?
        import indicators
        fast = indicators.ema(trig_c.close, config.TRIGGER_FAST)
        slow = indicators.ema(trig_c.close, config.TRIGGER_SLOW)
        import numpy as np
        n_cross = int(np.sum((fast[1:] >= slow[1:]) != (fast[:-1] >= slow[:-1])))

        row = {"sym": sym, "fired": trig.fired, "age": trig.age,
               "above": reg.above_ema120, "rsi": reg.rsi, "bb": reg.bb_state,
               "n_cross": n_cross}
        for side in ("LONG", "SHORT"):
            regime, dip = strategy._daily_supports(reg, side)
            sc = market_score(ctx, side) + regime + dip
            row[side] = sc
            row[side + "_grade"] = grade_of(sc)
        # real verdict for the side the trigger fired on
        if trig.fired:
            sig, why = strategy.evaluate(ctx, sym, reg, trig, trig_c)
            row["verdict"] = why
            row["blocked_by"] = None if sig else why
        rows.append(row)
        if i % 20 == 0:
            print(f"   ... {i}/{len(coins)}")

    print(f"   done: {len(rows)} coins analysed, {err} data errors\n")

    # ---------------------------------------------------------------- header
    f, sen, b = ctx.flow, ctx.sentiment, ctx.btc
    print("=" * 74)
    print("  MARKET STATE (applies to every coin)")
    print("=" * 74)
    print(f"  news          : {ctx.news.status}  ({ctx.news.note[:44]})")
    print(f"  dominance     : {f.dominance:.1f}%  {f.dominance_trend}  "
          f"({f.method})")
    print(f"  total mcap    : ${f.total_mcap / 1e12:.2f}T  24h "
          f"{f.mcap_delta_pct:+.1f}%")
    print(f"  MONEY FLOW    : {f.money_flow}")
    print(f"  fear & greed  : {sen.value} {sen.label}")
    print(f"  btc regime    : {'above' if b.above_ema120 else 'below'} "
          f"EMA120, {b.cross} cross, RSI {b.rsi:.0f}")
    print(f"  min grade     : {config.MIN_GRADE}  ->  crypto B needs score 4, "
          f"A 6, A+ 8 | forex/gold/stocks B 4, A 5, A+ 6 | "
          f"C = anything tradeable")
    print()

    # ---------------------------------------------------- A) fresh triggers
    fired = [r for r in rows if r["fired"]]
    print("=" * 74)
    print(f"  A) COINS WITH A FRESH 2-MINUTE TRIGGER RIGHT NOW: {len(fired)}")
    print("=" * 74)
    if fired:
        fired.sort(key=lambda r: -max(r["LONG"], r["SHORT"]))
        print(f"  {'COIN':<12}{'SIDE':<7}{'AGE':<5}{'L score':<9}"
              f"{'S score':<9}{'VERDICT'}")
        for r in fired:
            verdict = r.get("verdict", "?")
            print(f"  {r['sym']:<12}{r['fired']:<7}{r['age']:<5}"
                  f"{r['LONG']}({r['LONG_grade']}){'':<4}"
                  f"{r['SHORT']}({r['SHORT_grade']})  {verdict[:44]}")
    else:
        print("  none at this second (a cross must be < 5 candles = 10 min old)")
    print()

    # ---------------------------------------------------- B) opportunities
    print("=" * 74)
    print("  B) TOP OPPORTUNITIES - best aligned coins, they fire the")
    print("     moment a 2-min cross appears (score = trigger included)")
    print("=" * 74)
    for side, emoji in (("LONG", "LONG"), ("SHORT", "SHORT")):
        rank = sorted(rows, key=lambda r: -r[side])[:10]
        print(f"\n  {emoji} candidates (best first):")
        print(f"  {'COIN':<12}{'score':<7}{'grade':<7}"
              f"{'coin daily':<28}{'why not firing yet'}")
        for r in rank:
            daily_txt = (f"{'above' if r['above'] else 'below'} EMA120, "
                         f"RSI {r['rsi']:.0f}, {r['bb']}")
            why = ""
            if r[side] < 6:
                why = "market/daily alignment too weak (score < 6)"
            elif r["fired"] != side:
                why = "waiting for a 2-min cross"
            else:
                why = "FIRED - see section A"
            if side == "LONG" and ctx.flow.money_flow in ("LEAVING", "PANIC"):
                why = f"money flow {ctx.flow.money_flow} blocks longs"
            if side == "SHORT" and ctx.flow.money_flow == "ROTATING_IN":
                why = "money rotating in blocks shorts"
            print(f"  {r['sym']:<12}{r[side]:<7}{r[side + '_grade']:<7}"
                  f"{daily_txt:<28}{why}")
    print()

    # ---------------------------------------------------- C) block summary
    print("=" * 74)
    print("  C) WHY THE MARKET IS QUIET (every coin, counted)")
    print("=" * 74)
    c = Counter()
    max_short = max((r["SHORT"] for r in rows), default=0)
    max_long = max((r["LONG"] for r in rows), default=0)
    for r in rows:
        if r["fired"]:
            c[r.get("blocked_by", "fired")] += 1
        else:
            c["no fresh 2m cross (normal - crosses are rare)"] += 1
    for k, v in c.most_common(8):
        print(f"  {v:>4} x  {k[:60]}")
    print()
    print(f"  best possible LONG score today  : {max_long} "
          f"({grade_of(max_long)})  of 10")
    print(f"  best possible SHORT score today : {max_short} "
          f"({grade_of(max_short)})  of 10")
    print(f"  crosses per coin in last ~16h   : "
          f"avg {sum(r['n_cross'] for r in rows) / max(1, len(rows)):.1f}, "
          f"market total {sum(r['n_cross'] for r in rows)}")
    print()
    print("=" * 74)
    print("  HONEST VERDICT")
    print("=" * 74)
    if ctx.flow.money_flow in ("LEAVING", "PANIC"):
        print("  1. Money is LEAVING/PANIC -> the checklist says NO BUYS.")
    if max_long < 6 and max_short < 6:
        print("  2. No coin can reach grade B in this market state -")
        print("     the system is staying flat on purpose (capital safety).")
    else:
        print("  2. Some coins CAN reach grade B - see section B.")
    print("  3. To see lower-graded setups too, set min grade C in the app")
    print("     (Settings -> minimum grade). Signals become more, quality less.")
    print("=" * 74)


if __name__ == "__main__":
    main()
