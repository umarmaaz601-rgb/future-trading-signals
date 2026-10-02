"""
Technical indicators - same maths as TradingView.
All functions take / return numpy arrays.
"""
import numpy as np


def ema(src, period):
    """Exponential Moving Average (same as TradingView EMA)."""
    src = np.asarray(src, dtype=float)
    if src.size == 0:
        return np.array([])
    alpha = 2.0 / (period + 1.0)
    out = np.empty(src.size, dtype=float)
    out[0] = src[0]
    for i in range(1, src.size):
        out[i] = alpha * src[i] + (1.0 - alpha) * out[i - 1]
    return out


def sma(src, period):
    """Simple Moving Average. First period-1 values are NaN."""
    src = np.asarray(src, dtype=float)
    n = src.size
    if n < period:
        return np.full(n, np.nan)
    cumsum = np.cumsum(np.insert(src, 0, 0.0))
    out = np.full(n, np.nan)
    out[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return out


def rolling_std(src, period):
    """Population standard deviation (ddof=0, same as TradingView)."""
    src = np.asarray(src, dtype=float)
    n = src.size
    if n < period:
        return np.full(n, np.nan)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        out[i] = np.std(src[i - period + 1:i + 1], ddof=0)
    return out


def rsi(src, period=14):
    """Wilder RSI (same as TradingView RSI)."""
    src = np.asarray(src, dtype=float)
    n = src.size
    if n < period + 1:
        return np.full(n, np.nan)
    delta = np.diff(src)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    # Wilder smoothing seeded with simple average
    avg_gain = np.empty(n - 1)
    avg_loss = np.empty(n - 1)
    avg_gain[period - 1] = gain[:period].mean()
    avg_loss[period - 1] = loss[:period].mean()
    for i in range(period, n - 1):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    avg_gain[:period - 1] = np.nan
    avg_loss[:period - 1] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi_vals = 100.0 - 100.0 / (1.0 + rs)
    # loss = 0 (straight up market) -> RSI 100, gain = 0 -> RSI 0
    rsi_vals = np.where(np.isinf(rs) | (avg_loss == 0), 100.0, rsi_vals)
    rsi_vals = np.where((avg_gain == 0) & (avg_loss != 0), 0.0, rsi_vals)
    out = np.full(n, np.nan)
    out[1:] = rsi_vals
    return out


def bollinger(src, period=20, mult=2.0):
    """Returns (middle, upper, lower)."""
    mid = sma(src, period)
    sd = rolling_std(src, period)
    upper = mid + mult * sd
    lower = mid - mult * sd
    return mid, upper, lower


def atr(high, low, close, period=14):
    """Average True Range, Wilder smoothed."""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = close.size
    if n < period + 1:
        return np.full(n, np.nan)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    prev_c = close[:-1]
    tr[1:] = np.maximum(high[1:] - low[1:],
                        np.maximum(np.abs(high[1:] - prev_c),
                                   np.abs(low[1:] - prev_c)))
    out = np.full(n, np.nan)
    out[period - 1] = tr[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def latest_cross(fast, slow):
    """
    Returns (side, index) of the MOST RECENT cross between fast and slow.
    side = 'LONG'  when fast crossed ABOVE slow
    side = 'SHORT' when fast crossed BELOW slow
    side = None if no cross found.
    """
    n = min(len(fast), len(slow))
    if n < 3:
        return None, -1
    f = fast[:n]
    s = slow[:n]
    for i in range(n - 1, 0, -1):
        if np.isnan(f[i]) or np.isnan(s[i]) or np.isnan(f[i - 1]) or np.isnan(s[i - 1]):
            continue
        if f[i - 1] <= s[i - 1] and f[i] > s[i]:
            return "LONG", i
        if f[i - 1] >= s[i - 1] and f[i] < s[i]:
            return "SHORT", i
    return None, -1
