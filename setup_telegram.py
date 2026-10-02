"""
TELEGRAM SETUP HELPER  -  one command does everything:

  Step 1  In Telegram, chat with @BotFather -> send /newbot
          -> give it a name -> copy the TOKEN it gives you
  Step 2  Open YOUR new bot and press START (send any message)
  Step 3  Run:
              python setup_telegram.py
          paste the token when asked (or: python setup_telegram.py TOKEN)

  It will: validate the token -> find your chat id automatically ->
  write both into config.py -> send a test message.
"""
import re
import sys

import requests

import config

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{25,}$")


def get_token(argv):
    if len(argv) > 1 and argv[1]:
        return argv[1].strip()
    try:
        return input("Paste your BOT TOKEN from @BotFather: ").strip()
    except EOFError:
        return ""


def validate(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe",
                         timeout=20)
        data = r.json()
    except Exception as e:
        return None, f"network problem: {e}"
    if not data.get("ok"):
        return None, f"telegram rejected the token: {data.get('description')}"
    return data["result"]["username"], None


def find_chat_id(token):
    """Your chat id appears once you have sent the bot a message."""
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                         timeout=20)
        data = r.json()
    except Exception as e:
        return None, f"network problem: {e}"
    if not data.get("ok"):
        return None, f"telegram said: {data.get('description')}"
    private, other = None, None
    for upd in data.get("result") or []:
        msg = upd.get("message") or upd.get("channel_post") or \
            upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            if chat.get("type") == "private":
                private = str(chat["id"])
                break
            other = str(chat["id"])
    return (private or other), None


def write_config(token, chat_id):
    with open("config.py", "r", encoding="utf-8") as f:
        text = f.read()
    text, n1 = re.subn(
        r'(TELEGRAM_BOT_TOKEN = os\.getenv\("TELEGRAM_BOT_TOKEN", ")[^"]*("\))',
        rf"\g<1>{token}\g<2>", text)
    text, n2 = re.subn(
        r'(TELEGRAM_CHAT_ID = os\.getenv\("TELEGRAM_CHAT_ID", ")[^"]*("\))',
        rf"\g<1>{chat_id}\g<2>", text)
    if n1 != 1 or n2 != 1:
        return False
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(text)
    return True


def send_test(token, chat_id):
    text = ("<b>Signal system connected!</b>\n\n"
            "Assalam-o-Alaikum! Future trading alerts will arrive here:\n"
            "LONG / SHORT signals with entry, stop-loss, TP1-3, leverage "
            "and the full checklist.\n\n"
            "<i>Keep funds in your wallet. Not financial advice.</i>")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": "true"},
            timeout=20)
        return r.status_code == 200, r.text[:160] if r.status_code != 200 else ""
    except Exception as e:
        return False, str(e)


def main():
    token = get_token(sys.argv)
    if not token:
        print("no token given.")
        return 1
    if not TOKEN_RE.match(token):
        print(f"that does not look like a telegram token "
              f"(expected 123456:AA...): {token[:12]}...")
        return 1

    bot_name, err = validate(token)
    if err:
        print(f"FAILED: {err}")
        return 1
    print(f"[ok] token valid - your bot is @{bot_name}")

    chat_id, err = find_chat_id(token)
    if err:
        print(f"FAILED: {err}")
        return 1
    if not chat_id:
        print("chat id not found yet.")
        print("-> open YOUR bot in Telegram and press START "
              "(send it any message), then run this again.")
        return 1
    print(f"[ok] chat id found: {chat_id}")

    if not write_config(token, chat_id):
        print("FAILED: could not write config.py (run this from the "
              "project folder)")
        return 1
    print("[ok] token + chat id saved into config.py")

    ok, detail = send_test(token, chat_id)
    if not ok:
        print(f"test message FAILED: {detail}")
        print("config is saved anyway - press TELEGRAM TEST in the app.")
        return 1
    print("[ok] TEST MESSAGE SENT - check your Telegram now.")
    print("\nDONE. Restart the desktop app and signals will come to your "
          "phone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
