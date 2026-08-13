#!/usr/bin/env python3
"""
One-time helper: make sure the Green API instance delivers incoming
notifications (incl. reactions) into the queue that poll_reactions.py drains.
Run manually via the 'Green API Setup' workflow. Prints the current settings.
"""
import os
import json
import requests

INSTANCE = os.environ["GREEN_API_INSTANCE"]
TOKEN = os.environ["GREEN_API_TOKEN"]
BASE = f"https://api.green-api.com/waInstance{INSTANCE}"


def main():
    # Enable receiving incoming messages/reactions into the notification queue.
    # (No webhookUrl is set, so notifications queue for receiveNotification.)
    body = {"incomingWebhook": "yes", "stateWebhook": "no", "outgoingWebhook": "no"}
    r = requests.post(f"{BASE}/setSettings/{TOKEN}", json=body, timeout=40)
    print("setSettings:", r.status_code, r.text[:300])

    g = requests.get(f"{BASE}/getSettings/{TOKEN}", timeout=40)
    try:
        s = g.json()
        keep = {k: s.get(k) for k in
                ("incomingWebhook", "outgoingWebhook", "stateWebhook", "webhookUrl")}
        print("current settings:", json.dumps(keep, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        print("getSettings:", g.status_code, g.text[:300])


if __name__ == "__main__":
    main()
