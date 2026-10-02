"""
THE DECISION ENGINE

Hard truth from the method:
   "Only one thing is important - will money come into the market
    or leave it. If you don't understand this, future trading is a flop."

So every signal must pass 3 layers:

  LAYER 1 - MARKET FILTER  (whole market, applied to every coin)
      news status, money flow, BTC above/below EMA120, golden/death cross,
      fear & greed

  LAYER 2 - COIN FILTER (that coin's own daily chart)
      coin above/below its EMA120, daily Bollinger + RSI (dip / top zone)

  LAYER 3 - TRIGGER (2-minute chart)
      EMA20 crossed EMA200  ->  LONG or SHORT

Score everything -> grade A+ / A / B / C.  Only A+ A B are sent.
"""
from dataclasses import dataclass, field

import numpy as np

import config
import indicators

GRADE_ORDER = {"A+": 3, "A": 2, "B": 1, "C": 0}

# score cutoffs per market class (non-crypto has fewer checklist factors:
# no dominance / money-flow / fear&greed -> lower rungs for the same
# amount of alignment)
#   crypto : A+ 8+, A 6+, B 4+   (max achievable = 10)
#   others : A+ 6+, A 5+, B 4+   (max achievable = 6-7)
GRADE_CUT = {
    "crypto": (8, 6, 4),     # A+ / A / B
    "forex": (6, 5, 4),
    "metal": (6, 5, 4),
    "stock": (6, 5, 4),
}


def grade_of(score, cls="crypto"):
    """A+ / A / B cutoffs are class-aware (see GRADE_CUT)."""
    a_plus, a, b = GRADE_CUT.get(cls, GRADE_CUT["crypto"])
    if score >= a_plus:
        return "A+"
    if score >= a:
        return "A"
    if score >= b:
        return "B"
    return "C"


# ------------------------------------------------- market layer helpers
def _bench_above(ctx):
    """Is the benchmark trend favorable? (handles DXY-inverted pairs)"""
    above = ctx.btc.above_ema120
    return (not above) if getattr(ctx, "bench_inverted", False) else above


def _bench_cross(ctx):
    cross = ctx.btc.cross
    if getattr(ctx, "bench_inverted", False):
        return {"GOLDEN": "DEATH", "DEATH": "GOLDEN"}.get(cross, cross)
    return cross


# ---------------------------------------------------------------- trigger
@dataclass
class Trigger:
    fired: str = ""        # "LONG" | "SHORT" | ""
    age: int = 999         # candles since the cross
    fast: float = 0.0
    slow: float = 0.0


def detect_trigger(candles):
    """2-minute EMA20 vs EMA200 cross (the entry trigger)."""
    t = Trigger()
    if len(candles) < config.TRIGGER_SLOW + 5:
        return t
    c = candles.close
    fast = indicators.ema(c, config.TRIGGER_FAST)
    slow = indicators.ema(c, config.TRIGGER_SLOW)
    t.fast = float(fast[-1])
    t.slow = float(slow[-1])
    side, idx = indicators.latest_cross(fast, slow)
    if side:
        t.age = len(c) - 1 - idx
        if t.age <= config.TRIGGER_MAX_AGE_CANDLES:
            t.fired = side
    return t


# ---------------------------------------------------------------- context helpers
def _flow_supports(flow, side):
    """Does the direction of money support this side?"""
    if side == "LONG":
        if flow in ("ROTATING_IN", "BTC_SEASON"):
            return 2 if flow == "ROTATING_IN" else 1
        if flow in ("LEAVING", "PANIC"):
            return -3
        return 0
    else:  # SHORT
        if flow in ("LEAVING", "PANIC"):
            return 2
        if flow == "ROTATING_IN":
            return -3
        if flow == "BTC_SEASON":
            return -1
        return 0


def _sentiment_supports(value, side):
    if value < 0:
        return 0
    if side == "LONG":
        if value <= 25:
            return 2        # extreme fear = classic dip buy
        if value <= 45:
            return 1
        if value >= 75:
            return -1       # extreme greed, longs are crowded
        return 0
    else:
        if value >= 75:
            return 2
        if value >= 55:
            return 1
        if value <= 25:
            return -1
        return 0


def coin_daily(candles):
    """Layer 2: analyse the coin's own daily chart."""
    from context import analyse_daily
    return analyse_daily(candles, "coin")


def _daily_supports(reg, side):
    """Returns (regime_points, dip_points) for this side."""
    if not reg.ok:
        return 0, 0
    regime = 0
    if side == "LONG":
        regime = 1 if reg.above_ema120 else -1
        dip = 1 if (reg.bb_state == "BELOW_LOWER" or reg.rsi <= config.RSI_OVERSOLD) else 0
    else:
        regime = 1 if not reg.above_ema120 else -1
        dip = 1 if (reg.bb_state == "ABOVE_UPPER" or reg.rsi >= config.RSI_OVERBOUGHT) else 0
    return regime, dip


# ---------------------------------------------------------------- scoring
def score_setup(ctx, coin_reg, side):
    """
    Score for one side AS IF the 2-minute trigger had just fired.
    Used both by evaluate() (real signals) and by the watchlist
    (how ready is this coin - it will get this exact score when a
    cross appears).  Range roughly -4 .. 10.
    """
    score = 1                       # the trigger itself

    # benchmark regime (BTC for crypto, DXY for forex/gold, SPY stocks)
    if side == "LONG":
        score += 1 if _bench_above(ctx) else -1
    else:
        score += 1 if not _bench_above(ctx) else -1

    # golden / death cross of that benchmark
    cross = _bench_cross(ctx)
    if side == "LONG":
        score += 1 if cross == "GOLDEN" else (-1 if cross == "DEATH" else 0)
    else:
        score += 1 if cross == "DEATH" else (-1 if cross == "GOLDEN" else 0)

    # money flow
    score += _flow_supports(ctx.flow.money_flow, side)

    # fear & greed
    score += _sentiment_supports(ctx.sentiment.value, side)

    # news warning
    if ctx.news.status == "WARNING":
        score -= 1
    else:
        score += 1

    # coin's own daily chart
    regime, dip = _daily_supports(coin_reg, side)
    score += regime + dip
    return score


def block_reason(ctx, side):
    """Hard market block for this side, or '' if tradeable."""
    if ctx.news.status == "HALT":
        return "news HALT"
    if not getattr(ctx, "session_open", True):
        note = getattr(ctx, "session_note", "")
        return f"market closed ({note})" if note else "market closed"
    flow = ctx.flow.money_flow
    if side == "LONG" and flow in ("LEAVING", "PANIC"):
        return f"money flow {flow} blocks longs"
    if side == "SHORT" and flow == "ROTATING_IN":
        return "money rotating into alts blocks shorts"
    bench = getattr(ctx, "bench_name", "BTC")
    if side == "LONG" and not _bench_above(ctx) and flow != "ROTATING_IN":
        return f"{bench} below EMA120 (bearish regime) blocks longs"
    return ""


def strong_reason(ctx, coin_reg, trig=None, side="LONG"):
    """
    STRONG mode: EVERY checklist item must agree - not just score points.
    Returns '' when this side is a strong setup, else why it is not:
      news not HALT (WARNING allowed)  +  cross not against the side
      +  coin's own daily trend agreeing  +  daily not stretched (longs:
      RSI <= STRONG_RSI_LONG and band not at the upper edge; shorts:
      RSI >= STRONG_RSI_SHORT and band not at the lower edge) so we
      never chase  +  fresh cross (only when a live trigger is given)
      +  grade A.
    """
    if ctx.news.status == "HALT":
        return "strong: news is HALT (cannot trade)"
    cross = _bench_cross(ctx)
    if side == "LONG" and cross == "DEATH":
        return "strong: DEATH cross blocks longs"
    if side == "SHORT" and cross == "GOLDEN":
        return "strong: GOLDEN cross blocks shorts"
    if coin_reg.ok:
        if side == "LONG" and not coin_reg.above_ema120:
            return "strong: coin below its daily EMA120 (trend must agree)"
        if side == "SHORT" and coin_reg.above_ema120:
            return "strong: coin above its daily EMA120 (trend must agree)"
        if side == "LONG" and (coin_reg.bb_state == "ABOVE_UPPER" or
                               coin_reg.rsi > config.STRONG_RSI_LONG):
            return (f"strong: daily too hot to buy "
                    f"(RSI {coin_reg.rsi:.0f} vs max "
                    f"{config.STRONG_RSI_LONG}, BB {coin_reg.bb_state})")
        if side == "SHORT" and (coin_reg.bb_state == "BELOW_LOWER" or
                                coin_reg.rsi < config.STRONG_RSI_SHORT):
            return (f"strong: daily too cold to sell "
                    f"(RSI {coin_reg.rsi:.0f} vs min "
                    f"{config.STRONG_RSI_SHORT}, BB {coin_reg.bb_state})")
    if trig is not None and trig.fired and trig.age > config.STRONG_MAX_AGE:
        return f"strong: cross too old (age {trig.age} > {config.STRONG_MAX_AGE})"
    return ""


def opportunity(ctx, coin_reg, side):
    """
    Watchlist helper - (score, block) WITHOUT needing a live trigger.
    score = exactly what evaluate() would score if a cross fired now.
    """
    if not ctx.btc.ok:
        return -99, f"{getattr(ctx, 'bench_name', 'BTC')} daily data missing"
    if not coin_reg.ok:
        return -99, "coin daily data missing"
    blk = block_reason(ctx, side)
    if not blk and getattr(config, "STRONG_ONLY", False):
        blk = strong_reason(ctx, coin_reg, None, side)
    return score_setup(ctx, coin_reg, side), blk


# ---------------------------------------------------------------- probability
def prob_1to2(candles, side, stop_pct):
    """
    P(price reaches TP1 = TP1_R x risk BEFORE the stop loss).

    Measured empirically: replay every one of the last PROB_LOOKBACK
    2-minute candles as if it were an entry (same stop distance as the
    real signal) and see which barrier was touched first.  Candle
    touching both counts as a loss (conservative, same rule as the
    RESULTS tracker).

    Returns the ratio, or None when too few replays decided yet.
    """
    if stop_pct <= 0 or len(candles.close) < 30:
        return None
    n = len(candles.close)
    risk = stop_pct / 100.0                      # 1R as a price fraction
    tp = risk * config.TP1_R                     # target distance (2R)
    start = max(1, n - config.PROB_LOOKBACK)
    wins = losses = 0
    for i in range(start, n - 1):
        base = float(candles.close[i])
        for j in range(i + 1, n):
            hi, lo = float(candles.high[j]), float(candles.low[j])
            if side == "LONG":
                hit_win, hit_loss = hi >= base * (1 + tp), lo <= base * (1 - risk)
            else:
                hit_win, hit_loss = lo <= base * (1 - tp), hi >= base * (1 + risk)
            if hit_loss:                         # conservative: SL first
                losses += 1
                break
            if hit_win:
                wins += 1
                break
    total = wins + losses
    if total < 10:                               # not enough decided replays
        return None
    return wins / total


# ---------------------------------------------------------------- signal
@dataclass
class Signal:
    symbol: str
    side: str                 # LONG | SHORT
    cls: str = "crypto"       # crypto | forex | metal | stock
    grade: str = "C"
    score: int = 0
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profits: tuple = ()
    stop_pct: float = 0.0
    leverage: int = 50
    margin: float = 0.0
    size_usdt: float = 0.0
    risk_usdt: float = 0.0
    prob: float = -1.0        # P(1:2) measured on the 2m chart (-1 = n/a)
    checklist: list = field(default_factory=list)
    ts: float = 0.0


def build_signal(symbol, side, score, entry, sl, ctx, coin_reg, trig,
                 prob=-1.0):
    """Fill in grade, leverage, position size, SL/TP and the checklist."""
    stop_pct = abs(entry - sl) / entry * 100.0 if entry else 0.0

    # --- position sizing: risk only RISK_PER_TRADE_PCT of the balance
    risk_usdt = config.ACCOUNT_BALANCE * config.RISK_PER_TRADE_PCT / 100.0
    size_usdt = risk_usdt / (stop_pct / 100.0) if stop_pct > 0 else 0.0
    max_margin = config.ACCOUNT_BALANCE * config.MAX_MARGIN_PCT / 100.0
    max_size = max_margin * config.MAX_LEVERAGE
    if size_usdt > max_size:
        size_usdt = max_size
    margin = size_usdt / config.MAX_LEVERAGE if config.MAX_LEVERAGE else 0.0

    risk_r = (entry - sl) if side == "LONG" else (sl - entry)
    tps = []
    for r in (config.TP1_R, config.TP2_R, config.TP3_R):
        if side == "LONG":
            tps.append(entry + risk_r * r)
        else:
            tps.append(entry - risk_r * r)

    sig = Signal(symbol=symbol, side=side, score=score, entry=entry,
                 stop_loss=sl, take_profits=tuple(tps), stop_pct=stop_pct,
                 leverage=config.MAX_LEVERAGE, margin=margin,
                 size_usdt=size_usdt, risk_usdt=min(risk_usdt, size_usdt * stop_pct / 100.0))
    sig.cls = getattr(ctx, "cls", "crypto")
    sig.prob = float(prob)

    # grade (cutoffs differ per market class - see GRADE_CUT)
    sig.grade = grade_of(score, sig.cls)

    # ---------------- the checklist that is printed with the signal
    f, s, b = ctx.flow, ctx.sentiment, ctx.btc
    ck = []
    if sig.cls == "crypto":
        ck.append(("News", ctx.news.status == "OK",
                   f"{ctx.news.status} - {ctx.news.note}"))
        ck.append(("Money flow", _flow_supports(f.money_flow, side) > 0,
                   f"{f.money_flow} ({f.dominance:.1f}% dom {f.dominance_trend.lower()}"
                   f", 24h cap {f.mcap_delta_pct:+.1f}%)"))
        ck.append(("BTC regime", (b.above_ema120 == (side == "LONG")),
                   f"BTC {'above' if b.above_ema120 else 'below'} EMA120"
                   f" - {b.cross} cross"))
        ck.append(("Fear & Greed", _sentiment_supports(s.value, side) > 0,
                   f"{s.value} {s.label}"))
    else:
        # forex / metals / stocks: session gate + benchmark (DXY / SPY)
        bench = getattr(ctx, "bench_name", "DXY")
        ck.append(("Trading session", getattr(ctx, "session_open", True),
                   getattr(ctx, "session_note", "") or "market open"))
        eff_above = _bench_above(ctx)
        ck.append((f"{bench} regime", eff_above == (side == "LONG"),
                   f"{bench} {'above' if b.above_ema120 else 'below'} EMA120"
                   f" - favors {'LONGS' if eff_above else 'SHORTS'}"
                   f" ({b.cross} cross)"))
    regime_ok, dip_ok = _daily_supports(coin_reg, side)
    ck.append((("Coin daily EMA120" if sig.cls == "crypto"
                else f"{sig.symbol} daily EMA120"), regime_ok > 0,
               f"{'above' if coin_reg.above_ema120 else 'below'} EMA120"
               f", RSI {coin_reg.rsi:.0f}"))
    ck.append(("Daily dip/top", dip_ok > 0,
               f"Bollinger {coin_reg.bb_state}"))
    ck.append(("2m trigger", True,
               f"EMA{config.TRIGGER_FAST} x EMA{config.TRIGGER_SLOW} cross"
               f" {trig.age} candle(s) ago"))
    ck.append(("1:2 probability",
               prob is None or prob >= config.PROB_MIN,
               (f"{prob:.0%} to hit TP1 ({config.TP1_R:.0f}R) before SL"
                if prob is not None else "not enough 2m history")
               + f" - need ≥{config.PROB_MIN:.0%}"))
    sig.checklist = ck
    return sig


# ---------------------------------------------------------------- evaluate
def evaluate(ctx, symbol, coin_reg, trig, candles_2m):
    """
    Run all 3 layers. Returns (signal, reason).
    signal is None when no trade should be taken, then reason says why.
    """
    # ---------- LAYER 1 hard blocks (whole market) ----------
    if ctx.news.status == "HALT":
        return None, "news HALT"
    if not trig.fired:
        return None, "no fresh 2m EMA20/EMA200 cross"
    if not ctx.btc.ok:
        return None, f"{getattr(ctx, 'bench_name', 'BTC')} daily data missing"
    if not coin_reg.ok:
        return None, "coin daily data missing"

    side = trig.fired

    # hard market blocks (same function the watchlist shows)
    blk = block_reason(ctx, side)
    if blk and blk != "news HALT":          # HALT already handled above
        return None, blk

    # ---------- STRONG mode: every checklist item must agree ----------
    if getattr(config, "STRONG_ONLY", False):
        sr = strong_reason(ctx, coin_reg, trig, side)
        if sr:
            return None, sr

    # ---------- scoring ----------
    score = score_setup(ctx, coin_reg, side)

    # ---------- entry / stop-loss on the 2-minute chart ----------
    entry = float(candles_2m.close[-1])
    sl = stop_from_2m(candles_2m, side, entry)
    stop_pct = abs(entry - sl) / entry * 100.0 if entry else 0.0

    # ---------- 1:2 probability (replay of the last 2m candles) ----------
    prob = prob_1to2(candles_2m, side, stop_pct)
    sig = build_signal(symbol, side, score, entry, sl, ctx, coin_reg, trig,
                       prob=prob)
    if GRADE_ORDER[sig.grade] < GRADE_ORDER[config.MIN_GRADE]:
        return None, f"grade {sig.grade} below minimum {config.MIN_GRADE} (score {score})"
    if getattr(config, "STRONG_ONLY", False) and \
            GRADE_ORDER[sig.grade] < GRADE_ORDER["A"]:
        return None, (f"strong: needs grade A "
                      f"({sig.grade}, score {score})")
    if prob is not None and prob < config.PROB_MIN:
        return None, (f"1:2 probability {prob:.0%} < {config.PROB_MIN:.0%} "
                      f"(needs {config.TP1_R:.0f}R before SL)")
    return sig, f"grade {sig.grade} (score {score})"


def stop_from_2m(candles, side, entry):
    """
    Stop-loss = last swing point on the 2-minute chart,
    clamped inside [MIN_STOP_PCT, MAX_STOP_PCT].
    """
    lookback = 10
    if side == "LONG":
        swing = float(np.min(candles.low[-lookback:]))
        dist = (entry - swing) / entry * 100.0
    else:
        swing = float(np.max(candles.high[-lookback:]))
        dist = (swing - entry) / entry * 100.0
    dist = max(config.MIN_STOP_PCT, min(config.MAX_STOP_PCT, dist))
    if side == "LONG":
        return entry * (1 - dist / 100.0)
    return entry * (1 + dist / 100.0)
