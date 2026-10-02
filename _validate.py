"""One-off: which candidate NEW instruments actually have usable Yahoo data?
Run BEFORE adding them to config (drops any dead ticker).

    python _validate.py
"""
import time

import yfinance as yf

FOREX = [
    "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CHFJPY",
    "EURGBP", "EURCHF", "EURAUD", "EURCAD",
    "GBPAUD", "GBPCAD", "AUDCAD", "AUDNZD", "NZDCAD",
    "USDCNH", "USDMXN", "USDNOK", "USDSEK", "USDTRY", "USDZAR", "USDSGD",
]
STOCKS = [
    "GOOG", "ADBE", "ORCL", "CRM", "CSCO", "QCOM", "TXN", "AMAT", "MU",
    "LRCX", "KLAC", "IBM", "UBER", "ABNB", "SNAP", "F", "GM", "BA", "GS",
    "MS", "JPM", "BAC", "WMT", "COST", "KO", "PEP", "XOM", "CVX", "UNH",
    "GILD", "MRK", "PFE", "ABBV", "JNJ", "CAT", "GE", "HON", "DIS", "NKE",
    "SBUX", "TGT", "LCID", "SOFI",
]
COMM = {"XPTUSD": "PL=F", "XPDUSD": "PA=F", "OILUSD": "CL=F",
        "GASUSD": "NG=F"}


def check(sym, ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d",
                         progress=False, auto_adjust=False)
        if df is None or len(df) < 120:
            return f"only {0 if df is None else len(df)} bars"
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def main():
    groups = [(FOREX, lambda s: f"{s}=X"),
              (STOCKS, lambda s: s),
              (list(COMM), COMM.get)]
    for names, tf in groups:
        good, bad = [], []
        for s in names:
            err = check(s, tf(s))
            (bad.append((s, err)) if err else good.append(s))
            time.sleep(0.15)
        print(f"\n== {len(good)} OK / {len(bad)} bad ==")
        print("  OK :", ", ".join(good) or "-")
        for s, err in bad:
            print(f"  BAD: {s} -> {err}")


if __name__ == "__main__":
    main()
