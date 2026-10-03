"""One-off: did MRK / NZDCAD really hit SL first, or did TP1 come
before it inside the same candle?  Prints first-touch detail per level
using real Yahoo 1-minute bars."""
import yf_data as Y
from outcomes import walk

CASES = [
    # sym, side, ts(UTC sec), entry, sl, [tp1, tp2, tp3]
    ("MRK", "LONG", 1790963768, 143.675, 143.48,
     [144.065, 144.26, 144.65]),
    ("NZDCAD", "SHORT", 1790963764, 0.79963, 0.80043,
     [0.798031, 0.797231, 0.795632]),
]


def main():
    for sym, side, ts, entry, sl, tps in CASES:
        tp1 = tps[0]
        data = Y.SOURCE.candles_1m(sym)
        bars = list(zip(data.ts, data.open, data.high, data.low))
        seq, fin = walk([(t, h, l) for t, o, h, l in bars],
                        ts, side, sl, tps)
        print(f"\n=== {sym} {side}  walk -> {seq} (final={fin}) ===")
        # first bar touching each level, with the bar's open
        first_sl = first_tp = None
        for t, o, h, l in bars:
            if t / 1000 + 60 < ts:
                continue
            import datetime as dt
            when = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
            sl_hit = (l <= sl) if side == "LONG" else (h >= sl)
            tp_hit = (h >= tp1) if side == "LONG" else (l <= tp1)
            if tp_hit and first_tp is None:
                first_tp = (when, o, h, l)
            if sl_hit and first_sl is None:
                first_sl = (when, o, h, l)
            if first_tp and first_sl:
                break
        def fmt(x):
            if not x:
                return "never"
            when, o, h, l = x
            return f"{when:%H:%M:%S} open={o:.6g} low={l:.6g} high={h:.6g}"
        print(f"  first TP1 touch: {fmt(first_tp)}")
        print(f"  first SL  touch: {fmt(first_sl)}")
        if first_tp and first_sl:
            same = first_tp[0] == first_sl[0]
            print(f"  -> {'SAME candle (ambiguous)' if same else 'different candles: ' + ('TP1 FIRST' if first_tp[0] < first_sl[0] else 'SL FIRST')}")


if __name__ == "__main__":
    main()
