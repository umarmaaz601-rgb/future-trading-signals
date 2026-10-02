"""
Sends the signal to your Telegram and prints it on screen.
If telegram is not configured it still works - it just prints.
"""
import html
import sys
import time

import requests

import config

_GREEN, _RED, _YELLOW, _BOLD, _END = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"


def _money(x):
    if x >= 1e12:
        return f"${x / 1e12:.2f}T"
    if x >= 1e9:
        return f"${x / 1e9:.2f}B"
    if x >= 1e6:
        return f"${x / 1e6:.2f}M"
    return f"${x:,.0f}"


def send_telegram(text):
    if not config.TELEGRAM_ENABLED:
        return False
    token, chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
    if not token or token.startswith("PASTE_") or not chat or chat.startswith("PASTE_"):
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": "true"}
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                return True
            if attempt == 2:
                print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            if attempt == 2:
                print(f"[telegram] failed: {e}")
        time.sleep(2)
    return False


def send_text(text):
    """Try telegram, always print to console too."""
    sent = send_telegram(text)
    return sent


# ----------------------------------------------------------------- SIGNAL
def signal_message(sig):
    """HTML message for Telegram."""
    long_side = sig.side == "LONG"
    arrow = "🟢" if long_side else "🔴"
    e, sl = sig.entry, sig.stop_loss
    tp1, tp2, tp3 = sig.take_profits
    pct = lambda a, b: f"{(a - b) / b * 100:+.2f}%"

    rows = []
    mkt = f' <i>({sig.cls.upper()})</i>' if sig.cls != "crypto" else ""
    rows.append(
        f'{arrow} <b>{sig.side} SIGNAL</b> - <b>{html.escape(sig.symbol)}</b>'
        f'{mkt}   Grade <b>{sig.grade}</b>  (score {sig.score})')
    rows.append("")
    rows.append(f'<b>Entry</b> (market): <code>{e:.6g}</code>')
    rows.append(f'<b>Stop loss</b>: <code>{sl:.6g}</code>  ({pct(sl, e)})')
    rows.append(f'<b>TP1</b>: <code>{tp1:.6g}</code> ({pct(tp1, e)})  '
                f'<b>TP2</b>: <code>{tp2:.6g}</code> ({pct(tp2, e)})')
    rows.append(f'<b>TP3</b>: <code>{tp3:.6g}</code> ({pct(tp3, e)})')
    if getattr(sig, "prob", -1.0) >= 0:
        rows.append(f'<b>P(1:2)</b>: {sig.prob:.0%} to hit TP1 '
                    f'({config.TP1_R:.0f}R) before the stop')
    rows.append("")
    rows.append(f'<b>Leverage</b>: {sig.leverage}x')
    rows.append(f'<b>Position size</b>: {sig.size_usdt:,.0f} USDT  '
                f'(margin {sig.margin:,.1f} USDT)')
    rows.append(f'<b>Risk per trade</b>: {config.RISK_PER_TRADE_PCT}% of balance '
                f'({config.ACCOUNT_BALANCE:,.0f} USDT account)')
    rows.append("")
    rows.append("<b>CHECKLIST</b>")
    for name, ok, detail in sig.checklist:
        mark = "✅" if ok else "⚠️"
        rows.append(f'{mark} <b>{name}</b>: {html.escape(detail)}')
    rows.append("")
    rows.append("<i>Not financial advice. Only risk what you can afford to lose. "
                "Keep funds in your wallet, not on the exchange.</i>")
    return "\n".join(rows)


def print_signal(sig):
    colour = _GREEN if sig.side == "LONG" else _RED
    line = "=" * 62
    print(f"\n{line}")
    print(f"{colour}{_BOLD}  {sig.side}  {sig.symbol}   "
          f"GRADE {sig.grade} (score {sig.score}){_END}")
    print(line)
    print(f"  Entry      : {sig.entry:.6g}")
    print(f"  Stop loss  : {sig.stop_loss:.6g}  "
          f"({(sig.stop_loss - sig.entry) / sig.entry * 100:+.2f}%)")
    for i, tp in enumerate(sig.take_profits, 1):
        print(f"  TP{i}        : {tp:.6g}  "
              f"({(tp - sig.entry) / sig.entry * 100:+.2f}%)")
    if getattr(sig, "prob", -1.0) >= 0:
        print(f"  P(1:2)      : {sig.prob:.0%} chance to hit TP1 "
              f"({config.TP1_R:.0f}R) before the stop")
    print(f"  Leverage   : {sig.leverage}x   size {sig.size_usdt:,.0f} USDT "
          f"(margin {sig.margin:,.1f})")
    for name, ok, detail in sig.checklist:
        print(f"   {'[ok]' if ok else '[!!]'} {name}: {detail}")
    print(line)
    sys.stdout.flush()


def log_signal(sig):
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            tps = ",".join(f"{t:.6g}" for t in sig.take_profits)
            prob = getattr(sig, "prob", -1.0)
            p = f"p={prob:.0%} " if prob >= 0 else ""
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {sig.side} "
                    f"{sig.symbol} grade={sig.grade} score={sig.score} "
                    f"entry={sig.entry:.6g} sl={sig.stop_loss:.6g} "
                    f"tp={tps} lev={sig.leverage}x "
                    f"{p}mkt={getattr(sig, 'cls', 'crypto')}\n")
    except OSError:
        pass
