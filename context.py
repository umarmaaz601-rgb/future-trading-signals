"""
THE CHECKLIST  (the part that decides: is money coming in or going out?)

 1. News            -> Google / Yahoo crypto news, is anything bad happening?
 2. BTC dominance   -> falling or rising?
 3. Total market cap-> is world money leaving crypto or rotating inside it?
 4. Money flow      -> conclusion of 2 + 3
 5. Fear & Greed    -> are people scared or greedy?
 6. BTC > EMA120?   -> daily trend (the whole market follows Bitcoin)
 7. Golden / Death cross (EMA50 vs MA200) on the daily
 8. Daily Bollinger + RSI -> dip (buy) or top (sell) zone
"""
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote

import numpy as np
import requests

import config
import indicators
from market_data import DataError

# --------------------------------------------------------------- helpers


def _get_json(url, params=None, timeout=15):
    r = requests.get(url, params=params, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def load_state():
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            pass
    return {"dom_history": [], "cooldowns": {}}


def save_state(state):
    try:
        # keep the file small
        state["dom_history"] = state.get("dom_history", [])[-400:]
        # write to a temp file first, then atomically replace, so two
        # processes can never leave a half-written state.json
        tmp = config.STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, config.STATE_FILE)
    except OSError:
        pass


# --------------------------------------------------------------- 1) NEWS
@dataclass
class NewsReport:
    status: str = "OK"              # OK | WARNING | HALT
    headlines: list = field(default_factory=list)
    negative: int = 0
    critical: int = 0
    bad_items: list = field(default_factory=list)   # the offending titles
    note: str = "no bad news found"


def _parse_pubdate(text):
    """RFC-822 date from RSS -> epoch seconds, or None."""
    if not text:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(text)
        if dt is None:
            return None
        import datetime as _dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def fetch_news():
    """Free news: Google News RSS, falls back to Bing News RSS."""
    rep = NewsReport()
    raw_items = []
    urls = [
        ("https://news.google.com/rss/search?q=" + quote(config.NEWS_QUERY)
         + "&hl=en-US&gl=US&ceid=US:en"),
        ("https://www.bing.com/news/search?q=" + quote(config.NEWS_QUERY)
         + "&format=RSS"),
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=12,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            root = ET.fromstring(r.text)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                if title:
                    raw_items.append((title, _parse_pubdate(pub)))
            if raw_items:
                break
        except Exception:
            continue

    if not raw_items:
        rep.status = "WARNING"
        rep.note = "could not read any news feed -> do not trade blind"
        return rep

    # ONLY headlines from the last NEWS_LOOKBACK_HOURS count.
    # Old news (a hack from last month) must never block today's trading.
    cutoff = time.time() - config.NEWS_LOOKBACK_HOURS * 3600
    fresh = []
    undated = 0
    for title, ts in raw_items:
        if ts is None:
            undated += 1
            if undated > 10:      # feed without dates -> trust order, cap it
                continue
            fresh.append(title)
        elif ts >= cutoff:
            fresh.append(title)
        if len(fresh) >= 30:
            break

    neg, crit = [], []
    for title in fresh:
        t = title.lower()
        if any(w in t for w in config.NEWS_CRITICAL_WORDS):
            crit.append(title)
        if any(w in t for w in config.NEWS_NEGATIVE_WORDS):
            neg.append(title)

    rep.headlines = fresh[:12]
    rep.negative = len(neg)
    rep.critical = len(crit)
    rep.bad_items = (crit + [x for x in neg if x not in crit])[:6]

    if rep.critical >= config.NEWS_CRITICAL_LIMIT:
        rep.status = "HALT"
        rep.note = f"{rep.critical} critical headlines in last {config.NEWS_LOOKBACK_HOURS}h -> NO TRADING"
    elif rep.negative >= config.NEWS_NEGATIVE_LIMIT:
        rep.status = "WARNING"
        rep.note = f"{rep.negative} negative headlines in last {config.NEWS_LOOKBACK_HOURS}h -> trade extra careful"
    else:
        rep.status = "OK"
        rep.note = f"news clean (checked last {config.NEWS_LOOKBACK_HOURS}h, {len(fresh)} items)"
    return rep


# --------------------------------------------- 2+3) DOMINANCE / MARKET CAP
@dataclass
class FlowReport:
    dominance: float = 0.0
    dominance_delta: float = 0.0     # % points vs ~6-24h ago
    dominance_trend: str = "UNKNOWN"  # FALLING | RISING | FLAT | UNKNOWN
    total_mcap: float = 0.0
    mcap_delta_pct: float = 0.0      # 24h %
    money_flow: str = "UNKNOWN"      # ROTATING_IN | BTC_SEASON | LEAVING | PANIC
    method: str = "unknown"          # how the dominance move was measured
    note: str = "waiting for data"


FLOW_NOTES = {
    "ROTATING_IN": "Dominance DOWN + total cap stable/up = money rotating INTO ALTS -> altcoins will pump",
    "BTC_SEASON": "Dominance UP + total cap UP = new money entering, Bitcoin leading",
    "LEAVING": "Dominance DOWN + total cap DOWN = money LEAVING the whole market -> shorts only, be careful",
    "PANIC": "Dominance UP + total cap DOWN = PANIC, people running to cash -> shorts only",
    "UNKNOWN": "Not enough data yet - keep this file running for a day",
}


def fetch_flow(state, btc_change_24h=None):
    rep = FlowReport()
    try:
        g = _get_json("https://api.coingecko.com/api/v3/global")
        data = g.get("data", {})
        dom = float(data.get("market_cap_percentage", {}).get("btc", 0) or 0)
        mcap = float(data.get("total_market_cap", {}).get("usd", 0) or 0)
        mcap_24h = float(data.get("market_cap_change_percentage_24h_usd", 0) or 0)
    except Exception as e:
        rep.note = f"coingecko failed: {type(e).__name__}"
        return rep

    rep.dominance = dom
    rep.total_mcap = mcap
    rep.mcap_delta_pct = mcap_24h

    # remember snapshots so we can see the direction of dominance
    hist = state.setdefault("dom_history", [])
    now = time.time()
    hist.append({"t": now, "dom": dom, "mcap": mcap})
    state["dom_history"] = [h for h in hist if now - h["t"] < 48 * 3600]

    # --- how much of the world's BTC money moved, in dominance points?
    # 1st choice: our own stored snapshots (6h - 30h old)
    # 2nd choice: estimate it from BTC's 24h move vs total market 24h move
    #             (dominance falls when BTC loses value faster than the market)
    ref = None
    for h in state["dom_history"]:
        age = now - h["t"]
        if 6 * 3600 <= age <= 30 * 3600:
            ref = h
            break
    if ref:
        rep.dominance_delta = round(dom - ref["dom"], 2)
        rep.method = "measured (own history)"
    elif btc_change_24h is not None:
        rep.dominance_delta = round(
            dom * (btc_change_24h - mcap_24h) / 100.0, 2)
        rep.method = "estimated (BTC vs market, 24h)"
    else:
        rep.dominance_delta = 0.0
        rep.method = "unknown"

    if rep.dominance_delta <= -config.DOMINANCE_Trend:
        rep.dominance_trend = "FALLING"
    elif rep.dominance_delta >= config.DOMINANCE_Trend:
        rep.dominance_trend = "RISING"
    else:
        rep.dominance_trend = "FLAT"

    dom_falling = rep.dominance_trend == "FALLING"
    dom_rising = rep.dominance_trend == "RISING"
    cap_up = rep.mcap_delta_pct > config.STABLE_MCAP_PCT

    if dom_falling and cap_up:
        rep.money_flow = "ROTATING_IN"
    elif dom_falling and not cap_up:
        rep.money_flow = "LEAVING"
    elif dom_rising and cap_up:
        rep.money_flow = "BTC_SEASON"
    elif dom_rising and not cap_up:
        rep.money_flow = "PANIC"
    else:  # dominance flat
        rep.money_flow = "BTC_SEASON" if cap_up else "LEAVING"

    rep.note = FLOW_NOTES[rep.money_flow]
    save_state(state)
    return rep


# ------------------------------------------------- 5) FEAR & GREED
@dataclass
class SentimentReport:
    value: int = -1
    label: str = "UNKNOWN"
    yesterday: int = -1
    note: str = ""


def fetch_sentiment():
    rep = SentimentReport()
    try:
        d = _get_json("https://api.alternative.me/fng/", {"limit": 2})
        rows = d.get("data", [])
        if rows:
            rep.value = int(rows[0].get("value", -1))
            rep.label = rows[0].get("value_classification", "UNKNOWN")
        if len(rows) > 1:
            rep.yesterday = int(rows[1].get("value", -1))
    except Exception as e:
        rep.note = f"fear&greed failed: {type(e).__name__}"
        return rep
    if rep.value < 0:
        return rep
    v = rep.value
    if v >= 75:
        rep.note = "EXTREME GREED - crowd is euphoric, be careful with longs"
    elif v >= 55:
        rep.note = "Greed - crowd is buying, trend still friendly to longs"
    elif v <= 25:
        rep.note = "EXTREME FEAR - everyone is scared = classic dip / buy zone"
    elif v <= 45:
        rep.note = "Fear - people are selling, watch for the reversal"
    else:
        rep.note = "Neutral - no strong emotion in the market"
    return rep


# ------------------------------- 6+7+8) BTC DAILY: EMA120, CROSS, BB, RSI
@dataclass
class BtcRegime:
    price: float = 0.0
    ema120: float = 0.0
    above_ema120: bool = False
    cross: str = "NONE"          # GOLDEN | DEATH | NONE
    rsi: float = 50.0
    bb_state: str = "INSIDE"     # BELOW_LOWER | ABOVE_UPPER | INSIDE
    ok: bool = False
    note: str = ""


def analyse_daily(candles, label="BTC"):
    """Same daily checks are used for BTC and for every coin."""
    reg = BtcRegime()
    n = len(candles)
    if n < config.EMA_REGIME + 5:
        reg.note = f"{label}: not enough daily candles ({n})"
        return reg

    c = candles.close
    h, l = candles.high, candles.low
    reg.price = float(c[-1])
    e120 = indicators.ema(c, config.EMA_REGIME)
    reg.ema120 = float(e120[-1])
    reg.above_ema120 = bool(reg.price > reg.ema120)

    # Golden / Death cross: EMA50 vs MA200
    if n >= config.GOLDEN_SLOW + 5:
        fast = indicators.ema(c, config.GOLDEN_FAST)
        slow = indicators.sma(c, config.GOLDEN_SLOW)
        if not np.isnan(slow[-1]):
            if fast[-1] > slow[-1]:
                reg.cross = "GOLDEN"
            else:
                reg.cross = "DEATH"

    r = indicators.rsi(c, config.RSI_PERIOD)
    reg.rsi = float(r[-1]) if not np.isnan(r[-1]) else 50.0

    _, up, low = indicators.bollinger(c, config.BB_PERIOD, config.BB_MULT)
    if not np.isnan(up[-1]):
        if reg.price < low[-1]:
            reg.bb_state = "BELOW_LOWER"     # dip
        elif reg.price > up[-1]:
            reg.bb_state = "ABOVE_UPPER"     # stretched
        else:
            reg.bb_state = "INSIDE"

    reg.ok = True
    bits = [f"{label} {'ABOVE' if reg.above_ema120 else 'BELOW'} EMA120",
            f"{reg.cross} cross", f"RSI {reg.rsi:.0f}", f"BB {reg.bb_state}"]
    reg.note = ", ".join(bits)
    return reg


def fetch_btc_regime(hub):
    reg = BtcRegime()
    try:
        candles = hub.daily_candles("BTC" + config.QUOTE)
    except DataError as e:
        reg.note = f"BTC daily candles failed: {e}"
        return reg
    return analyse_daily(candles, "BTC")


# ------------------------------------------------- combined context
@dataclass
class Context:
    ts: float = 0.0
    news: NewsReport = field(default_factory=NewsReport)
    flow: FlowReport = field(default_factory=FlowReport)
    sentiment: SentimentReport = field(default_factory=SentimentReport)
    btc: BtcRegime = field(default_factory=BtcRegime)
    errors: list = field(default_factory=list)
    # --- multi-market (crypto keeps all the defaults) ---
    cls: str = "crypto"            # crypto | forex | metal | stock
    bench_name: str = "BTC"        # BTC | DXY | SPY (the market layer)
    bench_inverted: bool = False   # benchmark moves opposite to instrument
    session_open: bool = True
    session_note: str = ""


def build_class_context(cls, bench_regime, session_open=True,
                        session_note=""):
    """
    Market layer for forex / metals / stocks.

    The crypto-only checks (news, dominance, money flow, fear&greed) are
    switched off honestly; the daily benchmark (DXY for forex+gold, SPY
    for stocks) takes the place of BTC in the same scoring formula.
    """
    from yf_data import bench_symbol
    return Context(
        ts=time.time(),
        news=NewsReport(
            status="OK",
            note="news filter is crypto-only - not applied to this market"),
        flow=FlowReport(
            money_flow="NEUTRAL",
            note="money-flow check is crypto-only - not applied here"),
        sentiment=SentimentReport(
            value=-1, label="n/a",
            note="fear&greed is crypto-only - not applied here"),
        btc=bench_regime,
        cls=cls,
        bench_name=bench_symbol(cls),
        bench_inverted=False,      # set per instrument by the scanner
        session_open=session_open,
        session_note=session_note,
    )


def build_context(hub, state):
    ctx = Context(ts=time.time())
    ctx.news = fetch_news()
    ctx.sentiment = fetch_sentiment()
    ctx.btc = fetch_btc_regime(hub)
    btc_change = None
    try:
        btc_change = hub.btc_change_24h()
    except Exception:
        btc_change = None
    ctx.flow = fetch_flow(state, btc_change)
    if not ctx.btc.ok:
        ctx.errors.append(ctx.btc.note)
    if ctx.flow.total_mcap <= 0:
        ctx.errors.append(ctx.flow.note)
    save_state(state)
    return ctx


def dashboard(ctx):
    """The paper checklist, printed on screen."""
    f, s, b, n = ctx.flow, ctx.sentiment, ctx.btc, ctx.news
    fg = (f"{s.value} {s.label}" if s.value >= 0 else "no data")
    lines = [
        "=" * 62,
        "  MORNING CHECKLIST  (big frame first, then 2-minute trigger)",
        "-" * 62,
        f" 1. NEWS           : {n.status} - {n.note}",
    ]
    if n.status != "OK" and n.bad_items:
        for t in n.bad_items[:4]:
            lines.append(f"        - {t[:76]}")
    lines += [
        f" 2. BTC DOMINANCE  : {f.dominance:.1f}%  trend {f.dominance_trend}"
        f"  ({f.dominance_delta:+.1f} pts, {f.method})",
        f" 3. TOTAL MCAP     : ${f.total_mcap / 1e12:.2f}T  24h {f.mcap_delta_pct:+.1f}%",
        f" 4. MONEY FLOW     : {f.money_flow}",
        f"                    {f.note}",
        f" 5. FEAR & GREED   : {fg} - {s.note}",
        f" 6. BTC > EMA120?  : {'YES' if b.above_ema120 else 'NO'}"
        f"  (price {b.price:,.0f} vs EMA120 {b.ema120:,.0f})"
        f"  -> {'BULLISH' if b.above_ema120 else 'BEARISH'} regime",
        f" 7. GOLDEN/DEATH   : {b.cross} cross",
        f" 8. DAILY BB + RSI : RSI {b.rsi:.0f}  Bollinger {b.bb_state}",
        "=" * 62,
    ]
    return "\n".join(lines)
