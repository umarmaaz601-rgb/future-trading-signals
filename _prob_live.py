"""Quick calibration check: what P(1:2) values does live 2m data give?"""
import market_data
import strategy
import config

hub = market_data.DataHub()
print("sym        P(LONG) at stop 0.2/0.4/0.6%   P(SHORT) at stop 0.2/0.4/0.6%")
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ARUSDT", "ENAUSDT"):
    try:
        data = hub._call(lambda p: p.klines(sym, "2m", 240))   # scanner length
        longs, shorts = [], []
        for stop in (0.2, 0.4, 0.6):
            pl = strategy.prob_1to2(data, "LONG", stop)
            ps = strategy.prob_1to2(data, "SHORT", stop)
            longs.append("-" if pl is None else f"{pl:.0%}")
            shorts.append("-" if ps is None else f"{ps:.0%}")
        print(f"{sym:<10} {' / '.join(longs):<30} {' / '.join(shorts)}")
    except Exception as e:
        print(sym, "ERR", e)
print(f"PROB_MIN = {config.PROB_MIN:.0%}   TP1_R = {config.TP1_R}R   "
      f"lookback = {config.PROB_LOOKBACK} candles")
