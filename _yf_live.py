"""Quick live check of the Yahoo (forex / gold / stocks) data path."""
import sys
import config
from yf_data import (SOURCE, session_status, asset_class, instruments,
                     bench_inverted, yahoo_ticker)
import context as ctx_mod
import strategy

fails = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        fails.append(name)


print("== session gates ==")
for cls in ("crypto", "forex", "metal", "stock"):
    ok, note = session_status(cls)
    print(f"  {cls}: {'OPEN' if ok else 'CLOSED'} {note}")

print("== class lists ==")
total = 0
for cls in ("forex", "metal", "stock"):
    syms = instruments(cls)
    total += len(syms)
    print(f"  {cls}: {len(syms)} -> {syms}")
check("instrument lists", total >= 10, f"({total} total)")

print("== 1m + 2m trigger + daily ==")
for sym in ("EURUSD", "XAUUSD", "TSLA", "DXY"):
    try:
        m1 = SOURCE.candles_1m(sym, 500)
        t2 = SOURCE.trigger_2m(sym, config.TRIGGER_TF_CANDLES)
        d1 = SOURCE.candles_1d(sym)
        trig = strategy.detect_trigger(t2)
        reg = strategy.coin_daily(d1)
        check(f"{sym} ({yahoo_ticker(sym)})",
              len(m1.close) >= 300 and len(t2.close) >= 200 and d1 is not None,
              f"1m={len(m1.close)} 2m={len(t2.close)} daily={len(d1.close)} "
              f"reg.ok={reg.ok} trig.fired={trig.fired or '-'}")
    except Exception as e:
        check(f"{sym}", False, f"{type(e).__name__}: {e}")

print("== class context + scoring ==")
try:
    bench_reg = ctx_mod.analyse_daily(SOURCE.candles_1d("DXY"), "DXY")
    fctx = ctx_mod.build_class_context("forex", bench_reg)
    check("forex context", fctx.cls == "forex" and fctx.bench_name == "DXY"
          and fctx.flow.money_flow == "NEUTRAL" and fctx.news.status == "OK",
          f"above={bench_reg.above_ema120} cross={bench_reg.cross}")

    # EURUSD: DXY-inverted. USDJPY: not.
    import dataclasses
    fctx_inv = dataclasses.replace(fctx, bench_inverted=True)
    d1 = SOURCE.candles_1d("EURUSD")
    reg = strategy.coin_daily(d1)
    trig = strategy.Trigger(fired="LONG", age=1)

    # scanner behaviour: EURUSD is DXY-inverted
    trig = strategy.Trigger(fired="LONG", age=1)

    # session gate blocks
    closed = dataclasses.replace(fctx, bench_inverted=True, session_open=False,
                                 session_note="test closed")
    sig, why = strategy.evaluate(closed, "EURUSD", reg, trig, None)
    check("session gate", sig is None and "closed" in why, f"-> {why}")

    # normal context: evaluate runs end to end (entry needs candles)
    import numpy as np
    from market_data import OHLCV
    t2 = SOURCE.trigger_2m("EURUSD", config.TRIGGER_TF_CANDLES)
    sig, why = strategy.evaluate(fctx_inv, "EURUSD", reg, trig, t2)
    print(f"  evaluate EURUSD (DXY above={bench_reg.above_ema120}): {why}")
    if sig is not None:
        print(f"    -> {sig.side} grade {sig.grade} cls={sig.cls} "
              f"bench_inv={fctx.bench_inverted}")
        check("signal class field", sig.cls == "forex")
        check("forex grade cutoff", sig.grade in ("A+", "A", "B", "C"))

    # grade cutoffs
    check("grade_of forex", strategy.grade_of(6, "forex") == "A+"
          and strategy.grade_of(4, "forex") == "B"
          and strategy.grade_of(5, "crypto") == "C"
          and strategy.grade_of(6, "crypto") == "B",
          f"({strategy.grade_of(4,'forex')}/{strategy.grade_of(6,'forex')})")

    # inverted vs not: same DXY regime, opposite support
    s_long_inv = strategy.score_setup(fctx_inv, reg, "LONG")
    s_long_no = strategy.score_setup(fctx, reg, "LONG")
    check("bench inversion flips score", s_long_inv != s_long_no,
          f"inv={s_long_inv} plain={s_long_no}")
except Exception as e:
    import traceback
    traceback.print_exc()
    check("class context flow", False, str(e))

print("== stock context ==")
try:
    spy_reg = ctx_mod.analyse_daily(SOURCE.candles_1d("SPY"), "SPY")
    sctx = ctx_mod.build_class_context("stock", spy_reg)
    check("stock context", sctx.bench_name == "SPY" and sctx.cls == "stock",
          f"above={spy_reg.above_ema120}")
except Exception as e:
    check("stock context", False, str(e))

print()
print("RESULT:", "ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
