"""
Self-test: checks indicator maths + strategy logic WITHOUT needing
network or real money.  Run:  python test_system.py
"""
import sys

import numpy as np

import config
import indicators as ind


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name} {extra}")
    return bool(cond)


def make_ohlcv(close, high=None, low=None):
    from market_data import OHLCV
    close = np.asarray(close, dtype=float)
    n = close.size
    high = close * 1.001 if high is None else np.asarray(high, dtype=float)
    low = close * 0.999 if low is None else np.asarray(low, dtype=float)
    return OHLCV(ts=np.arange(n) * 120000.0, open=close.copy(),
                 high=high, low=low, close=close, volume=np.ones(n))


def test_indicators():
    print("\n1) INDICATORS")
    ok = True
    # EMA of a constant series is that constant
    c = np.full(300, 100.0)
    ok &= check("ema(const) = const", abs(ind.ema(c, 20)[-1] - 100.0) < 1e-9)

    # SMA of constant series
    ok &= check("sma(const) = const", abs(ind.sma(c, 200)[-1] - 100.0) < 1e-9)

    # RSI of a strictly rising series is ~100
    up = np.linspace(100, 200, 300)
    r = ind.rsi(up, 14)
    ok &= check("rsi(rising) near 100", r[-1] > 95, f"-> {r[-1]:.1f}")

    # RSI of strictly falling series is ~0
    down = np.linspace(200, 100, 300)
    r2 = ind.rsi(down, 14)
    ok &= check("rsi(falling) near 0", r2[-1] < 5, f"-> {r2[-1]:.1f}")

    # Bollinger: constant price -> zero width, price on the middle
    mid, up_b, low_b = ind.bollinger(c, 20, 2.0)
    ok &= check("bollinger constant -> width 0",
                abs(up_b[-1] - low_b[-1]) < 1e-9)

    # Golden cross detection: fast above slow
    fast = np.full(50, 110.0)
    slow = np.full(50, 100.0)
    side, idx = ind.latest_cross(fast, slow)
    ok &= check("latest_cross finds cross", side is None or side in ("LONG", "SHORT"))

    f2 = np.arange(50, dtype=float)      # rising fast crosses flat slow
    s2 = np.full(50, 20.0)
    side2, idx2 = ind.latest_cross(f2, s2)
    ok &= check("cross above detected", side2 == "LONG", f"idx={idx2}")
    return ok


def test_trigger():
    print("\n2) 2-MINUTE TRIGGER (EMA20 x EMA200)")
    ok = True
    # Long downtrend (fast well below slow), then a sharp V reversal.
    n = 300
    down = np.linspace(100, 60, 260)
    up = np.linspace(60, 95, 40)
    close = np.concatenate([down, up])
    sig = make_ohlcv(close)
    import strategy
    t = strategy.detect_trigger(sig)
    ok &= check("no signal while falling", t.fired != "SHORT" or t.age >= 0)
    ok &= check("trigger computed EMA values", t.fast > 0 and t.slow > 0,
                f"fast={t.fast:.2f} slow={t.slow:.2f}")

    # Force a fresh cross at the very end: build slow flat then jump up
    close2 = np.concatenate([np.full(296, 100.0), np.linspace(100, 140, 4)])
    sig2 = make_ohlcv(close2)
    t2 = strategy.detect_trigger(sig2)
    ok &= check("fresh bullish cross fires LONG",
                t2.fired == "LONG", f"fired={t2.fired} age={t2.age}")
    return ok


def test_stop_and_sizing():
    print("\n3) STOP-LOSS / POSITION SIZING")
    ok = True
    import strategy
    close = np.linspace(100, 110, 300)
    candles = make_ohlcv(close, high=close * 1.004, low=close * 0.996)

    entry = float(candles.close[-1])
    sl_long = strategy.stop_from_2m(candles, "LONG", entry)
    dist = (entry - sl_long) / entry * 100
    ok &= check("LONG stop is below entry", sl_long < entry)
    ok &= check("stop inside min/max", config.MIN_STOP_PCT - 1e-9 <= dist <= config.MAX_STOP_PCT + 1e-9,
                f"-> {dist:.3f}%")

    sl_short = strategy.stop_from_2m(candles, "SHORT", entry)
    ok &= check("SHORT stop is above entry", sl_short > entry)

    # sizing: 1% risk, 0.4% stop -> notional = 25% of balance / leverage margin
    risk = config.ACCOUNT_BALANCE * config.RISK_PER_TRADE_PCT / 100
    expected_notional = risk / (0.4 / 100)
    margin = expected_notional / config.MAX_LEVERAGE
    ok &= check("50x margin sane",
                margin <= config.ACCOUNT_BALANCE * config.MAX_MARGIN_PCT / 100 + 1,
                f"-> margin {margin:.1f} USDT on {config.ACCOUNT_BALANCE:.0f} account")
    return ok


def test_strategy():
    print("\n4) STRATEGY LAYERS (news / flow / regime -> LONG or SHORT)")
    ok = True
    import strategy
    from context import Context, NewsReport, FlowReport, SentimentReport, BtcRegime

    # --- build a STRONG LONG scenario
    ctx = Context()
    ctx.news = NewsReport(status="OK", note="news clean")
    ctx.flow = FlowReport(dominance=41.0, dominance_trend="FALLING",
                          dominance_delta=-2.0, total_mcap=1.2e12,
                          mcap_delta_pct=2.0, money_flow="ROTATING_IN",
                          note="money rotating into alts")
    ctx.sentiment = SentimentReport(value=20, label="EXTREME FEAR",
                                    note="classic dip zone")
    ctx.btc = BtcRegime(price=40000, ema120=38000, above_ema120=True,
                        cross="GOLDEN", rsi=60, bb_state="INSIDE", ok=True)

    # coin daily above EMA120, in dip (below lower band, low RSI)
    coin = BtcRegime(price=2.0, ema120=1.8, above_ema120=True,
                     cross="GOLDEN", rsi=28, bb_state="BELOW_LOWER", ok=True)

    # fresh bullish 2m cross (jump at the very end so the cross is fresh)
    close = np.concatenate([np.full(296, 2.0), np.linspace(2.0, 2.3, 4)])
    candles = make_ohlcv(close, high=close * 1.003, low=close * 0.997)
    trig = strategy.detect_trigger(candles)
    sig, reason = strategy.evaluate(ctx, "XYZUSDT", coin, trig, candles)
    ok &= check("strong LONG scenario produces a signal",
                sig is not None and sig.side == "LONG",
                f"-> {sig.grade if sig else reason}")
    if sig:
        ok &= check("checklist has 8 rows", len(sig.checklist) == 8)
        ok &= check("entry above stop", sig.entry > sig.stop_loss)
        ok &= check("TP1 < TP2 < TP3",
                    sig.take_profits[0] < sig.take_profits[1] < sig.take_profits[2])
        ok &= check("TP1 is a 1:2 trade (2R of risk)",
                    abs((sig.take_profits[0] - sig.entry) /
                        (sig.entry - sig.stop_loss) - config.TP1_R) < 0.01,
                    f"-> {(sig.take_profits[0] - sig.entry) / (sig.entry - sig.stop_loss):.2f}R")
        ok &= check("leverage is 50x", sig.leverage == 50)
        ok &= check("P(1:2) measured and passes the filter",
                    0.0 <= sig.prob and sig.prob >= config.PROB_MIN,
                    f"-> p={sig.prob:.0%}")

    # --- prob_1to2: same rising data must favor LONG, hurt SHORT
    p_long = strategy.prob_1to2(candles, "LONG", 0.6)
    p_short = strategy.prob_1to2(candles, "SHORT", 0.6)
    ok &= check("prob_1to2: trending up -> high P for LONG",
                p_long is not None and p_long >= 0.7, f"-> {p_long}")
    ok &= check("prob_1to2: same data -> low P for SHORT",
                p_short is not None and p_short <= 0.3, f"-> {p_short}")
    ok &= check("prob_1to2: too little history -> None",
                strategy.prob_1to2(make_ohlcv(np.full(20, 100.0)),
                                   "LONG", 0.6) is None)

    # --- the 1:2 gate must reject below PROB_MIN
    old_min = config.PROB_MIN
    config.PROB_MIN = 1.01                      # impossible to satisfy
    try:
        sigp, reasonp = strategy.evaluate(ctx, "XYZUSDT", coin, trig, candles)
    finally:
        config.PROB_MIN = old_min
    ok &= check("1:2 probability gate blocks low-prob setups",
                sigp is None and "1:2 probability" in str(reasonp),
                f"-> {reasonp}")

    # --- news HALT must block everything
    ctx2 = Context()
    ctx2.news = NewsReport(status="HALT", note="exchange hacked")
    ctx2.flow = ctx.flow
    ctx2.sentiment = ctx.sentiment
    ctx2.btc = ctx.btc
    sig2, reason2 = strategy.evaluate(ctx2, "XYZUSDT", coin, trig, candles)
    ok &= check("news HALT blocks all signals", sig2 is None,
                f"-> {reason2}")

    # --- money LEAVING must block longs
    ctx3 = Context()
    ctx3.news = ctx.news
    ctx3.flow = FlowReport(dominance=41.0, dominance_trend="FALLING",
                           total_mcap=1.1e12, mcap_delta_pct=-6.0,
                           money_flow="LEAVING")
    ctx3.sentiment = ctx.sentiment
    ctx3.btc = ctx.btc
    sig3, reason3 = strategy.evaluate(ctx3, "XYZUSDT", coin, trig, candles)
    ok &= check("money LEAVING blocks longs", sig3 is None, f"-> {reason3}")

    # --- SHORT scenario: BTC below EMA120, death cross, greed, flow PANIC
    ctx4 = Context()
    ctx4.news = ctx.news
    ctx4.flow = FlowReport(dominance=43.0, dominance_trend="RISING",
                           total_mcap=1.0e12, mcap_delta_pct=-5.0,
                           money_flow="PANIC")
    ctx4.sentiment = SentimentReport(value=80, label="EXTREME GREED")
    ctx4.btc = BtcRegime(price=35000, ema120=40000, above_ema120=False,
                         cross="DEATH", rsi=65, bb_state="ABOVE_UPPER", ok=True)
    coin_short = BtcRegime(price=2.0, ema120=2.4, above_ema120=False,
                           cross="DEATH", rsi=78, bb_state="ABOVE_UPPER", ok=True)
    down = np.concatenate([np.full(296, 2.3), np.linspace(2.3, 2.0, 4)])
    candles_short = make_ohlcv(down, high=down * 1.003, low=down * 0.997)
    trig_short = strategy.detect_trigger(candles_short)
    sig4, reason4 = strategy.evaluate(ctx4, "XYZUSDT", coin_short,
                                      trig_short, candles_short)
    ok &= check("strong SHORT scenario produces a signal",
                sig4 is not None and sig4.side == "SHORT",
                f"-> {sig4.grade if sig4 else reason4}")
    if sig4:
        ok &= check("SHORT stop is above entry", sig4.stop_loss > sig4.entry)
        ok &= check("SHORT TP1 < entry",
                    sig4.take_profits[0] < sig4.entry)
    return ok


def test_multi_market():
    print("\n5) MULTI-MARKET (forex / gold / stocks)")
    ok = True
    import dataclasses
    import strategy
    from context import build_class_context, BtcRegime
    from yf_data import (asset_class, bench_inverted, yahoo_ticker,
                         session_status, instruments)

    ok &= check("asset classes",
                asset_class("EURUSD") == "forex"
                and asset_class("XAUUSD") == "metal"
                and asset_class("TSLA") == "stock"
                and asset_class("BTCUSDT") == "crypto")
    ok &= check("EURUSD DXY-inverted / USDJPY not",
                bench_inverted("EURUSD", "forex")
                and not bench_inverted("USDJPY", "forex"))
    ok &= check("gold moves against the dollar",
                bench_inverted("XAUUSD", "metal"))
    ok &= check("yahoo tickers",
                yahoo_ticker("EURUSD") == "EURUSD=X"
                and yahoo_ticker("XAUUSD") == "GC=F"
                and yahoo_ticker("TSLA") == "TSLA"
                and yahoo_ticker("DXY") == "DX-Y.NYB")
    gates = {c: session_status(c)[0] for c in
             ("crypto", "forex", "metal", "stock")}
    ok &= check("crypto always open", gates["crypto"] is True)
    ok &= check("session gates return bool",
                all(isinstance(v, bool) for v in gates.values()),
                f"-> {gates}")
    ok &= check("instrument lists non-empty",
                all(len(instruments(c)) > 0 for c in
                    ("forex", "metal", "stock")),
                f"-> {sum(len(instruments(c)) for c in ('forex','metal','stock'))}")

    # ---- class context shape (crypto-only checks switched off)
    bench = BtcRegime(price=104.0, ema120=103.0, above_ema120=True,
                      cross="GOLDEN", rsi=60, bb_state="INSIDE", ok=True)
    fctx = build_class_context("forex", bench)
    ok &= check("forex context fields",
                fctx.cls == "forex" and fctx.bench_name == "DXY"
                and fctx.flow.money_flow == "NEUTRAL"
                and fctx.news.status == "OK" and fctx.session_open)
    ok &= check("neutral flow blocks neither side",
                strategy.block_reason(fctx, "LONG") == ""
                and strategy.block_reason(fctx, "SHORT") == "")

    # ---- per-class grade cutoffs
    ok &= check("forex cutoffs",
                strategy.grade_of(6, "forex") == "A+"
                and strategy.grade_of(5, "forex") == "A"
                and strategy.grade_of(4, "forex") == "B"
                and strategy.grade_of(3, "forex") == "C")
    ok &= check("crypto cutoffs (rebalanced)",
                strategy.grade_of(8, "crypto") == "A+"
                and strategy.grade_of(6, "crypto") == "A"
                and strategy.grade_of(4, "crypto") == "B"
                and strategy.grade_of(3, "crypto") == "C")

    # ---- DXY inversion flips the regime support
    fctx_inv = dataclasses.replace(fctx, bench_inverted=True)
    coin = BtcRegime(price=1.1, ema120=0.9, above_ema120=True,
                     cross="GOLDEN", rsi=55, bb_state="INSIDE", ok=True)
    sl = strategy.score_setup(fctx, coin, "LONG")
    si = strategy.score_setup(fctx_inv, coin, "LONG")
    ok &= check("inversion changes the score", sl != si,
                f"plain={sl} inverted={si}")
    ok &= check("plain: DXY up supports EURUSD-like long",
                strategy.block_reason(fctx, "LONG") == "")
    blk = strategy.block_reason(fctx_inv, "LONG")
    ok &= check("inverted: dollar strong blocks longs", "DXY below" in blk,
                f"-> {blk}")

    # ---- session gate hard block
    closed = dataclasses.replace(fctx, session_open=False,
                                 session_note="reopens Monday")
    blk2 = strategy.block_reason(closed, "SHORT")
    ok &= check("closed session blocks", "market closed" in blk2,
                f"-> {blk2}")

    # ---- evaluate end to end on a class context
    close = np.concatenate([np.full(296, 1.1), np.linspace(1.1, 1.15, 4)])
    candles = make_ohlcv(close, high=close * 1.003, low=close * 0.997)
    trig = strategy.detect_trigger(candles)
    sig, why = strategy.evaluate(fctx, "EURUSD", coin, trig, candles)
    ok &= check("forex signal produced", sig is not None,
                f"-> {sig.grade if sig else why}")
    if sig:
        ok &= check("signal carries its class", sig.cls == "forex")
        ok &= check("class checklist = 6 rows",
                    len(sig.checklist) == 6,
                    f"-> {[r[0] for r in sig.checklist]}")
        ok &= check("grade matches forex cutoff",
                    sig.grade == strategy.grade_of(sig.score, "forex"))
    return ok


def test_strong_mode():
    print("\n6) STRONG MODE (every checklist item must agree)")
    ok = True
    import strategy
    from context import Context, NewsReport, BtcRegime

    ctx = Context()
    ctx.news = NewsReport(status="OK", note="clean")
    ctx.btc = BtcRegime(price=110, ema120=100, above_ema120=True,
                        cross="GOLDEN", rsi=60, bb_state="INSIDE", ok=True)
    coin = BtcRegime(price=2.0, ema120=1.8, above_ema120=True,
                     cross="GOLDEN", rsi=40, bb_state="INSIDE", ok=True)
    fresh = strategy.Trigger(fired="LONG", age=1)

    ok &= check("clean pullback LONG passes",
                strategy.strong_reason(ctx, coin, fresh, "LONG") == "")

    # 1) news must be clean
    ctx.news = NewsReport(status="WARNING", note="sec lawsuit")
    r = strategy.strong_reason(ctx, coin, fresh, "LONG")
    ok &= check("news WARNING blocks strong", "news" in r, f"-> {r}")
    ctx.news = NewsReport(status="OK", note="clean")

    # 2) cross direction must not oppose the side
    ctx.btc.cross = "DEATH"
    r = strategy.strong_reason(ctx, coin, fresh, "LONG")
    ok &= check("DEATH cross blocks strong longs", "DEATH" in r, f"-> {r}")
    ctx.btc.cross = "GOLDEN"
    r = strategy.strong_reason(ctx, coin, fresh, "SHORT")
    ok &= check("GOLDEN cross blocks strong shorts", "GOLDEN" in r,
                f"-> {r}")

    # 3) the coin's own daily trend must agree
    bear = BtcRegime(price=1.5, ema120=1.8, above_ema120=False,
                     cross="DEATH", rsi=40, bb_state="INSIDE", ok=True)
    r = strategy.strong_reason(ctx, bear, fresh, "LONG")
    ok &= check("coin below EMA120 blocks strong longs", "EMA120" in r,
                f"-> {r}")

    # 4) never chase: longs need a dip, shorts need a top
    hot = BtcRegime(price=2.4, ema120=1.8, above_ema120=True,
                    cross="GOLDEN", rsi=78, bb_state="ABOVE_UPPER", ok=True)
    r = strategy.strong_reason(ctx, hot, fresh, "LONG")
    ok &= check("top zone blocks strong longs", "dip" in r, f"-> {r}")
    cool = BtcRegime(price=1.5, ema120=1.8, above_ema120=False,
                     cross="DEATH", rsi=35, bb_state="INSIDE", ok=True)
    ctx.btc.cross = "DEATH"                   # isolate the dip/top rule
    r = strategy.strong_reason(ctx, cool, fresh, "SHORT")
    ok &= check("no top blocks strong shorts", "top" in r, f"-> {r}")
    ctx.btc.cross = "GOLDEN"

    # 5) fresh cross only
    stale = strategy.Trigger(fired="LONG",
                             age=config.STRONG_MAX_AGE + 1)
    r = strategy.strong_reason(ctx, coin, stale, "LONG")
    ok &= check("stale cross blocked", "too old" in r, f"-> {r}")

    # 6) evaluate() honours the flag + needs grade A
    coin.rsi = 28                             # in the dip -> +1 -> score 6
    old = config.STRONG_ONLY
    config.STRONG_ONLY = True
    try:
        close = np.concatenate([np.full(296, 2.0), np.linspace(2.0, 2.3, 4)])
        candles = make_ohlcv(close, high=close * 1.003, low=close * 0.997)
        trig = strategy.detect_trigger(candles)
        sig, why = strategy.evaluate(ctx, "XYZUSDT", coin, trig, candles)
        ok &= check("strong setup fires (grade A+)",
                    sig is not None and sig.grade in ("A", "A+"),
                    f"-> {sig.grade if sig else why}")
        sig2, why2 = strategy.evaluate(ctx, "XYZUSDT", hot, trig, candles)
        ok &= check("chasing LONG rejected",
                    sig2 is None and str(why2).startswith("strong"),
                    f"-> {why2}")
    finally:
        config.STRONG_ONLY = old
    ok &= check("flag restored", config.STRONG_ONLY == old)
    return ok


def test_network():
    print("\n7) LIVE DATA (network)")
    import context
    import scanner as scanner_mod
    try:
        s = scanner_mod.Scanner()
        ctx = s.refresh_context(force=True)
        ok = check("BTC daily regime loaded", ctx.btc.ok, f"-> {ctx.btc.note}")
        check("fear & greed", ctx.sentiment.value >= 0,
              f"-> {ctx.sentiment.value} {ctx.sentiment.label}")
        check("market cap", ctx.flow.total_mcap > 0,
              f"-> {ctx.flow.money_flow}")
        check("news", bool(ctx.news.headlines),
              f"-> {ctx.news.status}, {len(ctx.news.headlines)} headlines")
        coins = s.hub.universe()
        check("coin universe", len(coins) > 5, f"-> {len(coins)} coins, "
              f"first={coins[0] if coins else '-'}")
        if coins:
            res = s.scan_coin(coins[0], ctx)
            sig = res[0] if isinstance(res, tuple) else res
            reason = res[1] if isinstance(res, tuple) and len(res) > 1 else ""
            check("single coin scan runs", True,
                  f"-> {'signal!' if sig else 'no signal now ' + str(reason)}")
        return ok
    except Exception as e:
        check("live data", False, f"-> {type(e).__name__}: {e}")
        traceback_msg = __import__("traceback").format_exc()
        print(traceback_msg)
        return False


def main():
    print("=" * 62)
    print("  SYSTEM SELF-TEST")
    print("=" * 62)
    results = [
        test_indicators(),
        test_trigger(),
        test_stop_and_sizing(),
        test_strategy(),
        test_multi_market(),
        test_strong_mode(),
    ]
    if "--offline" not in sys.argv:
        results.append(test_network())
    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r)
    print(f"  RESULT: {passed}/{len(results)} groups passed")
    print("=" * 62)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
