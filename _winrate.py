"""
SIGNAL RESULTS - TP1 or SL, which came first?
Reads signals.log, replays 1-minute candles from the moment of the signal.
Conservative rule: if one candle touches BOTH levels, it counts as SL.

Run:  python _winrate.py
"""
import re
import sys
import time

import config

LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<side>LONG|SHORT) "
    r"(?P<sym>\S+) grade=(?P<grade>\S+) score=(?P<score>-?\d+) "
    r"entry=(?P<entry>\S+) sl=(?P<sl>\S+) tp=(?P<tp>[\d.,]+) "
    r"lev=(?P<lev>\d+)x(?: p=(?P<prob>\d{1,3})%)?(?: mkt=(?P<mkt>\S+))?$")

HUB = None
YF = None


def load():
    rows = []
    try:
        with open(config.LOG_FILE, encoding="utf-8") as f:
            for line in f:
                m = LINE.match(line.strip())
                if not m:
                    continue
                d = m.groupdict()
                d["entry"] = float(d["entry"])
                d["sl"] = float(d["sl"])
                d["tp"] = [float(x) for x in d["tp"].split(",")]
                d["score"] = int(d["score"])
                d["mkt"] = d["mkt"] or "crypto"
                d["prob"] = (int(d["prob"]) / 100.0
                             if d.get("prob") else None)
                d["t0"] = time.mktime(time.strptime(d["ts"], "%Y-%m-%d %H:%M:%S"))
                rows.append(d)
    except OSError as e:
        print(f"cannot read {config.LOG_FILE}: {e}")
    return rows


def candles_1m(sym, mkt):
    global HUB, YF
    if mkt == "crypto":
        if HUB is None:
            import market_data
            HUB = market_data.DataHub()
        return HUB._call(lambda p: p.klines(sym, "1m", 300))
    if YF is None:
        import yf_data
        YF = yf_data.SOURCE
    return YF.candles_1m(sym, 500)


def raw_swing_pct(r, data):
    """Swing distance the stop SHOULD have used (before the 0.1-0.6% clamp)."""
    t0 = r["t0"] * 1000.0
    idx = [i for i in range(len(data.ts)) if data.ts[i] <= t0 + 60000.0]
    if len(idx) < 10:
        return None
    seg = idx[-20:]                     # ~20 minutes, same window as the bot
    if r["side"] == "LONG":
        swing = min(float(data.low[i]) for i in seg)
        return (r["entry"] - swing) / r["entry"] * 100.0
    swing = max(float(data.high[i]) for i in seg)
    return (swing - r["entry"]) / r["entry"] * 100.0


def outcome(r):
    """-> (result, detail) with result in TP1|TP2|TP3|SL|OPEN|OPEN(stale)"""
    try:
        data = candles_1m(r["sym"], r["mkt"])
    except Exception as e:
        return "ERR", str(e)[:40]
    t0 = r["t0"] * 1000.0
    long_ = r["side"] == "LONG"
    sl, entry = r["sl"], r["entry"]
    tps = r["tp"]
    started = False
    for i in range(len(data.ts)):
        if data.ts[i] <= t0:
            continue                        # skip the signal candle itself
        started = True
        hi, lo = float(data.high[i]), float(data.low[i])
        if long_:
            hit_sl = lo <= sl
            hits = [k + 1 for k, tp in enumerate(tps) if hi >= tp]
        else:
            hit_sl = hi >= sl
            hits = [k + 1 for k, tp in enumerate(tps) if lo <= tp]
        if hit_sl:
            return "SL", (f"TP reached too: {hits}" if hits else "")
        if hits:
            return f"TP{max(hits)}", ""
    if not started:
        return "OPEN", "no candles after signal yet"
    # nothing hit yet - is the feed still updating?
    age_min = (time.time() - r["t0"]) / 60.0
    last_min = (time.time() * 1000 - float(data.ts[-1])) / 60000.0
    if last_min > 15:
        return "STALE", f"feed last update {last_min:.0f}m ago"
    return "OPEN", f"{age_min:.0f}m running"


def main():
    rows = load()
    if not rows:
        print("no signals in signals.log yet")
        sys.exit(0)
    print("=" * 96)
    print("  SIGNAL RESULTS  (TP1 = win, SL = loss; same-candle touch counts as SL)")
    print("=" * 96)
    print(f"  {'TIME':<9}{'MKT':<8}{'SIDE':<6}{'SYM':<11}{'GR':<4}{'SC':<4}"
          f"{'P12':<6}{'RESULT':<7}{'RAW%':<7}{'note'}")
    done = []
    for r in rows:
        res, note = outcome(r)
        r["res"] = res
        try:
            data = candles_1m(r["sym"], r["mkt"])
            raw = raw_swing_pct(r, data)
        except Exception:
            raw = None
        r["raw"] = raw
        raw_txt = f"{raw:.2f}" if raw is not None else "-"
        if raw is not None and raw > config.MAX_STOP_PCT:
            raw_txt += "!"
        p_txt = f"{r['prob']:.0%}" if r.get("prob") is not None else "—"
        done.append(r)
        print(f"  {r['ts'][11:]:<9}{r['mkt'][:7]:<8}{r['side']:<6}"
              f"{r['sym'][:10]:<11}{r['grade']:<4}{r['score']:<4}"
              f"{p_txt:<6}{res:<7}{raw_txt:<7}{note}")

    def tally(sel):
        wins = sum(1 for r in done if sel(r) and r["res"] in ("TP1", "TP2", "TP3"))
        loss = sum(1 for r in done if sel(r) and r["res"] == "SL")
        open_ = sum(1 for r in done if sel(r) and r["res"] in ("OPEN", "STALE"))
        other = sum(1 for r in done if sel(r) and r["res"] not in
                    ("TP1", "TP2", "TP3", "SL", "OPEN", "STALE"))
        return wins, loss, open_, other

    def show(label, sel):
        w, l, o, x = tally(sel)
        dec = w + l
        rate = f"{100.0 * w / dec:.0f}%" if dec else "-"
        print(f"  {label:<28}{w} win / {l} loss / {o} open"
              f"  -> decided win rate {rate}")

    print()
    show("ALL signals", lambda r: True)
    show("by grade A/A+", lambda r: r["grade"] in ("A+", "A"))
    show("by grade B", lambda r: r["grade"] == "B")
    show("by grade C", lambda r: r["grade"] == "C")
    show("score >= 4", lambda r: r["score"] >= 4)
    show("score < 0", lambda r: r["score"] < 0)
    show("crypto", lambda r: r["mkt"] == "crypto")
    show("forex/metals", lambda r: r["mkt"] in ("forex", "metal"))
    show("LONG", lambda r: r["side"] == "LONG")
    show("SHORT", lambda r: r["side"] == "SHORT")
    print()
    show("stop was CLAMPED (raw>0.6%)",
         lambda r: r.get("raw") is not None and r["raw"] > config.MAX_STOP_PCT)
    show("stop had full room (raw<=0.6%)",
         lambda r: r.get("raw") is not None and r["raw"] <= config.MAX_STOP_PCT)
    show(f"P(1:2) >= {config.PROB_MIN:.0%} (filter passes)",
         lambda r: r.get("prob") is not None
                   and r["prob"] >= config.PROB_MIN)
    show(f"P(1:2) < {config.PROB_MIN:.0%} (would be blocked)",
         lambda r: r.get("prob") is not None
                   and r["prob"] < config.PROB_MIN)
    print("=" * 96)


if __name__ == "__main__":
    main()
