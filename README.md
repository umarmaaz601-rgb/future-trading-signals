# FUTURE TRADING SIGNAL SYSTEM (Long / Short alerts to Telegram)

This program is **your paper-and-pen checklist, turned into a machine.**
It runs the exact morning routine — news → Bitcoin dominance → total
market cap → money flow → fear & greed → daily EMA120 / Golden Cross /
Bollinger + RSI → 2-minute EMA20/200 trigger — on **all coins**, and
pings your phone on Telegram the moment a coin is worth going
**LONG** or **SHORT** with entry, stop-loss, 3 take-profits and
**50x leverage** sizing.

**Ab sirf crypto nahi — forex, gold/silver aur bade stocks bhi**
(EURUSD, GBPUSD, XAUUSD, TSLA, NVDA, SPY ... ). Same checklist, sirf
market layer badalta hai: crypto ke liye BTC, forex/gold ke liye **DXY
(dollar index)**, stocks ke liye **SPY**, plus trading-session gate
(band bazaar = koi signal nahi).

> ⚠️ This is an education tool, not a financial advisor. Futures trading
> can lose your whole balance. Never leave money sitting on an exchange —
> keep it in your own wallet.

---

## 1. What it checks (the checklist)

| # | Check | Where the data comes from | Why it matters |
|---|-------|---------------------------|----------------|
| 1 | **News** (last 12 hours) | Google News RSS (free, no key) | Bad news (hack, ban, collapse, arrest) = **HALT, no trading** |
| 2 | **Bitcoin dominance** | CoinGecko | Dominance falling = money leaving BTC → altcoins pump |
| 3 | **Total crypto market cap** | CoinGecko | Is world money staying inside crypto, or leaving? |
| 4 | **Money flow** (2+3 together) | computed | `ROTATING_IN` / `BTC_SEASON` / `LEAVING` / `PANIC` |
| 5 | **Fear & Greed index** | alternative.me | Extreme fear = dip buy zone, extreme greed = top risk |
| 6 | **BTC above EMA120?** (daily) | Binance / OKX candles | Whole market follows Bitcoin. Below = bearish trend |
| 7 | **Golden / Death cross** (EMA50 vs MA200, daily) | Binance / OKX | Long-term direction |
| 8 | **Bollinger + RSI** (daily) | computed | Below lower band + RSI < 30 = dip. Above upper + RSI > 70 = stretched |
| 9 | **2-minute EMA20 × EMA200 cross** | built from 1-minute candles | THE trigger that says "enter now" |

### The three layers a signal must survive

```
LAYER 1 - WHOLE MARKET     news clean?  money coming or going?  BTC > EMA120?
LAYER 2 - THE COIN         coin above its own EMA120?  daily dip or top zone?
LAYER 3 - THE TRIGGER      2-minute EMA20 crossed EMA200  ->  LONG / SHORT
```

Each agreeing check adds points. Grade:

| Grade | Score (crypto) | Score (forex/gold/stocks) | Meaning |
|-------|----------------|---------------------------|---------|
| **A+** | 8+ | 6+ | Everything agrees — strongest signal |
| **A** | 6–7 | 5+ | Almost everything agrees |
| **B** | 4–5 | 4 | Minimum grade sent by default |
| C | 3 or less | 3 or less | **Sent only when you pick C** in Settings (`min_grade = "C"`) — max signals |

### ⭐ STRONG setups only (Settings tick-box — recommended)

Agar 1:1 signals aksar SL kha rahe hon to **Settings → "STRONG setups only"**
tick karein. Tab ek signal **sirf tab** jaata jab **HAR checklist item agree
kare** (sirf score points nahi):

1. News = **HALT nahi** (WARNING chalta hai — sirf HALT blocks)
2. Daily cross **side ke khilaf nahi** (DEATH blocks longs / GOLDEN blocks shorts)
3. Coin ka **apna daily trend agree** (long = EMA120 upar, short = neeche)
4. **Daily stretched nahi** — long sirf tab jab daily RSI ≤ **60** ho aur BB
   upper band par na ho; short sirf tab jab RSI ≥ **40** ho aur BB lower
   band par na ho → **kabhi chase nahi**
5. Cross **fresh** (≤ 3 2-minute candles = 6 minute)
6. Grade **A ya A+**

Result: signals **kam**, lekin sirf high-conviction setups. Watchlist
bhi wahi reason dikhata hai (`strong: daily too hot to buy ...`) taake pata
chale signal kyun nahi aaya.

*(Non-crypto has no dominance / money-flow / fear&greed checks, so its
rungs are 2 points lower — same "how much agrees" meaning.)*

### 1:2 probability filter (sirf trades jo 1:2 ya zyada de sakte hain)

Har signal **TP1 = 2R** (risk ka 2 guna) par pehla target deta hai — matlab
minimum reward:hamesha **1:2** (TP2 = 3R, TP3 = 5R runner).

Aur usse pehle ek **probability gate**: system pichle **60 two-minute
candles ko replay** karke napaata hai ke price ne entry se **2R tak SL se
pehle** pohancha kitni baar. Agar yeh measured probability `PROB_MIN`
(config.py, default **35%**) se kam ho to **signal hi nahi banta** —
watchlist/status mein reason dikhta hai:

```
1:2 probability 31% < 35% (needs 2R before SL)
```

- 1:2 trade ka breakeven = **33%** — 35%+ matlab positive edge fees se pehle
- Checklist mein row: `✅ 1:2 probability: 44% to hit TP1 (2R) before SL - need ≥35%`
- Telegram/message mein `P(1:2): 44%`, signals.log mein `p=44%`
- Stricter chahiye? `config.py → PROB_MIN = 0.50` (0.60 = bohot strict)
- `_winrate.py` report P12 column + "P(1:2) >= 35%" summary dikhata hai —
  waqt ke saath khud check karein ke probability high wale signals jeet rahe ya nahi

### Hard blocks (no signal at all)

- 🔴 News status = **HALT** (critical headlines in the last 12h)
- 🔴 Money flow = `LEAVING` or `PANIC` → **longs are blocked**
- 🔴 Money flow = `ROTATING_IN` (money entering alts) → **shorts are blocked**
- 🔴 BTC below EMA120 with money not rotating in → **longs are blocked**
- 🔴 Same coin + same side traded less than 30 minutes ago (cooldown)
- 🔴 Forex / gold / stocks **session closed** (weekend, 21–22 UTC rollover,
  or outside 09:30–16:00 New York) → nothing fires from that market

### Multi-market (forex / gold / stocks) — kaise kaam karta hai

| Market | Instruments | Market layer (Layer 1) | Session gate |
|--------|-------------|------------------------|--------------|
| Crypto | all USDT pairs ≥ $5M vol | BTC (dominance, flow, fear&greed) | 24/7 |
| Forex | 7 majors (EURUSD ... NZDUSD) | **DXY** dollar index (sign flips for USDJPY/USDCAD/USDCHF) | Sun 21:00 → Fri 21:00 UTC, off 21–22 UTC |
| Gold/Silver | XAUUSD, XAGUSD (CME futures) | **DXY** (gold vs dollar) | same as forex |
| Stocks | 20 liquid names + SPY/QQQ | **SPY** index | Mon–Fri 09:30–16:00 ET |

Data comes from **Yahoo Finance** (free, `yfinance` package, cached 75s/6h).
The 2-minute trigger chart is built the same way — from Yahoo's 1-minute
bars. Choose what to watch with the **market:** dropdown in the app
toolbar (ALL / CRYPTO / FOREX / GOLD / STOCKS). Toggle the groups in
`config.py` (`ENABLE_FOREX`, `ENABLE_METAL`, `ENABLE_STOCKS`).

---

## 2. Install (do this once)

### Step 1 — Install Python
Download from https://www.python.org/downloads/ → run installer →
**tick "Add python.exe to PATH"** → Install.

### Step 2 — Put this folder anywhere
Example: `C:\trading-signal\`

### Step 3 — Open a command prompt in that folder and install 3 packages

```
pip install -r requirements.txt
```

### Step 4 — Make your Telegram bot (2 minutes)

1. In Telegram talk to **@BotFather** → send `/newbot` → follow it →
   copy the **token** (looks like `123456789:AAH...`).
2. Talk to **@userinfobot** (or open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   after sending your bot one message) → copy your **chat id** (a number).
3. Open `config.py` and paste both:

```python
TELEGRAM_BOT_TOKEN = "123456789:AAH..."
TELEGRAM_CHAT_ID   = "987654321"
```

### Step 5 — Set your money settings in `config.py`

```python
ACCOUNT_BALANCE = 1000      # your USDT balance (for position sizing)
MAX_LEVERAGE    = 50        # your courage leverage
RISK_PER_TRADE_PCT = 1.0    # % of balance you risk per trade
MAX_COINS       = 0         # 0 = ALL coins (with >= $5M daily volume)
MIN_GRADE       = "B"       # "A+" for only the strongest signals
```

### Step 6 — Test

```
python test_system.py            # self-test (offline part needs no internet)
python scanner.py --test-telegram
python _diag.py                  # FULL market opportunity report (all coins)
python _levels.py                # entry/stop/TP levels for top candidates
python _yf_live.py               # forex/gold/stocks data + session gates
```

If both tests pass → you're live. `_diag.py` answers "which coin has an
opportunity right now" on demand - it checks every coin, shows fresh
triggers, top scores per side and exactly why the market is quiet.

---

## 3. Running it

### 🖥️ Desktop App (recommended — 24/7, all signals on one screen)

| What you want | How |
|---------------|-----|
| **Desktop app** | double-click **`run_app.bat`** (or `python app.py`) |
| App self-check | `python app.py --smoke` |

**24/7 mode — built in:**
- **Auto-starts** the moment the window opens (⚙ SETTINGS can turn this off)
- **Checks for work every 1 second** (`TICK_EVERY_SEC`)
- **Parallel scanning**: 5 workers pass over the **whole market in ~12 seconds**
  (measured: 84 coins in 12.3s — sequential would take ~100s)
- New full scan every **~17 seconds** (12s scan + 5s pause, both adjustable)
- **Keeps your PC awake** while scanning so Windows never sleeps on you
- Survives network errors: auto-retries, auto-switches Binance ⇄ OKX

> ⚠️ Honest note: "every second" means the app *checks* every second and
> scans the whole market as fast as the exchanges legally allow. Any faster
> and Binance rate-limits/bans the connection — the 12-second full pass is
> the safe maximum. Since 2-minute candles only change every 2 minutes,
> nothing is ever missed.

The window shows everything at once:

```
┌──────────────────────────────────────────────────────────────────────┐
│ 📡 FUTURE TRADING SIGNALS   LONG/SHORT • 24/7 • 50x   ● RUNNING 23:41:07│
├──────────────────────────────────────────────────────────────────────┤
│ [▶START] [■STOP] [⟳SCAN NOW] [✈TELEGRAM] [⚙SETTINGS] 🔊   LONG 0 SHORT 0│
├──────────────────────────────────────────────────────────────────────┤
│  MONEY LEAVING THE MARKET -> SHORTS ONLY, BE CAREFUL   (banner)      │
├───────────┬──────────────┬──────────────┬───────────┬────────────────┤
│ MONEY FLOW│ SIGNALS TODAY│ FEAR & GREED │ BTC TREND │ LAST SIGNAL    │
│ PANIC      │ 0            │ 74 GREED     │ BULLISH   │ —              │
├────────────┴──────────────┴──────────────┴───────────┴────────────────┤
│ 📋 MORNING CHECKLIST (8 checks, coloured)  │ 📰 ACTIVITY LOG          │
├────────────────────────────────────────────┴──────────────────────────┤
│ 🟢 LONG SIGNALS  0  [filter___][✕]  │ 🔴 SHORT SIGNALS 0  [filter][✕] │
│ COIN GRADE ENTRY STOP TP1..3 LEV TIME│ (sortable columns - click header)│
├──────────────────────────────────────────────────────────────────────┤
│ 🔎 DETAIL: entry, stop, TP1-3, size, margin, ✅/⚠ checklist          │
├──────────────────────────────────────────────────────────────────────┤
│ binance • 5 workers • tick 1s • min grade A+   next scan in 7s [████░] │
└──────────────────────────────────────────────────────────────────────┘
```

- **Sort** — click any column header (COIN, GRADE, ENTRY, STOP, TP1… TIME)
- **Filter** — type part of a coin name to narrow the table
- **Right-click a row** — copy signal text / open chart in TradingView / clear table
- **👀 WATCHLIST (right of the detail pane)** — "READY & WAITING": every coin
  whose score is worth watching, with its side, score, grade-if-it-fires and
  status (green = will pass the rules on the next cross, amber = needs more
  alignment, grey = blocked by the market rules). It refreshes every scan and
  **fires a real signal by itself the moment a 2-minute cross + rules match** —
  nothing to click.
- **🟢 Sound alert** every new signal (toggle in the toolbar)
- **KPI cards** — money flow, signals today, fear & greed, BTC trend, last signal
- **Progress bar** — watch each market pass sweep the whole coin list
- **⚙ SETTINGS** — balance, leverage, risk %, min grade, coins, scan pause,
  auto-start, keep-PC-awake (saved automatically, remembered next time)
- **History** — old signals from `signals.log` load automatically (grey rows)
- Telegram still sends every signal to your phone at the same time

### 🖥️ Command line

| What you want | Command |
|---------------|---------|
| Run all day (8–9 hour session) | `python scanner.py`  (or double-click **run.bat**) |
| One single scan, then exit | `python scanner.py --once` |
| Send a test Telegram message | `python scanner.py --test-telegram` |
| Force OKX data / Binance data | `python scanner.py --provider okx` |
| Scan only the top 40 coins | `python scanner.py --coins 40` |
| Change account balance for this run | `python scanner.py --balance 5000` |
| Only A+ signals | `python scanner.py --min-grade "A+"` |

**Leave it open while you trade.** It prints/refreshes the checklist every
5 minutes and scans every coin every 60 seconds.

Files it creates:
- `signals.log` — every signal ever sent (review your trades later)
- `state.json` — history of dominance snapshots + cooldowns (do not delete, it learns your market)
- `app_settings.json` — the values you saved in ⚙ SETTINGS

---

## 3b. 24/7 cloud (GitHub Actions) + mobile

Repo: **https://github.com/umarmaaz601-rgb/future-trading-signals**

| Kya | Kaise |
|-----|-------|
| **24/7 scanner** | `.github/workflows/scan.yml` — har 5 minute GitHub ke servers par pura scan + Telegram alerts (PC band ho to bhi chalta hai) |
| **Mobile dashboard** | https://umarmaaz601-rgb.github.io/future-trading-signals/ — har scan (5 min) ke baad update; phone browser mein kholo, menu se **Add to Home Screen** = app icon |
| **Android APK (built-in notifications)** | Actions → **build mobile APK** → run → `apk-latest` release se `FutureSignals.apk` download karke phone par install karo. **v1.1:** app har 90 second dashboard check karta hai aur har naye signal par **phone notification** deta hai (install ke baad *Allow notifications* + *Allow battery* zaroor dabayein, app ko background mein chhorein) |
| **Push alerts on phone (backup)** | Telegram bot (section 2) — app band/swipe ho tab bhi alerts bhejta hai |

**Cloud Telegram setup** (ek baar): repo → **Settings → Secrets and variables
→ Actions → New repository secret**:
- `TELEGRAM_BOT_TOKEN` = aapka token
- `TELEGRAM_CHAT_ID` = aapka chat id

(phir `python setup_telegram.py <TOKEN>` locally bhi chalayein taake desktop
app bhi bheje.)

**Notes:**
- Repo **public** rakho — private repo mein Actions ka free quota 2000
  min/month hai jo 5-minute scans ka 24/7 nahi nibha sakta.
- GitHub schedule thoda late ho sakta hai (5–10 min); desktop app sabse
  fast hai — dono saath chalte hain, cooldown `state.json` cache se
  cloud runs ke beech share hota hai (duplicate alerts nahi).
- 60 din tak repo mein koi activity nahi ho to GitHub scheduled workflows
  band kar deta hai — mahine mein ek baar koi commit kar dein.

---

## 4. How to read a signal on your phone

```
🟢 LONG SIGNAL - SOLUSDT   Grade A+  (score 9)

Entry (market): 142.35
Stop loss:      141.20  (-0.81%)
TP1: 143.50 (+0.81%)   TP2: 144.65 (+1.62%)
TP3: 145.80 (+2.42%)

Leverage: 50x
Position size: 2500 USDT (margin 50 USDT)
Risk per trade: 1% of balance (10 USDT)

CHECKLIST
✅ News: OK - news clean
✅ Money flow: ROTATING_IN (dominance falling, cap stable)
✅ BTC regime: above EMA120 - GOLDEN cross
✅ Fear & Greed: 20 EXTREME FEAR
✅ Coin daily EMA120: above EMA120, RSI 41
✅ Daily dip/top: Bollinger BELOW_LOWER
✅ 2m trigger: EMA20 x EMA200 cross 2 candle(s) ago
```

- **Entry** = market order, go immediately (the trigger only lives a few minutes).
- **Stop loss** = set it as soon as the position opens. Never move it further.
- **TP1/TP2/TP3** = close part of the position at each level (e.g. 40 / 30 / 30 %).
  Levels = **2R / 3R / 5R** of the risk — TP1 par hi 1:2 mil jaata hai.
- **Margin** = how much of your balance to put in. It is already calculated so
  that if the stop-loss hits you lose only ~1% of your balance — **even at 50x**.
- ⚠️ rows mean that check disagreed. Fewer ✅ = weaker signal (grade shows it).

---

## 5. Morning routine (still do this yourself)

The machine does the numbers, but **you** are still the trader:

1. **Wake up → read the news** (Google / Yahoo). Machine says `HALT`? Believe it.
2. **Check the dashboard lines 2–4** — is money coming in or going out?
3. **Open TradingView, look at monthly/weekly first**, then daily EMA120 on BTC.
4. Only then look at the signals the program sends.
5. **Choppy, mixed day?** The program will stay quiet — that is it protecting you.
   "Market is crashing, tell me a scalp trade" is how accounts die.

### Quick Roman Urdu

- Pehle khud khabrein parho, phir scanner ka checklist dekho.
- Money flow `ROTATING_IN` ho to altcoins pump karengi — long ki tarafi socho.
- Money flow `LEAVING`/`PANIC` ho to paise bahar ja rahe hain — long mat lo.
- BTC daily ke EMA120 ke neeche ho to market bearish hai.
- Signal aaye to turant entry, stop-loss zaroor lagao, phir TP1/2/3 par profit nikaalte jao.
- Paisa exchange par mat chhodo — wallet mein rakho.

---

## 6. Troubleshooting

| Problem | Fix |
|---------|-----|
| App closed / crashed with no message | Look in **`app_crash.log`** and **`app_console.log`** (same folder) — everything is written there, even with no black console window. |
| Black console window got closed, app died | Use **`run_app.bat`** now — it launches with `pythonw.exe` (no console at all). Never close the black window if you launch with `python app.py`. |
| `Telegram test: FAILED` | Token/chat id wrong, or you never messaged your bot first. Send any message to your bot, then re-check the id. |
| `could not read any news feed` | Internet/firewall issue. The scanner still runs but news = WARNING (trades are extra careful). |
| `binance -> HTTP 418/429` | Rate limited — it auto-switches to OKX, or just wait 1 minute. |
| `okx -> ConnectionReset` | OKX blocked by your network — leave `DATA_PROVIDER = "auto"` so Binance is used. |
| Money flow says `FLAT`/weak | Normal for the first hours: after 6+ hours it switches from *estimated* to *measured* dominance history. |
| No signals for a long time | Check two things: **Settings → minimum grade** (C = most signals, A+ = almost none) and the **👀 WATCHLIST** panel — it shows every coin's score, why it is blocked and that it will auto-fire when a cross arrives. |
| Forex / gold / stocks missing | Their market is closed (weekend, 21–22 UTC rollover, or outside 09:30–16:00 ET). The **market:** dropdown set to ALL shows everything that is open. |
| Yahoo data errors for stocks | Yahoo sometimes rate-limits: a symbol is paused 30 minutes automatically and the rest keep scanning. |
| Want only the strongest | Settings → minimum grade `A`, or `MIN_GRADE = "A"` in `config.py`. |

---

## 7. File map

```
config.py        all settings (coins, leverage, balance, thresholds, markets)
app.py           DESKTOP APP - all long/short signals on one screen  ← start here
scanner.py       the command-line loop (same engine as the app)
indicators.py    EMA / RSI / Bollinger / cross maths (TradingView-identical)
market_data.py   candles + coin list from Binance and OKX (auto failover)
yf_data.py       forex / gold / stocks candles from Yahoo + session gates
context.py       the checklist: news, dominance, market cap, fear&greed, BTC regime
strategy.py      3 layers -> LONG/SHORT, grade, stop-loss, position size
notifier.py      Telegram + console formatting
setup_telegram.py one-shot bot setup (token -> chat id -> test message)
test_system.py   self-test
run_app.bat      double-click = desktop app
run.bat          double-click = command line scanner
```
