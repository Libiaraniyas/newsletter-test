#!/usr/bin/env python3
"""
Send ONE clearly-labeled test message and map its idMessage in msgmap.json so a
later emoji reaction can be resolved to a (test) article.

By default it sends to the WhatsApp group (GREEN_API_CHAT_ID). If TARGET_NUMBER
is set, it sends a 1:1 message to that number instead — used to test whether an
INCOMING reaction from a DIFFERENT person is delivered to the instance (our own
reactions on our own messages would be outgoing, not incoming).
"""
import os
from datetime import datetime, timezone

import requests

from brief import save_msgmap

INSTANCE = os.environ["GREEN_API_INSTANCE"]
TOKEN = os.environ["GREEN_API_TOKEN"]
BASE = f"https://api.green-api.com/waInstance{INSTANCE}"
TARGET_NUMBER = os.environ.get("TARGET_NUMBER", "").strip()
GROUP_CHAT = os.environ.get("GREEN_API_CHAT_ID", "").strip()

TEST_URL = "https://example.com/fb-brief-reaction-test"

MESSAGE = (
    "🧪 *בדיקת תגובות — F&B Brief*\n"
    "🔗 " + TEST_URL + "\n\n"
    "זו הודעת בדיקה. אנא הגיבו לי עם אימוגי כלשהו (❤️ / 👍 / ⭐ — כל אחד עובד) "
    "כדי שנוודא שהתגובה נקלטת. אפשר למחוק אותה אחר כך."
)


def send(chat_id, text):
    r = requests.post(f"{BASE}/sendMessage/{TOKEN}",
                      json={"chatId": chat_id, "message": text}, timeout=60)
    print("sendMessage:", r.status_code, r.text[:300])
    r.raise_for_status()
    try:
        return str(r.json().get("idMessage", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def main():
    if TARGET_NUMBER:
        digits = "".join(ch for ch in TARGET_NUMBER if ch.isdigit())
        chat_id = f"{digits}@c.us"
    else:
        chat_id = GROUP_CHAT
    print("target chatId:", chat_id)
    now = datetime.now(timezone.utc)
    mid = send(chat_id, MESSAGE)
    if not mid:
        print("✗ No idMessage returned — cannot map for the reaction test.")
        raise SystemExit(1)
    save_msgmap({
        mid: {
            "url": TEST_URL,
            "title": "בדיקת תגובות F&B Brief",
            "summary": "הודעת בדיקה לאימות לולאת התגובה→כוכב.",
            "story_key": "reaction-test",
            "category": "market",
            "sent_at": now.isoformat(),
        }
    })
    print(f"✓ Test message sent and mapped (idMessage={mid}, chatId={chat_id}). React with any emoji.")


if __name__ == "__main__":
    main()
