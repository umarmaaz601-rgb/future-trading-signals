"""
TRADE OUTCOME TRACKING - did a published signal reach TP1/TP2/TP3 or
get stopped out?

The cloud runner calls update_outcomes() after every scan; it replays
the 1-minute candles AFTER the signal timestamp and records which
levels were touched, in order:

    "TP1"            TP1 hit, trade still running        (live)
    "TP1->TP2"       TP1 and TP2 hit, still running      (live)
    "TP1->TP2->TP3"  full ladder - done                   (final)
    "SL"             stopped out before any TP            (final)
    "TP1->SL"        TP1 first, then the stop             (final)

A single candle that touches BOTH the stop and the next target counts
as a stop (the order inside one candle is unknowable - conservative).

Coverage: crypto replays 1000x1m (~16.6h), or 1000x5m (~3.5 days)
for older signals; Yahoo instruments replay their 1m cache (~25h).
Older/unresolvable signals simply keep their last outcome.
"""
import time

MAX_AGE_1M = 16 * 3600          # 1000 x 1m candles
MAX_AGE_5M = 80 * 3600          # 1000 x 5m candles (~3.5 days)
MAX_AGE_YF = 25 * 3600          # 1500 x 1m bars kept by the yahoo cache


def _norm(ts_c):
    """Candle timestamp -> seconds (binance & yahoo both send ms)."""
    ts_c = float(ts_c)
    return ts_c / 1000.0 if ts_c > 1e11 else ts_c


def walk(candles, ts, side, sl, tps):
    """
    Replay candles = iterable of (t, high, low), chronological, from the
    signal time.  Returns (outcome, final):
      outcome None  - nothing touched yet (trade running untouched)
      outcome str   - "->" sequence of levels touched, e.g. "TP1->SL"
      final   True  - trade is over (SL hit or full ladder done)
    """
    long = side == "LONG"
    levels = [("TP1", tps[0] if len(tps) > 0 else None),
              ("TP2", tps[1] if len(tps) > 1 else None),
              ("TP3", tps[2] if len(tps) > 2 else None)]
    needs = {"TP1": None, "TP2": "TP1", "TP3": "TP2"}
    reached = []
    seq = None
    final = False
    for t, hi, lo in candles:
        if _norm(t) + 60 < ts:                # bar ended before the signal
            continue
        # --- stop first: one candle touching both stop and target = stop
        stop_hit = (lo <= sl) if long else (hi >= sl)
        if stop_hit:
            seq = "->".join(reached + ["SL"])
            return seq, True
        # --- targets in ladder order (a big candle can skip levels)
        grew = False
        for name, lvl in levels:
            if lvl is None or name in reached:
                continue
            prev = needs[name]
            if prev is not None and prev not in reached:
                continue
            hit = (hi >= lvl) if long else (lo <= lvl)
            if hit:
                reached.append(name)
                grew = True
        if grew:
            seq = "->".join(reached)
            if reached[-1] == "TP3":
                return seq, True
    return seq, final


# ------------------------------------------------------------ data fetch
def _crypto_candles(hub, sym, tf):
    data = hub._call(lambda p: p.klines(sym, tf, 1000))
    return list(zip(data.ts, data.high, data.low))


def _yf_candles(src, sym):
    data = src.candles_1m(sym)                 # up to 1500 x 1m, cached
    return list(zip(data.ts, data.high, data.low))


# ------------------------------------------------------------ entry point
def update_outcomes(signals, hub=None, log=None):
    """
    Refresh s["outcome"] / s["outcome_final"] of every tracked signal
    dict IN PLACE.  Signals whose trade is over are skipped from then on.
    """
    from yf_data import SOURCE, asset_class
    now = time.time()
    for s in signals:
        sym = str(s.get("symbol") or s.get("sym") or "")
        if not sym or "TEST" in sym or s.get("mkt") == "test":
            continue
        if s.get("outcome_final"):
            continue
        ts = float(s.get("ts") or 0)
        sl = s.get("stop_loss")
        if ts <= 0 or not sl or now <= ts:
            continue
        age = now - ts
        cls = s.get("cls") or asset_class(sym)

        if cls == "crypto":
            if hub is None:
                continue
            if age <= MAX_AGE_1M:
                tf = "1m"
            elif age <= MAX_AGE_5M:
                tf = "5m"
            else:
                continue
            fetch = lambda tf=tf: _crypto_candles(hub, sym, tf)
        else:
            if age > MAX_AGE_YF:
                continue
            fetch = lambda: _yf_candles(SOURCE, sym)

        try:
            candles = fetch()
        except Exception as e:
            if log:
                log(f"[outcome] {sym}: {e}")
            continue
        seq, final = walk(candles, ts, s.get("side"), float(sl),
                          [float(x) for x in (s.get("take_profits") or [])])
        if seq is None or (seq == s.get("outcome")
                           and bool(s.get("outcome_final")) == final):
            continue
        s["outcome"] = seq
        s["outcome_final"] = bool(final)
        if log:
            log(f"[outcome] {sym} {s.get('side')}: {seq}"
                f"{' (final)' if final else ''}")
