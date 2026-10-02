"""
Hypothetical levels for the top opportunity candidates.
Read-only: no telegram, no signals.log, no cooldown changes.
"""
import config
from scanner import Scanner
import strategy

s = Scanner()
ctx = s.refresh_context(force=True)

# (coin, side, score-from-full-diagnostic)
TARGETS = [
    ("MEGAUSDT",   "SHORT", 3),
    ("OPNUSDT",    "SHORT", 3),
    ("UUSDT",      "SHORT", 2),
    ("XAUTUSDT",   "SHORT", 2),
    ("PAXGUSDT",   "SHORT", 2),
    ("TONUSDT",    "SHORT", 2),
    ("OPNUSDT",    "LONG", -2),
    ("PLUMEUSDT",  "LONG", 0),
    ("SAGAUSDT",   "LONG", 0),
]


def grade_of(sc):
    import strategy
    return strategy.grade_of(sc, "crypto")


print("=" * 100)
print("  OPPORTUNITY CANDIDATES - hypothetical levels "
      f"(balance {config.ACCOUNT_BALANCE:,.0f} USDT, "
      f"{config.MAX_LEVERAGE}x, risk {config.RISK_PER_TRADE_PCT}%/trade)")
print("=" * 100)
print(f"  {'COIN':<11}{'SIDE':<7}{'score':<7}{'ENTRY':<12}{'STOP':<12}"
      f"{'STOP%':<8}{'TP1':<11}{'TP2':<11}{'TP3':<11}{'size/margin'}")
print("-" * 100)

for sym, side, score in TARGETS:
    try:
        daily = s.hub.daily_candles(sym)
        c2 = s.hub.trigger_candles(sym)
        reg = strategy.coin_daily(daily)
        trig = strategy.detect_trigger(c2)
    except Exception as e:
        print(f"  {sym:<11}{side:<7}data error: {e}")
        continue

    entry = float(c2.close[-1])
    sl = strategy.stop_from_2m(c2, side, entry)
    t = strategy.Trigger(fired=side,
                         age=trig.age if trig.fired == side else 999)
    sig = strategy.build_signal(sym, side, score, entry, sl, ctx, reg, t)
    stop_pct = abs(entry - sl) / entry * 100.0
    tp = sig.take_profits
    fired = "TRIGGERED" if trig.fired == side else "waiting cross"
    print(f"  {sym:<11}{side:<7}{score}({grade_of(score)})  "
          f"{entry:<12.6g}{sl:<12.6g}{stop_pct:<8.2f}"
          f"{tp[0]:<12.6g}{tp[1]:<12.6g}{tp[2]:<12.6g}"
          f"{sig.size_usdt:,.0f}/{sig.margin:,.0f}   {fired}")

print("-" * 100)
print("  note: 'TRIGGERED' = fresh 2-min cross exists NOW; "
      "'waiting cross' = levels only apply AFTER a cross appears.")
print("  SYSTEM VERDICT today: all score < 6 -> grade C -> "
      "not sent while min grade = B.")
print("=" * 100)
