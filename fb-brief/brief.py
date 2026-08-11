#!/usr/bin/env python3
"""
F&B Daily Brief — proof of concept.

Flow:
  1. Collect candidate articles from a small set of RSS feeds (incl. Hebrew).
  2. Drop anything whose URL was already sent (cheap first-pass dedup).
  3. Ask Claude ONCE to pick only the strategically important stories,
     returning clean structured JSON (no free-text extraction needed).
  4. If nothing qualifies -> send nothing (a quiet day is a valid result).
  5. Send the selected articles to the WhatsApp group via Green API.
  6. Remember what we sent (url + story_key) so we never repeat a story.

Everything the user might want to tweak lives in sources.json and in the
two RULES constants below.
"""

import json
import os
import sys
import html
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import feedparser

HERE = Path(__file__).resolve().parent
SOURCES_FILE = HERE / "sources.json"
SENT_FILE = HERE / "sent.json"

# ----- tunables ------------------------------------------------------------
LOOKBACK_HOURS = 48          # only consider articles newer than this
MAX_PER_FEED = 8             # cap candidates per feed (protect against huge feeds)
MEMORY_DAYS = 14             # how long a story stays "already sent"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
ANTHROPIC_VERSION = "2023-06-01"

# In TEST_MODE, when zero articles qualify we still send a short heartbeat
# so you can confirm the end-to-end pipeline reached WhatsApp.
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# ----- the two rules you locked in -----------------------------------------
RULES = """
You are a senior BI strategist at Strauss Group, an Israeli F&B company.
From the candidate articles below, select ONLY items that clear a high
strategic bar. Zero selected articles is a perfectly valid, good outcome.

RULE 1 — QUALITY (be strict; quality over quantity):
  SELECT only genuinely strategic moves, e.g.:
    - A strong company ENTERING A NEW CATEGORY (e.g. a dairy firm launching supplements/pet food)
    - Major M&A / a large acquisition or divestiture
    - A meaningful market-share shift (with data)
    - A significant competitive move by an Israeli player (Tnuva, Osem, Strauss, Shufersal)
    - A leadership change or earnings surprise with clear strategic signal
  REJECT anything mediocre: routine product launches, new flavors, recipes,
  lifestyle, PR/awards/sponsorships, generic roundups, listicles, market-research
  reports without news. Do NOT pad the list to reach a number.
  ONE excellent article is a complete, successful brief.

RULE 2 — NO REPEATS (dedup by STORY, not by URL):
  - If several candidates cover the SAME event, keep only ONE, from the best source.
  - If a story appears in ALREADY_SENT below, DROP it — even from a different
    source or with different wording. The ONLY exception is a MAJOR new
    development (e.g. "Tnuva lost 5% market share because of the crisis").
    A new angle, a reworded headline, or a minor update does NOT qualify.

OUTPUT:
  - Titles in English, Title Case. If the source is Hebrew, translate the title.
  - summary = exactly two sentences: what happened, then what it means strategically.
  - story_key = a short stable slug for the underlying story (e.g. "tnuva-vitamins-entry"),
    used to avoid repeating this story in future runs.
"""

SUBMIT_TOOL = {
    "name": "submit_brief",
    "description": "Submit the final selected strategic articles (may be an empty list).",
    "input_schema": {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "English, Title Case"},
                        "summary": {"type": "string", "description": "Exactly two sentences: what happened + strategic implication"},
                        "url": {"type": "string", "description": "The exact source URL, copied from the candidate"},
                        "story_key": {"type": "string", "description": "Short stable slug for the underlying story"},
                    },
                    "required": ["title", "summary", "url", "story_key"],
                },
            }
        },
        "required": ["articles"],
    },
}


def log(msg):
    print(msg, flush=True)


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ----- 1. collect ----------------------------------------------------------
def collect_candidates(sources):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    candidates = []
    for src in sources:
        name, url = src["name"], src["url"]
        try:
            feed = feedparser.parse(url)
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  {name}: failed to parse ({e})")
            continue
        if getattr(feed, "bozo", False) and not feed.entries:
            log(f"  ⚠️  {name}: no entries / broken feed")
            continue

        taken = 0
        for entry in feed.entries:
            if taken >= MAX_PER_FEED:
                break
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            candidates.append({
                "source": name,
                "title": strip_html(entry.get("title", "")),
                "summary": strip_html(entry.get("summary", ""))[:400],
                "url": entry.get("link", ""),
            })
            taken += 1
        log(f"  ✓ {name}: {taken} recent candidate(s)")
    return candidates


# ----- 2. cheap URL pre-filter --------------------------------------------
def drop_known_urls(candidates, sent):
    sent_urls = {item["url"] for item in sent}
    fresh = [c for c in candidates if c["url"] not in sent_urls]
    if len(fresh) != len(candidates):
        log(f"  ↳ removed {len(candidates) - len(fresh)} already-sent URL(s)")
    return fresh


# ----- 3. judge with Claude (structured JSON) ------------------------------
def judge(candidates, sent, api_key):
    already_sent = [{"story_key": s.get("story_key", ""), "title": s.get("title", "")} for s in sent]
    payload = {
        "candidates": candidates,
        "already_sent": already_sent,
    }
    prompt = (
        RULES
        + "\n\nALREADY_SENT (do not repeat these stories):\n"
        + json.dumps(already_sent, ensure_ascii=False, indent=2)
        + "\n\nCANDIDATES (choose from these only; copy URLs exactly):\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2)
    )
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1500,
        "tools": [SUBMIT_TOOL],
        "tool_choice": {"type": "tool", "name": "submit_brief"},
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json=body,
        timeout=120,
    )
    if resp.status_code != 200:
        log(f"  ✗ Anthropic API error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()

    data = resp.json()
    for block in data.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "submit_brief":
            return block["input"].get("articles", [])
    return []


# ----- 4. format -----------------------------------------------------------
def format_message(articles):
    lines = ["📰 *F&B Daily Brief*", ""]
    for a in articles:
        lines.append(f"📌 {a['title']}")
        lines.append(a["summary"])
        lines.append(f"🔗 {a['url']}")
        lines.append("")
    return "\n".join(lines).strip()[:19000]  # stay under Green API's 20k limit


# ----- 5. send via Green API ----------------------------------------------
def send_whatsapp(text):
    instance = os.environ["GREEN_API_INSTANCE"]
    token = os.environ["GREEN_API_TOKEN"]
    chat_id = os.environ["GREEN_API_CHAT_ID"]
    url = f"https://api.green-api.com/waInstance{instance}/sendMessage/{token}"
    resp = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=60)
    if resp.status_code != 200:
        log(f"  ✗ Green API error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    log("  ✓ WhatsApp message sent")


# ----- 6. memory -----------------------------------------------------------
def update_memory(sent, new_articles):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MEMORY_DAYS)
    kept = []
    for item in sent:
        try:
            ts = datetime.fromisoformat(item["sent_at"])
        except (KeyError, ValueError):
            ts = now
        if ts >= cutoff:
            kept.append(item)
    for a in new_articles:
        kept.append({
            "url": a["url"],
            "story_key": a.get("story_key", ""),
            "title": a["title"],
            "sent_at": now.isoformat(),
        })
    SENT_FILE.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  ✓ memory updated ({len(kept)} stories tracked)")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("✗ ANTHROPIC_API_KEY is not set — add it as a GitHub Secret.")
        sys.exit(1)

    sources = load_json(SOURCES_FILE, [])
    sent = load_json(SENT_FILE, [])

    log("① Collecting candidates from feeds...")
    candidates = collect_candidates(sources)
    candidates = drop_known_urls(candidates, sent)
    log(f"   → {len(candidates)} candidate article(s) after URL dedup\n")

    if not candidates:
        log("No candidates at all — nothing to judge.")
        articles = []
    else:
        log("② Asking Claude to select strategic stories...")
        articles = judge(candidates, sent, api_key)
        log(f"   → Claude selected {len(articles)} article(s)\n")

    if not articles:
        log("☕ No strategic news this run.")
        if TEST_MODE:
            log("   (TEST_MODE) sending heartbeat so you can see the pipeline works.")
            send_whatsapp("✅ בדיקת F&B Brief: הצינור עובד מקצה לקצה. אין כתבות אסטרטגיות כרגע ☕")
        return

    log("③ Selected articles:")
    for a in articles:
        log(f"   • {a['title']}  [{a.get('story_key','')}]")
    log("")

    message = format_message(articles)
    log("④ Sending to WhatsApp...")
    send_whatsapp(message)
    update_memory(sent, articles)
    log("\n✅ Done.")


if __name__ == "__main__":
    main()
