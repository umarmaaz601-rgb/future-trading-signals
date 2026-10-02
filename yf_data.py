"""
YAHOO FINANCE DATA  (forex, gold/silver, stocks)

Free, no API key. Uses the yfinance package. We only need:
  * 1-minute bars  -> aggregated into the same 2-minute trigger chart
  * daily bars      -> EMA120 / golden-death cross / Bollinger / RSI
  * a session gate  -> outside market hours nothing can fire

Every symbol is cached so Yahoo is never hammered (1m: 75s, daily: 6h)
and a symbol that keeps failing is put in a 30-minute time-out.
"""
import datetime as dt
import threading
import time
from zoneinfo import ZoneInfo

import config
from market_data import DataError, aggregate_to_2m


# ------------------------------------------------------------- classes
def asset_class(sym):
    """crypto | forex | metal | stock (crypto stays on Binance)."""
    if sym in config.FOREX_PAIRS:
        return "forex"
    if sym in config.METALS:
        return "metal"
    if sym in config.STOCKS:
        return "stock"
    return "crypto"


def instruments(cls):
    if cls == "forex" and config.ENABLE_FOREX:
        return list(config.FOREX_PAIRS)
    if cls == "metal" and config.ENABLE_METAL:
        return list(config.METALS)
    if cls == "stock" and config.ENABLE_STOCKS:
        return list(config.STOCKS)
    return []


ALL_CLASSES = ("forex", "metal", "stock")


def yahoo_ticker(sym):
    if sym in config.FOREX_PAIRS:
        return f"{sym}=X"
    if sym in config.METALS:
        # Yahoo has no XAUUSD=X spot - use CME futures (same price, ~23h)
        return {"XAUUSD": "GC=F", "XAGUSD": "SI=F", "XPTUSD": "PL=F",
                "XPDUSD": "PA=F", "OILUSD": "CL=F",
                "GASUSD": "NG=F"}.get(sym, f"{sym}=X")
    if sym == "DXY":
        return "DX-Y.NYB"
    return sym                                  # stocks / ETFs


def bench_symbol(cls):
    return (config.FOREX_METAL_BENCH if cls in ("forex", "metal")
            else config.STOCK_BENCH)


def bench_inverted(sym, cls):
    """True when the benchmark moves OPPOSITE to this instrument.

    EURUSD / gold fall when the dollar (DXY) rises -> inverted.
    USDJPY rises with the dollar -> not inverted.
    Stocks follow SPY -> not inverted.
    """
    if cls == "metal":
        return True
    if cls == "forex":
        return not sym.startswith("USD")
    return False


# ------------------------------------------------------------- sessions
def _forex_open(now):
    """FX (and spot gold) window: Sun 21:00 UTC -> Fri 21:00 UTC,
    minus the daily 21:00-22:00 UTC rollover freeze."""
    wd, h = now.weekday(), now.hour + now.minute / 60.0
    if wd == 5:                       # Saturday
        return False
    if wd == 6:                       # Sunday: opens 21 UTC
        return h >= 21
    if wd == 4 and h >= 21:           # Friday close
        return False
    if 21 <= h < 22:                  # daily rollover
        return False
    return True


def _stocks_open(now):
    et = now.astimezone(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return False
    t = et.hour + et.minute / 60.0
    return 9.5 <= t < 16.0            # 09:30 - 16:00 ET, no thin hours


def session_status(cls):
    """(open?, note) for a market class. Crypto never closes."""
    now = dt.datetime.now(dt.timezone.utc)
    if cls == "forex":
        ok = _forex_open(now)
        return ok, "" if ok else "forex closed (reopens Sun/Mon 21:00 UTC)"
    if cls == "metal":
        ok = _forex_open(now)
        return ok, "" if ok else "metals closed (daily 21-22 UTC + weekend)"
    if cls == "stock":
        ok = _stocks_open(now)
        return ok, "" if ok else "US market closed (opens 09:30 ET)"
    return True, ""


# ------------------------------------------------------------- source
def _df_to_ohlcv(df, limit):
    import numpy as np
    if df is None or len(df) == 0:
        raise DataError("yahoo: empty response")
    if getattr(df.columns, "nlevels", 1) > 1:
        df = df.droplevel(-1, axis=1)          # drop the ticker level
    try:
        idx = df.index
        # pandas/yfinance may store the index in s / ms / us / ns units
        unit = getattr(idx, "unit", "ns")
        raw = idx.view("int64")                 # tz-aware = UTC epoch
        if unit == "s":
            ts = raw * 1000
        elif unit == "ms":
            ts = raw
        elif unit == "us":
            ts = raw // 1_000
        else:
            ts = raw // 1_000_000
        ts = ts.astype(np.int64)
        o = df["Open"].to_numpy(np.float64)
        h = df["High"].to_numpy(np.float64)
        l = df["Low"].to_numpy(np.float64)
        c = df["Close"].to_numpy(np.float64)
        v = df["Volume"].to_numpy(np.float64)
    except Exception as e:
        raise DataError(f"yahoo: bad frame ({e})")
    n = len(c)
    if n < 30:
        raise DataError(f"yahoo: only {n} bars")
    keep = min(n, limit)
    from market_data import OHLCV
    return OHLCV(ts=n - keep + ts[-keep:], open=o[-keep:], high=h[-keep:],
                 low=l[-keep:], close=c[-keep:], volume=v[-keep:])


class YfSource:
    name = "yahoo"

    def __init__(self):
        self._m1 = {}          # sym -> (fetch_ts, OHLCV)
        self._day = {}         # sym -> (fetch_ts, OHLCV)
        self._fail = {}        # sym -> (first_fail_ts, misses)
        self._lock = threading.Lock()

    # ---- failure time-out (delisted / broken ticker)
    def _check_fail(self, sym):
        with self._lock:
            entry = self._fail.get(sym)
        if not entry:
            return
        first, misses = entry
        if time.time() - first < config.YF_FAIL_BACKOFF_SEC:
            if misses >= 3:
                raise DataError(f"yahoo: {sym} failing - paused 30 min")
        else:
            with self._lock:
                self._fail.pop(sym, None)

    def _note_fail(self, sym):
        with self._lock:
            first, misses = self._fail.get(sym, (time.time(), 0))
            self._fail[sym] = (first, misses + 1)

    # ---- fetches
    def _download(self, ticker, period, interval):
        import yfinance as yf
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=False, threads=True)
        return df

    def candles_1m(self, sym, limit=500):
        self._check_fail(sym)
        now = time.time()
        with self._lock:
            entry = self._m1.get(sym)
        if entry and now - entry[0] < config.YF_1M_CACHE_SEC:
            return entry[1]
        try:
            df = self._download(yahoo_ticker(sym), "5d", "1m")
            data = _df_to_ohlcv(df, limit)
        except DataError:
            self._note_fail(sym)
            raise
        except Exception as e:
            self._note_fail(sym)
            raise DataError(f"yahoo {sym}: {type(e).__name__}: {e}")
        with self._lock:
            self._m1[sym] = (time.time(), data)
        return data

    def candles_1d(self, sym):
        key = sym
        now = time.time()
        with self._lock:
            entry = self._day.get(key)
        if entry and now - entry[0] < config.YF_DAY_CACHE_SEC:
            return entry[1]
        self._check_fail(key)
        try:
            df = self._download(yahoo_ticker(sym), "2y", "1d")
            data = _df_to_ohlcv(df, 600)
        except DataError:
            self._note_fail(key)
            raise
        except Exception as e:
            self._note_fail(key)
            raise DataError(f"yahoo {sym}: {type(e).__name__}: {e}")
        with self._lock:
            self._day[key] = (time.time(), data)
        return data

    def trigger_2m(self, sym, limit):
        """Same 2-minute trigger chart as crypto (built from 1m bars)."""
        return aggregate_to_2m(self.candles_1m(sym), limit)


# module-level singleton (thread-safe caches; downloads run in parallel)
SOURCE = YfSource()
