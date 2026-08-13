#!/usr/bin/env python3
"""
Send ONE clearly-labeled test message to the WhatsApp group and map its
idMessage in msgmap.json, so we can exercise the reaction -> star loop without
resending real news. React to it with ANY emoji, then run the
'Poll WhatsApp Reactions' workflow: it should resolve the reaction to the test
article below and star it in the active month's pool.

Cleanup: the test article uses a sentinel URL (see TEST_URL) so it's easy to
find and remove from the pool afterwards.
"""
import os
from datetime import datetime, timezone

from brief import save_msgmap, send_whatsapp

TEST_URL = "https://example.com/fb-brief-reaction-test"

MESSAGE = (
    "🧪 *בדיקת תגובות — F&B Brief*\n"
    "🔗 " + TEST_URL + "\n\n"
    "זו הודעת בדיקה. הגיבי לי עם אימוגי כלשהו (❤️ / 👍 / ⭐ — כל אחד עובד) "
    "כדי שנוודא שהתגובה נקלטת ומסמנת כתבה. אפשר למחוק אותה אחר כך."
)


def main():
    now = datetime.now(timezone.utc)
    mid = send_whatsapp(MESSAGE)
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
    print(f"✓ Test message sent and mapped (idMessage={mid}). React with any emoji.")


if __name__ == "__main__":
    main()
