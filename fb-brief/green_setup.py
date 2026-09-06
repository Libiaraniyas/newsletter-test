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


def hosttest():
    """Compare the generic host vs the instance's DEDICATED host (shown in the
    console as apiUrl, e.g. https://7107.api.greenapi.com) and try to enable
    incomingWebhook on the dedicated host — the generic host may silently no-op."""
    inst = INSTANCE
    prefix = inst[:4]
    hosts = {
        "generic":   f"https://api.green-api.com/waInstance{inst}",
        "dedicated": f"https://{prefix}.api.greenapi.com/waInstance{inst}",
    }
    for name, base in hosts.items():
        try:
            g = requests.get(f"{base}/getSettings/{TOKEN}", timeout=40).json()
            print(f"[{name}] {base}\n    incomingWebhook={g.get('incomingWebhook')!r}")
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] {base}\n    getSettings FAILED: {str(e)[:160]}")

    base = hosts["dedicated"]
    print(f"\n→ setSettings(incomingWebhook=yes) on DEDICATED host {base}")
    try:
        r = requests.post(f"{base}/setSettings/{TOKEN}",
                          json={"incomingWebhook": "yes"}, timeout=40)
        print("  setSettings:", r.status_code, r.text[:200])
    except Exception as e:  # noqa: BLE001
        print("  setSettings FAILED:", str(e)[:200])
        return
    for i in range(1, 13):
        time.sleep(15)
        try:
            g = requests.get(f"{base}/getSettings/{TOKEN}", timeout=40).json()
            cur = g.get("incomingWebhook")
            print(f"  [{i:02d}] dedicated incomingWebhook={cur!r}")
            if cur == "yes":
                print("✓ DEDICATED host worked — the generic host was the problem.")
                return
        except Exception as e:  # noqa: BLE001
            print(f"  [{i:02d}] getSettings err: {str(e)[:120]}")
    print("dedicated-host set did not flip within the wait window.")


def history():
    """Probe whether reactions are readable WITHOUT incomingWebhook, via
    getChatHistory / lastIncomingMessages. Prints raw entries so we can learn
    the reaction shape and rebuild the poller on top of a read that works."""
    chat = os.environ.get("GREEN_API_CHAT_ID", "")
    base = f"https://api.green-api.com/waInstance{INSTANCE}"
    if not chat:
        print("⚠️  GREEN_API_CHAT_ID not set — cannot read chat history.")
        return

    print(f"→ getChatHistory (chatId={chat}, count=40)")
    try:
        r = requests.post(f"{base}/getChatHistory/{TOKEN}",
                          json={"chatId": chat, "count": 40}, timeout=60)
        print("  HTTP", r.status_code)
        msgs = r.json()
    except Exception as e:  # noqa: BLE001
        print("  getChatHistory FAILED:", str(e)[:200])
        msgs = None
    if isinstance(msgs, list):
        print(f"  {len(msgs)} message(s). Scanning for reactions / recent items:")
        for m in msgs[:40]:
            t = str(m.get("typeMessage", ""))
            mark = "  ⭐REACTION" if "reaction" in t.lower() else ""
            print(f"    - type={t} id={m.get('idMessage')}{mark}")
            if "reaction" in t.lower():
                print("      RAW:", json.dumps(m, ensure_ascii=False)[:400])
    else:
        print("  unexpected getChatHistory body:", json.dumps(msgs, ensure_ascii=False)[:300] if msgs is not None else "(none)")

    print("\n→ lastIncomingMessages (last 1440 min)")
    try:
        r2 = requests.get(f"{base}/lastIncomingMessages/{TOKEN}?minutes=1440", timeout=60)
        print("  HTTP", r2.status_code)
        inc = r2.json()
        if isinstance(inc, list):
            print(f"  {len(inc)} incoming item(s).")
            for m in inc[:40]:
                t = str(m.get("typeMessage", ""))
                mark = "  ⭐REACTION" if "reaction" in t.lower() else ""
                print(f"    - type={t} id={m.get('idMessage')}{mark}")
                if "reaction" in t.lower():
                    print("      RAW:", json.dumps(m, ensure_ascii=False)[:400])
        else:
            print("  body:", json.dumps(inc, ensure_ascii=False)[:300])
    except Exception as e:  # noqa: BLE001
        print("  lastIncomingMessages FAILED:", str(e)[:200])


def groups():
    """List the WhatsApp GROUPS this instance can see (id + name), so we can pick
    the right group chatId (…@g.us) to send the daily brief to."""
    base = f"https://api.green-api.com/waInstance{INSTANCE}"
    try:
        r = requests.get(f"{base}/getContacts/{TOKEN}", timeout=60)
        data = r.json()
    except Exception as e:  # noqa: BLE001
        print("getContacts failed:", str(e)[:200])
        return
    if not isinstance(data, list):
        print("unexpected getContacts body:", json.dumps(data, ensure_ascii=False)[:300])
        return
    grps = [c for c in data if str(c.get("id", "")).endswith("@g.us")]
    print(f"{len(grps)} group(s) found:")
    for g in grps:
        name = g.get("name") or g.get("contactName") or g.get("subject") or "(no name)"
        print(f"  {g.get('id')}  |  {name}")


def main():
    if MODE == "groups":
        groups()
        return
    if MODE == "history":
        history()
        return
    if MODE == "hosttest":
        hosttest()
        return
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
