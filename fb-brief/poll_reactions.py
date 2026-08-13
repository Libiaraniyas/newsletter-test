#!/usr/bin/env python3
"""
Poll Green API for ⭐ reactions and mark the reacted articles as starred in the
active month's pool. Runs on a schedule (GitHub Actions) — no webhook server.

Flow per run:
  1. receiveNotification (repeatedly) drains Green API's queue.
  2. For a reaction on a message we sent (looked up in msgmap.json):
       - a non-empty emoji  => star the article (add to the pool if missing)
       - an empty emoji     => un-star it (reaction removed)
  3. deleteNotification for each processed item.
The workflow commits any pool changes.

Reaction JSON shape varies by Green API version, so we parse defensively AND
log the raw body of anything we don't recognize — the first real test reveals
the exact format and we tune the parser from the logs.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from brief import load_json, current_month, fetch_og_image, MONTHLY_DIR, MSGMAP_FILE

INSTANCE = os.environ["GREEN_API_INSTANCE"]
TOKEN = os.environ["GREEN_API_TOKEN"]
BASE = f"https://api.green-api.com/waInstance{INSTANCE}"
MAX_ITER = 300  # safety cap on notifications processed per run


def log(m):
    print(m, flush=True)


def pool_path():
    return MONTHLY_DIR / f"{current_month()}.json"


def receive():
    r = requests.get(f"{BASE}/receiveNotification/{TOKEN}", timeout=40)
    if r.status_code == 200:
        return r.json()   # None/empty when the queue is drained
    log(f"  ⚠️  receiveNotification HTTP {r.status_code}: {r.text[:200]}")
    return None


def delete(receipt_id):
    try:
        requests.delete(f"{BASE}/deleteNotification/{TOKEN}/{receipt_id}", timeout=30)
    except Exception:  # noqa: BLE001
        pass


def parse_reaction(body):
    """Return (target_message_id, emoji_text) for a reaction, else None.
    Tries the known Green API shapes; emoji '' means the reaction was removed."""
    md = body.get("messageData", {}) or {}
    t = md.get("typeMessage", "")
    if "reaction" not in t.lower():
        return None
    # Known containers across versions
    rd = (md.get("reactionMessage")
          or md.get("extendedTextMessageData")
          or md.get("reaction")
          or {})
    if not isinstance(rd, dict):
        rd = {}
    emoji = rd.get("text", rd.get("emoji", rd.get("reaction", "")))
    target = (rd.get("idMessage") or rd.get("messageId")
              or rd.get("quotedMessageId") or md.get("quotedMessage", {}).get("stanzaId", ""))
    return str(target or ""), str(emoji or "")


def main():
    msgmap = load_json(MSGMAP_FILE, {})
    if not isinstance(msgmap, dict):
        msgmap = {}
    path = pool_path()
    pool = load_json(path, [])
    by_url = {a.get("url"): a for a in pool}
    changed = False
    seen_incoming = 0

    for _ in range(MAX_ITER):
        note = receive()
        if not note:
            break
        receipt = note.get("receiptId")
        body = note.get("body", {}) or {}
        try:
            hook = body.get("typeWebhook", "")
            if hook == "incomingMessageReceived":
                seen_incoming += 1
                r = parse_reaction(body)
                if r is None:
                    # Not a reaction — log a compact hint so we learn the shape.
                    log(f"  · incoming (not a reaction): {json.dumps(body.get('messageData', {}), ensure_ascii=False)[:180]}")
                else:
                    target, emoji = r
                    art = msgmap.get(target)
                    if not art:
                        log(f"  · reaction on unknown message {target} (emoji={emoji!r})")
                    else:
                        starred = bool(emoji.strip())
                        existing = by_url.get(art["url"])
                        if existing:
                            if existing.get("starred") != starred:
                                existing["starred"] = starred
                                changed = True
                        elif starred:
                            item = {
                                "url": art["url"],
                                "title": art["title"],
                                "summary": art["summary"],
                                "story_key": art.get("story_key", ""),
                                "category": art.get("category", "market"),
                                "image": fetch_og_image(art["url"]),
                                "starred": True,
                                "added_at": datetime.now(timezone.utc).isoformat(),
                            }
                            pool.append(item)
                            by_url[art["url"]] = item
                            changed = True
                        log(f"  {'⭐' if starred else '☆'} {art['title'][:70]}")
        finally:
            if receipt:
                delete(receipt)

    if changed:
        path.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"✓ {path.name}: {sum(1 for a in pool if a.get('starred'))} starred / {len(pool)} total")
    else:
        log(f"no pool changes (saw {seen_incoming} incoming notification(s))")


if __name__ == "__main__":
    main()
