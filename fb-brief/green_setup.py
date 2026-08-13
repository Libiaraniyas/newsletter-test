#!/usr/bin/env python3
"""
Ensure the Green API instance delivers incoming notifications (incl. reactions)
into the queue that poll_reactions.py drains.

Important Green API gotcha: calling setSettings REBOOTS the instance (~1-3 min),
and getSettings returns the STALE (pre-reboot) value until the reboot finishes.
So a setSettings immediately followed by getSettings will wrongly show the old
value. We therefore:
  - MODE=check          -> only read getSettings (the true persisted state).
  - default (set+verify)-> setSettings once, then POLL getSettings until
                           incomingWebhook == "yes" (or a timeout).
Run via the 'Green API Setup' workflow.
"""
import os
import json
import time

import requests

INSTANCE = os.environ["GREEN_API_INSTANCE"]
TOKEN = os.environ["GREEN_API_TOKEN"]
BASE = f"https://api.green-api.com/waInstance{INSTANCE}"
MODE = os.environ.get("MODE", "set").lower()

KEEP = ("incomingWebhook", "outgoingWebhook", "stateWebhook", "webhookUrl")


def get_settings():
    g = requests.get(f"{BASE}/getSettings/{TOKEN}", timeout=40)
    try:
        s = g.json()
        return {k: s.get(k) for k in KEEP}
    except Exception:  # noqa: BLE001
        return {"_error": f"HTTP {g.status_code}: {g.text[:200]}"}


def diag():
    """Print who this instance is (phone + state) and its full webhook settings,
    so we can confirm the GitHub secret points at the RIGHT (paid) instance and
    see exactly which flags are off. Nothing is changed (no reboot)."""
    try:
        w = requests.get(f"{BASE}/getWaSettings/{TOKEN}", timeout=40).json()
        phone = w.get("phone") or w.get("wid") or "?"
        print(f"linked WhatsApp: phone={phone}  state={w.get('stateInstance')}")
    except Exception as e:  # noqa: BLE001
        print("getWaSettings failed:", str(e)[:200])
    try:
        s = requests.get(f"{BASE}/getStateInstance/{TOKEN}", timeout=40).json()
        print("state:", json.dumps(s, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print("getStateInstance failed:", str(e)[:200])
    print("webhook settings:", json.dumps(get_settings(), ensure_ascii=False))


def main():
    if MODE == "check":
        print("check-only — current settings:",
              json.dumps(get_settings(), ensure_ascii=False))
        return
    if MODE == "diag":
        diag()
        return

    # Enable receiving incoming messages/reactions into the notification queue.
    # (No webhookUrl is set, so notifications queue for receiveNotification.)
    body = {"incomingWebhook": "yes", "stateWebhook": "no", "outgoingWebhook": "no"}
    r = requests.post(f"{BASE}/setSettings/{TOKEN}", json=body, timeout=40)
    print("setSettings:", r.status_code, r.text[:300])

    # Poll until the reboot applies the new value (or give up after ~4 min).
    for attempt in range(1, 17):
        time.sleep(15)
        cur = get_settings()
        print(f"  [{attempt:02d}] getSettings -> {json.dumps(cur, ensure_ascii=False)}")
        if cur.get("incomingWebhook") == "yes":
            print("✓ incomingWebhook is now 'yes' — reactions will queue for polling.")
            return
    print("⚠️  incomingWebhook did not flip to 'yes' within the wait window. "
          "The instance may still be rebooting — re-run this workflow with MODE=check "
          "in a couple of minutes to read the true state.")


if __name__ == "__main__":
    main()
