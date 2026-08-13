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
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import feedparser

HERE = Path(__file__).resolve().parent
SOURCES_FILE = HERE / "sources.json"
SENT_FILE = HERE / "sent.json"
MONTHLY_DIR = HERE / "monthly"

# ----- tunables ------------------------------------------------------------
LOOKBACK_HOURS = 48          # only consider articles newer than this
MAX_PER_FEED = 15            # cap candidates per feed (protect against huge feeds)
FEED_TIMEOUT = 20            # seconds per feed — a hung host can't stall the run
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MEMORY_DAYS = 14             # how long a story stays "already sent"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
ANTHROPIC_VERSION = "2023-06-01"

# In TEST_MODE, when zero articles qualify we still send a short heartbeat
# so you can confirm the end-to-end pipeline reached WhatsApp.
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# In DRY_RUN, only collect and print candidates — no Claude call, no WhatsApp.
# Used to verify which feeds are alive without messaging anyone.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# In NO_SEND, run the full pipeline incl. Claude selection but skip WhatsApp and
# memory — for safely inspecting what the model picks without messaging anyone.
NO_SEND = os.environ.get("NO_SEND", "false").lower() == "true"

# Hard safety cap on how many messages one run can send (a brief, not a feed dump).
MAX_ARTICLES = 5

# ----- the strategic filter (calibrated with Libi) -------------------------
RULES = """
You are a senior strategist at Strauss Group, a global F&B company. Its core
categories are: dairy, COFFEE (a global business — especially Eastern Europe
and Brazil), salty snacks & confectionery, dips & spreads (Sabra / Obela),
water (Tami4), and health / wellness.

From the candidate articles below, select ONLY items a senior Strauss executive
would stop and think about, asking "what does this mean for OUR strategy?".
Be strict — quality over quantity. Zero selected articles is a perfectly valid,
good outcome. NEVER pad the list to reach a number; ONE excellent item is a
complete, successful brief. Select AT MOST 5 items, and usually 0–3 — if you are
choosing more than 5, your bar is too low.

WHAT QUALIFIES (high strategic bar) — examples of the kind of move we want:
  - M&A, acquisitions, divestitures, SELLING a business unit or brand —
    especially large ones (hundreds of millions+). E.g. "Unilever sells its
    food business", "Company X sells brand Y for hundreds of millions".
  - A competitor ENTERING — or even seriously CONSIDERING entering — a new
    category. Early signals count (e.g. "Tnuva is weighing a move into a new field").
  - INNOVATION / food-tech that could disrupt our categories or key inputs —
    e.g. lab-grown cocoa, novel ingredients, new platforms — EVEN from an
    unknown startup, not only from the big players.
  - OPERATIONAL events at competitors — ANY significant FAILURE *or* SUCCESS:
    a systems/supply-chain breakdown (e.g. Tnuva's warehouse collapse) or a
    notable operational win.
  - COFFEE-market moves globally, with special attention to EASTERN EUROPE and
    BRAZIL (Strauss Coffee's turf): competitor entries, deals, capacity, pricing.
  - Meaningful market-share shifts (with data), private-label milestones.
  - Big, structurally interesting moves EVEN in categories Strauss is NOT in,
    when they signal where the industry is heading.
  - Moves by Israeli competitors (Tnuva, Osem, Shufersal, Strauss) get a LOWER
    bar — even a mid-size but meaningful Israeli move is worth sending.

COMPANY LIST IS A PRIORITY LIST, NOT A HARD FILTER:
  Priority players — Global: Unilever, Mondelez, PepsiCo, Nestle, Danone,
  Coca-Cola, Kraft Heinz, Keurig Dr Pepper, JDE Peet's, Lavazza, Ferrero,
  General Mills, Barry Callebaut, Hershey. Israeli: Strauss, Tnuva, Osem,
  Shufersal. BUT a big move or disruptive innovation from a company NOT on this
  list still qualifies.

REJECT (noise — do not send):
  routine product launches or new flavors, recipes / lifestyle / consumer tips,
  PR / awards / sponsorships / conferences, generic industry roundups without a
  specific company action, listicles ("Top 10..."), market-research reports
  without actual news, low-quality aggregator sites.

DEDUP — NO REPEATS (by STORY, not by URL):
  - If several candidates cover the SAME event, keep only ONE, from the best source.
  - If a story appears in ALREADY_SENT below, DROP it — even from a different
    source or with different wording. The ONLY exception is a MAJOR new
    development (e.g. "Tnuva lost 5% market share because of the crisis").
    A new angle, a reworded headline, or a minor update does NOT qualify.

The Strauss perspective above is ONLY for deciding WHICH articles to select.
It must NOT appear in the summary text.

These strict picks go into the "brief" array (this is what is sent to WhatsApp).

OUTPUT for every item (short and factual — NO analysis):
  - LANGUAGE — match the source article: write BOTH the title and the summary in
    the SAME language the article is written in. Hebrew article -> Hebrew title and
    Hebrew summary; English article -> English title and English summary. Do NOT
    translate. (Use Title Case only for English titles.)
  - title = the article's own headline, in its original language.
  - summary = a short, factual summary of what the article itself reports, at most
    two sentences (~2 lines), in the article's language. Do NOT add strategic
    implications, do NOT mention Strauss, do NOT write "what this means for us".
  - story_key = a short stable slug in English/ASCII for the underlying story
    (e.g. "tnuva-vitamins-entry") — this is an internal key, always English,
    used to avoid repeating this story in future runs.

======================================================================
SECOND TASK — THE MONTHLY POOL (broader, categorized)
After the strict brief, ALSO build a "pool" for a monthly F&B business
newsletter. From the candidates you did NOT put in the brief, select every item
that is genuinely relevant for such a newsletter — still selective, NOT boring
filler — and give each ONE category key:
  - "macro"  = Macro Environment (economy, inflation, commodities, policy, geopolitics affecting F&B)
  - "mna"    = M&A and Divestitures (deals, acquisitions, sales, spin-offs)
  - "market" = Market Dynamics (competition, earnings, retail, market share, weighty launches)
  - "tech"   = Tech & Innovation (food-tech, ingredients, novel platforms, R&D)
Pool rules:
  - Do NOT include anything already in the brief (no duplicates between brief and pool).
  - Broader than the brief, but still selective — skip lifestyle/recipes/PR/awards/trivia.
  - Same output format and LANGUAGE rule as above, plus a "category" field (one of the four keys).
These items go into the "pool" array (shown on the site, NOT sent to WhatsApp).
"""

_ITEM_PROPS = {
    "title": {"type": "string", "description": "Headline in the article's own language"},
    "summary": {"type": "string", "description": "Factual summary, at most two sentences, in the article's language. No strategic analysis, no mention of Strauss."},
    "url": {"type": "string", "description": "The exact source URL, copied from the candidate"},
    "story_key": {"type": "string", "description": "Short stable English/ASCII slug for the underlying story"},
}

SUBMIT_TOOL = {
    "name": "submit_brief",
    "description": "Submit the strict brief (for WhatsApp) and the broader categorized pool (for the site). Either list may be empty.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brief": {
                "type": "array",
                "description": "Strict strategic picks — sent to WhatsApp.",
                "items": {
                    "type": "object",
                    "properties": dict(_ITEM_PROPS),
                    "required": ["title", "summary", "url", "story_key"],
                },
            },
            "pool": {
                "type": "array",
                "description": "Broader, categorized picks for the monthly newsletter — shown on the site.",
                "items": {
                    "type": "object",
                    "properties": dict(_ITEM_PROPS, category={
                        "type": "string",
                        "enum": ["macro", "mna", "market", "tech"],
                        "description": "One category key",
                    }),
                    "required": ["title", "summary", "url", "story_key", "category"],
                },
            },
        },
        "required": ["brief", "pool"],
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
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=FEED_TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  {name}: fetch failed ({e})")
            continue
        if not feed.entries:
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
VALID_CATEGORIES = ("macro", "mna", "market", "tech")


def _clean_items(raw, want_category=False):
    """Normalize a raw list of article dicts, recovering stringified shapes.
    Returns a list, or None if the input isn't a recoverable list."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if isinstance(raw, dict):
        raw = raw.get("articles", raw)
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except (ValueError, TypeError):
                continue
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not title or not url:
            continue
        rec = {
            "title": title,
            "url": url,
            "summary": str(item.get("summary", "")).strip(),
            "story_key": str(item.get("story_key", "")).strip() or title.lower(),
        }
        if want_category:
            cat = str(item.get("category", "")).strip().lower()
            rec["category"] = cat if cat in VALID_CATEGORIES else "market"
        out.append(rec)
    return out


def _extract_result(data):
    """Return {"brief":[...], "pool":[...]} from the tool response, or None if
    the response is malformed and should be retried."""
    payload = None
    for block in data.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "submit_brief":
            payload = block.get("input", {})
            break
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    brief = _clean_items(payload.get("brief", []), want_category=False)
    pool = _clean_items(payload.get("pool", []), want_category=True)
    if brief is None or pool is None:
        return None
    return {"brief": brief, "pool": pool}


def judge(candidates, sent, api_key, attempts=3):
    already_sent = [{"story_key": s.get("story_key", ""), "title": s.get("title", "")} for s in sent]
    prompt = (
        RULES
        + "\n\nALREADY_SENT (do not repeat these stories):\n"
        + json.dumps(already_sent, ensure_ascii=False, indent=2)
        + "\n\nCANDIDATES (choose from these only; copy URLs exactly):\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2)
    )
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 5000,
        "tools": [SUBMIT_TOOL],
        "tool_choice": {"type": "tool", "name": "submit_brief"},
        "messages": [{"role": "user", "content": prompt}],
    }
    for attempt in range(1, attempts + 1):
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

        result = _extract_result(resp.json())
        if result is not None:
            return result
        log(f"  ⚠️  malformed model response (attempt {attempt}/{attempts})"
            + (" — retrying" if attempt < attempts else " — giving up"))
    return {"brief": [], "pool": []}


# ----- og:image + monthly pool store ---------------------------------------
def fetch_og_image(url):
    """Best-effort: return the article's og:image URL, or '' on any failure."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        html_text = resp.text[:200000]
        for pat in (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ):
            m = re.search(pat, html_text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def save_to_monthly_pool(pool_items):
    """Accumulate categorized pool items into fb-brief/monthly/YYYY-MM.json,
    de-duplicated by url. Starred flag is added later (Phase B) via reactions."""
    if not pool_items:
        return
    now = datetime.now(timezone.utc)
    MONTHLY_DIR.mkdir(exist_ok=True)
    path = MONTHLY_DIR / f"{now:%Y-%m}.json"
    existing = load_json(path, [])
    seen = {a.get("url") for a in existing}
    added = 0
    for a in pool_items:
        if a["url"] in seen:
            continue
        existing.append({
            "url": a["url"],
            "title": a["title"],
            "summary": a["summary"],
            "story_key": a.get("story_key", ""),
            "category": a.get("category", "market"),
            "image": a.get("image", ""),
            "starred": False,
            "added_at": now.isoformat(),
        })
        seen.add(a["url"])
        added += 1
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  ✓ monthly pool updated (+{added}, {len(existing)} total in {path.name})")


# ----- 4. format -----------------------------------------------------------
def format_article(a):
    # One WhatsApp message per article: bold title, link, then a 2-line summary.
    return (
        f"📌 *{a['title']}*\n"
        f"🔗 {a['url']}\n\n"
        f"{a['summary']}"
    )[:19000]  # stay under Green API's 20k limit


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
    sources = load_json(SOURCES_FILE, [])
    sent = load_json(SENT_FILE, [])

    log("① Collecting candidates from feeds...")
    candidates = collect_candidates(sources)
    candidates = drop_known_urls(candidates, sent)
    log(f"   → {len(candidates)} candidate article(s) after URL dedup\n")

    if DRY_RUN:
        log("DRY_RUN — feeds only, no Claude call, no WhatsApp. Candidates:")
        for c in candidates:
            log(f"   • [{c['source']}] {c['title'][:90]}")
        log("\n✅ Dry run done.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("✗ ANTHROPIC_API_KEY is not set — add it as a GitHub Secret.")
        sys.exit(1)

    if not candidates:
        log("No candidates at all — nothing to judge.")
        result = {"brief": [], "pool": []}
    else:
        log("② Asking Claude for the brief (strict) + the monthly pool (broad)...")
        result = judge(candidates, sent, api_key)

    brief = result["brief"]
    pool = result["pool"]
    if len(brief) > MAX_ARTICLES:
        log(f"   ↳ capping brief {len(brief)} → {MAX_ARTICLES} (safety valve)")
        brief = brief[:MAX_ARTICLES]
    log(f"   → brief: {len(brief)} (→ WhatsApp) | pool: {len(pool)} (→ site)\n")

    if brief:
        log("③ Brief:")
        for a in brief:
            log(f"   • {a['title']}  [{a.get('story_key', '')}]")
    if pool:
        log("③ Pool:")
        for a in pool:
            log(f"   • [{a.get('category', '?')}] {a['title']}")

    if NO_SEND:
        log("\nNO_SEND — skipping WhatsApp, memory, and pool write (diagnostic only).")
        return

    # --- monthly pool: fetch images + save silently (never sent to WhatsApp) ---
    if pool:
        log(f"\n④ Fetching og:image for {len(pool)} pool item(s)...")
        for a in pool:
            a["image"] = fetch_og_image(a["url"])
        save_to_monthly_pool(pool)

    # --- brief -> WhatsApp (behavior unchanged from before) ---
    if not brief:
        log("☕ No strategic news for WhatsApp this run.")
        if TEST_MODE:
            log("   (TEST_MODE) sending heartbeat.")
            send_whatsapp("✅ בדיקת F&B Brief: הצינור עובד מקצה לקצה. אין כתבות אסטרטגיות כרגע ☕")
        log("\n✅ Done.")
        return

    log(f"\n⑤ Sending {len(brief)} separate WhatsApp message(s)...")
    for i, a in enumerate(brief):
        if i:
            time.sleep(2)   # pace messages so Green API keeps order / avoids rate limits
        send_whatsapp(format_article(a))
    update_memory(sent, brief)
    log("\n✅ Done.")


if __name__ == "__main__":
    main()
