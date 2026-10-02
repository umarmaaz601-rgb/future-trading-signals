"""
================================================================
 ZAKA-STYLE FUTURE TRADING SIGNAL SYSTEM  -  CONFIGURATION
 Edit this file only. Everything else runs by itself.
================================================================
"""

import os

# ----------------------------------------------------------------
# 1) TELEGRAM  (create bot with @BotFather -> get token;
#               send a message to your bot -> get chat id with
#               @userinfobot or https://api.telegram.org/bot<TOKEN>/getUpdates )
# ----------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PASTE_YOUR_CHAT_ID_HERE")
TELEGRAM_ENABLED = True          # False = only print on screen, no telegram

# ----------------------------------------------------------------
# 2) DATA SOURCE  (where candle data comes from)
#    auto   = try Binance, fall back to OKX automatically
#    binance / okx = force one of them
# ----------------------------------------------------------------
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "auto")          # auto | binance | okx
BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
]
OKX_HOST = "https://www.okx.com"
HTTP_TIMEOUT = 15

# ----------------------------------------------------------------
# 3) WHICH COINS TO SCAN  ("all coins")
#    Universe = every USDT pair whose 24h volume is above
#    MIN_QUOTE_VOLUME_24H.  Set MAX_COINS = 0 for no cap.
# ----------------------------------------------------------------
QUOTE = "USDT"
MIN_QUOTE_VOLUME_24H = 5_000_000     # ignore coins with less than $5M daily volume
MAX_COINS = 0                         # 0 = ALL coins that pass the volume filter
# Stablecoins / non-crypto tokens we never trade
EXCLUDE_BASES = {
    # stablecoins
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "PYUSD", "BUSD",
    "USD1", "XUSD", "AEUR", "EUR", "EURI", "USDD", "FRAX", "RLUSD",
    # Binance tokenized stocks (not crypto - their chart has no crypto rhythm)
    "GOOGLB", "NVDAB", "MSTRB", "CRCLB", "SNDKB", "TSLAB", "AAPLB",
    "AMZNB", "MSFTB", "METAB", "COINB", "HOODB", "SPYB", "QQQB",
}

# ----------------------------------------------------------------
# 4) TIME FRAMES  (big frame first, then 2-minute trigger)
# ----------------------------------------------------------------
BIG_TF = "1d"        # daily  -> EMA120, Golden/Death cross, Bollinger, RSI
TRIGGER_TF = "2m"    # 2 min  -> EMA20 / EMA200 entry trigger
BIG_TF_CANDLES = 250 # how many daily candles to load (need > 200 for MA200)
TRIGGER_TF_CANDLES = 240  # 2m candles (built from 1m; need > 200 for EMA200)

# ----------------------------------------------------------------
# 5) LEVERAGE + RISK  (maximum leverage mode)
# ----------------------------------------------------------------
MAX_LEVERAGE = 50            # your "courage leverage"
DEFAULT_LEVERAGE = 50
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000"))  # USDT in your account
RISK_PER_TRADE_PCT = 1.0     # % of balance you can LOSE if stop-loss hits
MAX_MARGIN_PCT = 20.0        # never put more than this % of balance into one trade
MIN_STOP_PCT = 0.10          # stop-loss distance limits (price %)
MAX_STOP_PCT = 0.60          # at 50x, 0.60% = 30% of the margin
TP1_R, TP2_R, TP3_R = 2.0, 3.0, 5.0   # take profits at 2x / 3x / 5x of risk
#                                        # -> TP1 itself is a 1:2 trade

# ----------------------------------------------------------------
# 6c) 1:2 PROBABILITY FILTER  (only trades that can give 1:2 or more)
#     Before a signal is sent we replay the last PROB_LOOKBACK 2-minute
#     candles as starting points and ask: how often did price reach
#     TP1 (= TP1_R x risk) BEFORE the stop loss?  Signals are only sent
#     when that measured probability is at least PROB_MIN.
#     Breakeven for a 1:2 trade is 33% - so 35%+ = positive edge.
# ----------------------------------------------------------------
PROB_MIN = 0.35          # minimum P(hit 2R before SL) to allow a signal
PROB_LOOKBACK = 60       # 2m candles replayed to measure it (needs long
                         # horizons so wide stops still get decided)

# ----------------------------------------------------------------
# 6) STRATEGY THRESHOLDS  (the checklist rules)
# ----------------------------------------------------------------
EMA_REGIME = 120              # daily EMA 120  - is BTC above or below it?
GOLDEN_FAST, GOLDEN_SLOW = 50, 200   # EMA50 vs MA200 golden/death cross
BB_PERIOD, BB_MULT = 20, 2.0
RSI_PERIOD = 14
RSI_OVERSOLD = 30.0           # below Bollinger + RSI under this = dip / buy zone
RSI_OVERBOUGHT = 70.0
TRIGGER_FAST, TRIGGER_SLOW = 20, 200  # 2-minute EMA20 vs EMA200
TRIGGER_MAX_AGE_CANDLES = 5   # cross must be fresher than this many 2m candles

STABLE_MCAP_PCT = -1.0        # total cap change above this = "not falling"
DOMINANCE_Trend = 1.0         # % point move needed to call dominance falling/rising

# Signal quality:  A+ >= 8,  A >= 6,  B >= 4,  else C
# (per market class - see GRADE_CUT in strategy.py)
MIN_GRADE = "B"               # "A+" | "A" | "B" | "C"  (C = max signals)

# ----------------------------------------------------------------
# 6b) STRONG SETUPS ONLY  (recommended if 1:1 signals keep stopping out)
#     When ON a signal must ALSO pass every checklist item - not just
#     score points:  news not HALT (WARNING is allowed)  +  daily cross
#     not against the side  +  the coin's own daily trend agreeing  +
#     daily NOT stretched:  long needs RSI <= STRONG_RSI_LONG and the
#     band not at the upper edge, short needs RSI >= STRONG_RSI_SHORT
#     and the band not at the lower edge (never chase an extended
#     daily)  +  cross fresher than STRONG_MAX_AGE candles  +  grade A.
#     Result: far fewer signals, but only high-conviction setups.
# ----------------------------------------------------------------
STRONG_ONLY = False           # app Settings has the tick-box
STRONG_MAX_AGE = 3            # max 2m-candle age of the cross
STRONG_RSI_LONG = 60          # LONG: daily RSI above this = too hot to buy
STRONG_RSI_SHORT = 40         # SHORT: daily RSI below this = too cold to sell
SIGNAL_COOLDOWN_MIN = 30      # no repeat signal for same coin+side in this time

# ----------------------------------------------------------------
# 7) NEWS FILTER  (first step of the checklist)
#    Source = Google News RSS (fallback Bing News RSS), free, no key.
# ----------------------------------------------------------------
NEWS_QUERY = "bitcoin OR cryptocurrency OR crypto"
NEWS_LOOKBACK_HOURS = 12
NEWS_REFRESH_SEC = 300
# headline with any of these words = negative
NEWS_NEGATIVE_WORDS = [
    "hack", "hacked", "exploit", "stolen", "drained", "ban", "banned",
    "prohibit", "crackdown", "lawsuit", "sue", "sec ", "fraud", "ponzi",
    "rug pull", "collapse", "bankrupt", "bankruptcy", "insolvent",
    "arrest", "arrested", "charged", "prison", "illegal", "ban on",
    "outlaw", "exit scam", "delist", "suspend", "halt", "liquidation",
]
# these words are so bad they STOP all signals by themselves
NEWS_CRITICAL_WORDS = [
    "hack", "stolen", "drained", "bankrupt", "collapse", "ban on bitcoin",
    "outlaw", "exit scam", "insolvent",
]
NEWS_CRITICAL_LIMIT = 2       # this many critical headlines in 12h = HALT
NEWS_NEGATIVE_LIMIT = 5       # this many negative headlines in 12h = WARNING

# ----------------------------------------------------------------
# 8) LOOP TIMING  (24/7 mode)
#    The app checks for work every second. A full pass over ALL
#    coins runs continuously with parallel workers - the fastest
#    that is safe (Binance would rate-limit us any faster).
# ----------------------------------------------------------------
TICK_EVERY_SEC = 1          # the app looks for work every 1 second
SCAN_INTERVAL_SEC = 5       # pause between two full market scans
SCAN_WORKERS = 5            # parallel candle fetchers (big speed boost)
AUTO_START = True           # start scanning the moment the app opens
KEEP_AWAKE = True           # stop Windows from sleeping while scanning
CONTEXT_REFRESH_SEC = 300   # seconds between news/dominance/fear-greed updates
UNIVERSE_REFRESH_SEC = 600  # seconds between coin list refresh
DAILY_CACHE_SEC = 21600     # daily candles only change once per day (6h cache)
REQUEST_PAUSE_SEC = 0.02    # polite pause between requests
STATE_FILE = "state.json"
LOG_FILE = "signals.log"

# Self-test mode (used by test_system.py): scans run instantly, no pacing
UNIT_TEST = False

# ----------------------------------------------------------------
# 9) WATCHLIST (the "ready & waiting" panel in the app)
#    A coin shows up when its best side scores at least this much
#    (a fresh 2-min cross ALWAYS shows, even with a low score).
# ----------------------------------------------------------------
WATCH_MIN_SCORE = 2      # show coins scoring >= this on their best side

# ----------------------------------------------------------------
# 10) MULTI-MARKET  (forex, gold/silver, stocks)  - data from Yahoo
#    Same 3-layer checklist + 2-minute trigger, only the market
#    layer adapts: DXY (dollar index) for forex/metals, SPY for
#    stocks, and a trading-session gate (closed = no signals).
# ----------------------------------------------------------------
ENABLE_FOREX = True
ENABLE_METAL = True           # gold & silver
ENABLE_STOCKS = True

FOREX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
]
# pairs quoted USD-first move WITH the dollar index (no sign flip)
USD_BASE_PAIRS = {"USDJPY", "USDCAD", "USDCHF"}

METALS = ["XAUUSD", "XAGUSD"]

STOCKS = [
    "SPY", "QQQ", "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META",
    "AMD", "NFLX", "COIN", "MSTR", "PLTR", "SMCI", "ARM", "AVGO", "INTC",
    "BABA", "RIVN",
]

FOREX_METAL_BENCH = "DXY"     # dollar index = market layer for forex/gold
STOCK_BENCH = "SPY"           # index = market layer for stocks

# Yahoo cache times (forex/stock 1m bars only change when session is on)
YF_1M_CACHE_SEC = 75         # refresh 1-minute bars at most every 75s
YF_DAY_CACHE_SEC = 21600     # daily bars: 6h
YF_FAIL_BACKOFF_SEC = 1800   # after repeated failures leave a symbol alone
