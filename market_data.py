"""
Market data: candle prices (klines) + coin universe (all USDT pairs).
Works with Binance and OKX. If one is blocked/unavailable it falls
back to the other automatically (DATA_PROVIDER = "auto").
"""
import time
from dataclasses import dataclass

import numpy as np
import requests

import config


class DataError(Exception):
    pass


@dataclass
class OHLCV:
    ts: np.ndarray      # open time, ms
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __len__(self):
        return int(self.close.size)


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (futures-signal-system)"})
    return s


class _ThreadSessions:
    """`s = self._sess()` returns this thread's own requests.Session.

    Sessions are not thread-safe and the scanner uses SCAN_WORKERS
    parallel threads, so every thread gets its own session.
    """

    def __init__(self):
        import threading
        self._local = threading.local()

    def __call__(self):
        if not hasattr(self._local, "session"):
            self._local.session = _session()
        return self._local.session


# ----------------------------------------------------------------- 2-MIN BARS
# Neither Binance nor OKX offer a native 2-minute bar, so we build the
# 2-minute chart from 1-minute candles (this is the trigger chart).
def aggregate_to_2m(data: "OHLCV", limit: int) -> "OHLCV":
    """Merge 1-minute candles into confirmed 2-minute candles."""
    buckets, order = {}, []
    for i in range(len(data)):
        key = int(data.ts[i]) // 120000          # 2-minute bucket
        if key not in buckets:
            buckets[key] = [float(data.open[i]), float(data.high[i]),
                            float(data.low[i]), float(data.close[i]),
                            float(data.volume[i])]
            order.append(key)
        else:
            b = buckets[key]
            b[1] = max(b[1], float(data.high[i]))
            b[2] = min(b[2], float(data.low[i]))
            b[3] = float(data.close[i])
            b[4] += float(data.volume[i])
    # only keep candles whose 2 minutes have fully passed
    now_ms = time.time() * 1000.0
    order = [k for k in order if (k + 2) * 60000 <= now_ms][-limit:]
    if not order:
        raise DataError("no confirmed 2-minute candles")
    n = len(order)
    return OHLCV(
        ts=np.asarray([k * 120000 for k in order], dtype=float),
        open=np.asarray([buckets[k][0] for k in order]),
        high=np.asarray([buckets[k][1] for k in order]),
        low=np.asarray([buckets[k][2] for k in order]),
        close=np.asarray([buckets[k][3] for k in order]),
        volume=np.asarray([buckets[k][4] for k in order]),
    )


# ----------------------------------------------------------------- BINANCE
class BinanceSource:
    name = "binance"

    def __init__(self):
        self._sess = _ThreadSessions()     # one session per thread

    def _get(self, path, params):
        errors = []
        for host in config.BINANCE_HOSTS:
            sess = self._sess()
            for attempt in range(3):
                try:
                    r = sess.get(host + path, params=params,
                                 timeout=config.HTTP_TIMEOUT)
                    if r.status_code in (418, 429):
                        # rate limited -> back off and retry this host
                        if attempt < 2:
                            time.sleep(1.5 * (attempt + 1))
                            continue
                        errors.append(f"{host} -> rate limited")
                        break
                    if r.status_code == 200:
                        return r.json()
                    errors.append(f"{host} -> HTTP {r.status_code}")
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(0.5)
                        continue
                    errors.append(f"{host} -> {type(e).__name__}")
                    break
        raise DataError("binance: " + "; ".join(errors))

    def klines(self, symbol, interval, limit):
        if interval == "2m":
            # no native 2m bar -> build it from 1-minute candles
            need = min(1000, int(limit) * 2 + 6)
            raw = self._get("/api/v3/klines",
                            {"symbol": symbol, "interval": "1m", "limit": need})
            if not raw:
                raise DataError(f"binance: no 1m candles for {symbol}")
            arr = np.asarray(raw, dtype=float)
            one_min = OHLCV(ts=arr[:, 0], open=arr[:, 1], high=arr[:, 2],
                            low=arr[:, 3], close=arr[:, 4], volume=arr[:, 5])
            # drop the still-open minute
            if len(one_min) > 1:
                one_min = OHLCV(ts=one_min.ts[:-1], open=one_min.open[:-1],
                                high=one_min.high[:-1], low=one_min.low[:-1],
                                close=one_min.close[:-1], volume=one_min.volume[:-1])
            time.sleep(config.REQUEST_PAUSE_SEC)
            return aggregate_to_2m(one_min, limit)

        raw = self._get("/api/v3/klines",
                        {"symbol": symbol, "interval": interval, "limit": int(limit)})
        if not raw:
            raise DataError(f"binance: no candles for {symbol}")
        arr = np.asarray(raw, dtype=float)
        return OHLCV(
            ts=arr[:, 0],
            open=arr[:, 1],
            high=arr[:, 2],
            low=arr[:, 3],
            close=arr[:, 4],
            volume=arr[:, 5],
        )

    def universe(self):
        """All USDT pairs with enough 24h volume, sorted by volume (best first)."""
        raw = self._get("/api/v3/ticker/24hr", {})
        rows = []
        for d in raw:
            sym = d.get("symbol", "")
            if not sym.endswith(config.QUOTE):
                continue
            base = sym[:-len(config.QUOTE)]
            if base in config.EXCLUDE_BASES:
                continue
            try:
                qv = float(d.get("quoteVolume", 0))
            except (TypeError, ValueError):
                continue
            if qv >= config.MIN_QUOTE_VOLUME_24H:
                rows.append((sym, qv))
        rows.sort(key=lambda x: -x[1])
        if config.MAX_COINS:
            rows = rows[:config.MAX_COINS]
        return [s for s, _ in rows]

    def btc_change_24h(self):
        d = self._get("/api/v3/ticker/24hr", {"symbol": "BTC" + config.QUOTE})
        return float(d["priceChangePercent"])


# ----------------------------------------------------------------- OKX
class OkxSource:
    name = "okx"
    BAR = {"1d": "1D", "1D": "1D", "1h": "1H", "4h": "4H"}

    def __init__(self):
        self._sess = _ThreadSessions()     # one session per thread

    def _get(self, path, params):
        sess = self._sess()
        last_err = None
        for attempt in range(3):
            try:
                r = sess.get(config.OKX_HOST + path, params=params,
                             timeout=config.HTTP_TIMEOUT)
            except Exception as e:
                last_err = f"okx -> {type(e).__name__}: {e}"
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code in (429, 418):
                last_err = "okx -> rate limited"
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise DataError(f"okx -> HTTP {r.status_code}")
            try:
                body = r.json()
            except ValueError:
                raise DataError("okx -> bad json")
            if str(body.get("code")) != "0":
                raise DataError(f"okx -> {body.get('code')} {body.get('msg')}")
            return body.get("data", [])
        raise DataError(last_err or "okx -> failed")

    @staticmethod
    def _rows_to_ohlcv(rows):
        # OKX returns newest first: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
        rows = [r for r in rows if len(r) >= 5]
        if not rows:
            return None
        rows = list(reversed(rows))          # oldest first
        # drop the still-open candle
        if len(rows) > 1 and str(rows[-1][-1]) == "0":
            rows = rows[:-1]
        arr = np.asarray([[float(v) for v in r[:5]] for r in rows], dtype=float)
        return OHLCV(ts=arr[:, 0], open=arr[:, 1], high=arr[:, 2],
                     low=arr[:, 3], close=arr[:, 4],
                     volume=np.zeros(len(arr)))

    def klines(self, symbol, interval, limit):
        inst = f"{symbol[:-len(config.QUOTE)]}-{config.QUOTE}"
        if interval in self.BAR:
            rows = self._get("/api/v5/market/candles",
                             {"instId": inst, "bar": self.BAR[interval],
                              "limit": min(int(limit), 300)})
            data = self._rows_to_ohlcv(rows)
            if data is None:
                raise DataError(f"okx: no candles for {inst}")
            return data

        if interval == "2m":
            # OKX has no 2-minute bar either -> build it from 1-minute candles
            need = int(limit) * 2 + 6
            rows = self._get("/api/v5/market/candles",
                             {"instId": inst, "bar": "1m", "limit": "300"})
            for _ in range(6):                     # page further back if needed
                if len(rows) >= need or not rows:
                    break
                more = self._get("/api/v5/market/history-candles",
                                 {"instId": inst, "bar": "1m",
                                  "after": rows[-1][0], "limit": "100"})
                if not more:
                    break
                rows = rows + more
            rows = [r for r in rows if len(r) >= 5]
            if not rows:
                raise DataError(f"okx: no 1m candles for {inst}")
            rows = list(reversed(rows))          # oldest first
            if str(rows[-1][-1]) == "0":
                rows = rows[:-1]                 # drop still-open minute
            arr = np.asarray([[float(v) for v in r[:5]] for r in rows], dtype=float)
            one_min = OHLCV(ts=arr[:, 0], open=arr[:, 1], high=arr[:, 2],
                            low=arr[:, 3], close=arr[:, 4],
                            volume=np.zeros(len(arr)))
            return aggregate_to_2m(one_min, limit)

        raise DataError(f"okx: unsupported interval {interval}")

    def universe(self):
        rows = self._get("/api/v5/market/tickers", {"instType": "SPOT"})
        out = []
        for d in rows:
            inst = d.get("instId", "")
            if not inst.endswith("-" + config.QUOTE):
                continue
            base = inst.split("-")[0]
            if base in config.EXCLUDE_BASES:
                continue
            try:
                last = float(d.get("last", 0) or 0)
                vol_base = float(d.get("vol24h", 0) or 0)
            except (TypeError, ValueError):
                continue
            quote_vol = vol_base * last
            if quote_vol >= config.MIN_QUOTE_VOLUME_24H:
                out.append((inst.replace("-", ""), quote_vol))
        out.sort(key=lambda x: -x[1])
        if config.MAX_COINS:
            out = out[:config.MAX_COINS]
        return [s for s, _ in out]

    def btc_change_24h(self):
        rows = self._get("/api/v5/market/ticker",
                         {"instId": "BTC-" + config.QUOTE})
        if not rows:
            raise DataError("okx: no BTC ticker")
        last = float(rows[0].get("last", 0) or 0)
        open24 = float(rows[0].get("open24h", 0) or 0)
        if not open24:
            raise DataError("okx: no BTC open24h")
        return (last - open24) / open24 * 100.0


# ----------------------------------------------------------------- MANAGER
class DataHub:
    """
    Holds the coin list, daily-candle cache and picks a working provider.
    """

    def __init__(self):
        self.providers = []
        if config.DATA_PROVIDER in ("auto", "binance"):
            self.providers.append(BinanceSource())
        if config.DATA_PROVIDER in ("auto", "okx"):
            self.providers.append(OkxSource())
        if not self.providers:
            raise DataError("DATA_PROVIDER must be auto, binance or okx")
        self.active = 0
        import threading
        self._lock = threading.Lock()      # provider switching is shared
        self._daily_cache = {}      # symbol -> (fetch_ts, OHLCV)
        self._universe_cache = (0.0, [])

    # -- provider selection ------------------------------------------------
    def _call(self, fn, *args, **kwargs):
        """
        Run fn(provider, ...) on the current provider; if that provider
        fails, switch to the next one. Thread-safe (SCAN_WORKERS run
        these calls in parallel).
        """
        last_err = None
        for _ in range(len(self.providers)):
            with self._lock:
                provider = self.providers[self.active]
            try:
                return fn(provider, *args, **kwargs)
            except DataError as e:
                last_err = e
                with self._lock:
                    # only advance if nobody else already switched
                    if self.providers[self.active] is provider:
                        self.active = (self.active + 1) % len(self.providers)
        raise DataError(str(last_err))

    @property
    def provider_name(self):
        return self.providers[self.active].name

    # -- candles -----------------------------------------------------------
    def trigger_candles(self, symbol):
        data = self._call(self.klines_fallback, symbol,
                          config.TRIGGER_TF, config.TRIGGER_TF_CANDLES)
        time.sleep(config.REQUEST_PAUSE_SEC)
        return data

    def klines_fallback(self, provider, symbol, interval, limit):
        return provider.klines(symbol, interval, limit)

    def btc_change_24h(self):
        """BTC price change of the last 24 hours, in percent."""
        return self._call(lambda p: p.btc_change_24h())

    def daily_candles(self, symbol):
        now = time.time()
        hit = self._daily_cache.get(symbol)
        if hit and now - hit[0] < config.DAILY_CACHE_SEC:
            return hit[1]
        data = self._call(self.klines_fallback, symbol,
                          config.BIG_TF, config.BIG_TF_CANDLES)
        self._daily_cache[symbol] = (now, data)
        time.sleep(config.REQUEST_PAUSE_SEC)
        return data

    # -- coin list ---------------------------------------------------------
    def universe(self, force=False):
        now = time.time()
        if not force and now - self._universe_cache[0] < config.UNIVERSE_REFRESH_SEC:
            return self._universe_cache[1]
        coins = self._call(lambda p: p.universe())
        if not coins:
            raise DataError("empty coin universe")
        self._universe_cache = (now, coins)
        time.sleep(config.REQUEST_PAUSE_SEC)
        return coins
