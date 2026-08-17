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
import base64
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import feedparser

HERE = Path(__file__).resolve().parent
SOURCES_FILE = HERE / "sources.json"
SENT_FILE = HERE / "sent.json"
# Learned taste profile: stories Libi chose for past newsletters + her future
# "add to newsletter" clicks. Injected as SOFT positive guidance (few-shot), so
# the filter tilts toward her taste at the STORY level without crude category
# threshold changes. Positive signals only — "not added" is never a negative.
LEARN_FILE = HERE / "learning" / "added-examples.json"
MONTHLY_DIR = HERE / "monthly"
# Maps each sent WhatsApp message id -> its article, so a later ⭐ reaction can be
# resolved to the article (reactions may arrive days after the message).
MSGMAP_FILE = MONTHLY_DIR / "msgmap.json"
# Shared source of truth for the ACTIVE month. NOT the calendar month — the site
# and this engine both read it, and it only advances when the "End month" button
# is pressed (a few days into the next month is normal). Bootstraps to the
# calendar month on first run if unset.
STATE_FILE = MONTHLY_DIR / "state.json"

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
# Broadened single filter, so a bit higher than the old strict brief — tune freely.
MAX_ARTICLES = 8

# "Add to monthly newsletter" link appended to each WhatsApp message. Tapping it
# hits the Cloudflare Worker, which writes the article (starred) into the shared
# selection file so it appears in the newsletter builder. The share key gates the
# endpoint (must match the Worker's SHARE_KEY secret); with no key set, no link is
# added (safe default).
WORKER_ADD_URL = os.environ.get("WORKER_ADD_URL",
                                "https://news-digest-add.libia0305.workers.dev/add")
ADD_SHARE_KEY = os.environ.get("ADD_SHARE_KEY", "")

# Short "add to newsletter" links resolve on the site's own Cloudflare Pages
# project (Pages Functions), so the WhatsApp link is short and carries no
# personal account name: https://<PAGES_ADD_BASE>/a/<id>. Each article's full
# payload is registered under <id> in links.json (committed by the workflow);
# the /a/<id> function looks it up and stars the article.
PAGES_ADD_BASE = os.environ.get("PAGES_ADD_BASE",
                                "https://news-digest-ag1.pages.dev").rstrip("/")
LINKS_FILE = MONTHLY_DIR / "links.json"

# ----- the strategic filter (calibrated with Libi) -------------------------
RULES = """
You are a senior strategist at Strauss Group, a global F&B company. Its core
categories are: dairy, COFFEE (a global business — especially Eastern Europe
and Brazil), salty snacks & confectionery, dips & spreads (Sabra / Obela),
water (Tami4), and health / wellness.

From the candidate articles below, select every item a senior Strauss executive
would genuinely want to see — items that make you ask "what does this mean for
OUR strategy?". Keep a high, strategic bar (quality over quantity), but this is a
SINGLE selection that is broader than a deals-only brief: it should ALSO capture
the macro, commodity and consumer-trend stories that matter to an F&B strategist.
A quiet run with zero selected items is a perfectly valid outcome — NEVER pad the
list to reach a number.

WHAT QUALIFIES — six strategic angles:

1) M&A, DEALS & DIVESTITURES
   Acquisitions, mergers, selling or spinning off a business unit or brand —
   global and Israeli. Big ones especially (hundreds of millions+), but a
   meaningful Israeli deal counts too.

2) COMPETITOR STRATEGIC MOVES
   A competitor ENTERING — or seriously CONSIDERING entering — a new category
   (early signals count). Significant OPERATIONAL events at competitors — a
   notable FAILURE *or* SUCCESS (systems/supply-chain breakdown, cyberattack,
   shutdown, or a major operational win). Meaningful market-share shifts (with
   data); private-label milestones.

3) MACRO & COMMODITIES affecting F&B
   Food inflation, grocery volumes, tariffs / trade policy, the economies of key
   markets (e.g. China; Eastern Europe consumption / CPI), and commodity-price
   moves (coffee, cocoa, sugar, dairy) that hit margins or inputs.

4) COFFEE (core — high priority)
   Global coffee moves, with special attention to EASTERN EUROPE and BRAZIL
   (Strauss Coffee's turf): competitor entries, deals, capacity, pricing,
   harvests, cultured / next-gen coffee.

5) COCOA & CHOCOLATE (high priority)
   Alt-cocoa / lab-grown cocoa, cocoa price volatility, and strategic moves by
   major chocolate / ingredient players.

6) INNOVATION / FOOD-TECH & CONSUMER MEGATRENDS
   Food-tech that could disrupt our categories or key inputs (even from an
   unknown startup); the GLP-1 / weight-management wave and its impact on food;
   protein, gut-health and functional nutrition; clean-label / removing
   artificial ingredients; packaging & sustainability moves with real business
   impact.

COMPANY LIST IS A PRIORITY LIST, NOT A HARD FILTER:
  Priority players — Global: Unilever, Mondelez, PepsiCo, Nestle, Danone,
  Coca-Cola, Kraft Heinz, Keurig Dr Pepper, JDE Peet's, Lavazza, Ferrero,
  General Mills, Barry Callebaut, Hershey, Bel Group. Israeli: Strauss, Tnuva,
  Osem, Shufersal. A big move or disruptive innovation from a company NOT on this
  list still qualifies. Israeli competitors are held to the SAME bar as everyone
  else — important, but not an easier bar.

REJECT (noise — do not send):
  - MEAT & POULTRY stories — NOT of interest, UNLESS the impact is very large and
    exceptional.
  - routine product launches or new flavors, recipes / lifestyle / consumer tips,
    PR / awards / sponsorships / conferences, generic industry roundups without a
    specific company action, listicles ("Top 10..."), market-research reports
    without actual news, low-quality aggregator sites.

DEDUP — NO REPEATS (by STORY, not by URL):
  - If several candidates cover the SAME event, keep only ONE, from the best source.
  - If a story appears in ALREADY_SENT below, DROP it — even from a different
    source or with different wording. The ONLY exception is a MAJOR new
    development. A new angle, a reworded headline, or a minor update does NOT qualify.

The Strauss perspective above is ONLY for deciding WHICH articles to select.
It must NOT appear in the summary text.

OUTPUT for every selected item (short and factual — NO analysis):
  - LANGUAGE — match the source article: write BOTH the title and the summary in
    the SAME language the article is written in. Hebrew article -> Hebrew title and
    Hebrew summary; English article -> English title and English summary. Do NOT
    translate. (Use Title Case only for English titles.)
  - title = the article's own headline, in its original language.
  - summary = a short, factual summary of what the article itself reports, at most
    two sentences (~2 lines), in the article's language. Do NOT add strategic
    implications, do NOT mention Strauss, do NOT write "what this means for us".
  - story_key = a short stable slug in English/ASCII for the underlying story
    (e.g. "tnuva-vitamins-entry") — an internal key, always English, used to avoid
    repeating this story in future runs.
  - category = which monthly-newsletter section it belongs to — one of:
    "macro" | "mna" | "market" | "tech" (EVERY item gets one).

Put every selected item into the "selected" array. It may be empty.
"""

_CATEGORY_PROP = {
    "type": "string",
    "enum": ["macro", "mna", "market", "tech"],
    "description": "One category key (which newsletter section this belongs to)",
}
_ITEM_PROPS = {
    "title": {"type": "string", "description": "Headline in the article's own language"},
    "summary": {"type": "string", "description": "Factual summary, at most two sentences, in the article's language. No strategic analysis, no mention of Strauss."},
    "url": {"type": "string", "description": "The exact source URL, copied from the candidate"},
    "story_key": {"type": "string", "description": "Short stable English/ASCII slug for the underlying story"},
}

SUBMIT_TOOL = {
    "name": "submit_selection",
    "description": "Submit the selected strategic articles — every one is sent to WhatsApp. The list may be empty.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "description": "Every article that passes the strategic bar (categorized for the monthly newsletter).",
                "items": {
                    "type": "object",
                    "properties": dict(_ITEM_PROPS, category=_CATEGORY_PROP),
                    "required": ["title", "summary", "url", "story_key", "category"],
                },
            },
        },
        "required": ["selected"],
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
    """Return {"selected":[...]} from the tool response, or None if the response
    is malformed and should be retried."""
    payload = None
    for block in data.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "submit_selection":
            payload = block.get("input", {})
            break
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    selected = _clean_items(payload.get("selected", []), want_category=True)
    if selected is None:
        return None
    return {"selected": selected}


def taste_block(limit=45):
    """Soft few-shot taste guidance from LEARN_FILE (past-newsletter picks +
    future 'add to newsletter' clicks). Titles only, most-recent capped. Framed
    as guidance, NOT rules — never used to raise a category's bar."""
    ex = load_json(LEARN_FILE, [])
    if not isinstance(ex, list) or not ex:
        return ""
    lines = []
    for e in ex[-limit:]:
        if not isinstance(e, dict):
            continue
        title = str(e.get("title", "")).strip()
        cat = str(e.get("category", "")).strip() or "?"
        if title:
            lines.append(f"  - [{cat}] {title}")
    if not lines:
        return ""
    return (
        "\n\n======================================================================\n"
        "LIBI'S TASTE — examples of stories she chose for past monthly newsletters\n"
        "(and articles she later added). Use these as SOFT guidance for the KIND of\n"
        "story that resonates with her — NOT as hard rules. Do NOT reject a candidate\n"
        "merely because no example resembles it, and do NOT raise the bar for a whole\n"
        "category just because a similar example is absent. The RULES above remain the\n"
        "primary filter; these only tilt borderline calls toward her taste.\n"
        + "\n".join(lines)
    )


def judge(candidates, sent, api_key, attempts=3):
    already_sent = [{"story_key": s.get("story_key", ""), "title": s.get("title", "")} for s in sent]
    prompt = (
        RULES
        + taste_block()
        + "\n\nALREADY_SENT (do not repeat these stories):\n"
        + json.dumps(already_sent, ensure_ascii=False, indent=2)
        + "\n\nCANDIDATES (choose from these only; copy URLs exactly):\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2)
    )
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 5000,
        "tools": [SUBMIT_TOOL],
        "tool_choice": {"type": "tool", "name": "submit_selection"},
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
    return {"selected": []}


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


def save_msgmap(entries):
    """Record {idMessage: article} for sent brief messages, so the reaction
    poller can resolve a ⭐ back to its article. Prunes entries older than 45 days."""
    if not entries:
        return
    now = datetime.now(timezone.utc)
    MONTHLY_DIR.mkdir(exist_ok=True)
    data = load_json(MSGMAP_FILE, {})
    if not isinstance(data, dict):
        data = {}
    cutoff = now - timedelta(days=45)
    data = {
        mid: v for mid, v in data.items()
        if _parse_dt(v.get("sent_at"), now) >= cutoff
    }
    data.update(entries)
    MSGMAP_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  ✓ message map updated ({len(data)} ids tracked)")


def _parse_dt(s, default):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return default


def current_month():
    """The ACTIVE month label (YYYY-MM) shared by this engine and the site.
    NOT the calendar month — read from STATE_FILE; only the site's 'End month'
    button advances it. Bootstraps to the calendar month if unset."""
    state = load_json(STATE_FILE, {})
    cm = state.get("current_month") if isinstance(state, dict) else None
    return cm or f"{datetime.now(timezone.utc):%Y-%m}"


def save_to_monthly_pool(pool_items):
    """Accumulate categorized pool items into the ACTIVE month's file
    (fb-brief/monthly/<active-month>.json), de-duplicated by url. The active
    month comes from STATE_FILE, not the calendar. Starred flag is set later
    (Phase B) via reactions."""
    if not pool_items:
        return
    now = datetime.now(timezone.utc)
    MONTHLY_DIR.mkdir(exist_ok=True)
    cm = current_month()
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({"current_month": cm}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        log(f"  ✓ bootstrapped active month → {cm}")
    path = MONTHLY_DIR / f"{cm}.json"
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
            "from_brief": bool(a.get("from_brief", False)),
            "starred": False,
            "added_at": now.isoformat(),
        })
        seen.add(a["url"])
        added += 1
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  ✓ monthly pool updated (+{added}, {len(existing)} total in {path.name})")


# ----- 4. format -----------------------------------------------------------
def link_id(url, month):
    """Short, stable id for an article's add-link (same url+month -> same id, so
    re-runs are idempotent). 10 hex chars is plenty to avoid collisions here."""
    return hashlib.sha1(f"{url}|{month}".encode("utf-8")).hexdigest()[:10]


def strip_tracking(url):
    """Drop RSS/utm tracking cruft for the displayed link (identity keeps the
    original url everywhere else)."""
    url = re.sub(r"#utm_[^\s]*$", "", url)
    url = re.sub(r"[?&]utm_[^=]+=[^&\s]*", "", url)
    return url.rstrip("?&#")


def build_add_payload(a, month, image=""):
    """The article payload registered under its short id in links.json, which the
    site's /a/<id> Pages function reads to star the article. `image` (an og:image
    URL, optional) lets the site pre-fill the newsletter image."""
    payload = {
        "url": a["url"],
        "title": a["title"],
        "summary": a["summary"],
        "category": a.get("category", "market"),
        "story_key": a.get("story_key", ""),
        "month": month,
    }
    if image:
        payload["image"] = image
    return payload


def save_links(new_map):
    """Merge {id: payload} into monthly/links.json (committed by the workflow) so
    each short /a/<id> link resolves. Pruned to the most recent entries to keep
    the file small."""
    if not new_map:
        return
    MONTHLY_DIR.mkdir(exist_ok=True)
    data = load_json(LINKS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.update(new_map)
    if len(data) > 300:
        data = dict(list(data.items())[-300:])
    LINKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  ✓ links.json updated ({len(data)} short links tracked)")


def format_article(a, add_url=""):
    # One WhatsApp message per article: bold title, link, 2-line summary, and
    # (if configured) a tap-to-add-to-newsletter link.
    body = (
        f"📌 *{a['title']}*\n"
        f"🔗 {strip_tracking(a['url'])}\n\n"
        f"{a['summary']}"
    )[:18000]  # leave room for the add-link; stay under Green API's 20k limit
    if add_url:
        body += f"\n\n➕ הוספה לניוז החודשי:\n{add_url}"
    return body


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
    try:
        return str(resp.json().get("idMessage", "") or "")
    except Exception:  # noqa: BLE001
        return ""


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
        result = {"selected": []}
    else:
        log("② Asking Claude to select the strategic articles (single filter)...")
        result = judge(candidates, sent, api_key)

    selected = result["selected"]
    if len(selected) > MAX_ARTICLES:
        log(f"   ↳ capping {len(selected)} → {MAX_ARTICLES} (safety valve)")
        selected = selected[:MAX_ARTICLES]
    log(f"   → {len(selected)} selected (→ WhatsApp)\n")

    if selected:
        log("③ Selected:")
        for a in selected:
            log(f"   • [{a.get('category', '?')}] {a['title']}  [{a.get('story_key', '')}]")

    if NO_SEND:
        log("\nNO_SEND — skipping WhatsApp and memory (diagnostic only).")
        return

    if not selected:
        log("☕ No strategic news this run.")
        if TEST_MODE:
            log("   (TEST_MODE) sending heartbeat.")
            send_whatsapp("✅ בדיקת F&B Brief: הצינור עובד מקצה לקצה. אין כתבות אסטרטגיות כרגע ☕")
        log("\n✅ Done.")
        return

    log(f"\n④ Sending {len(selected)} separate WhatsApp message(s)...")
    now = datetime.now(timezone.utc)
    month = current_month()   # active month the add-link will file the article under

    # Register each article's payload under a short id and build the short link
    # BEFORE sending, then persist links.json so the /a/<id> function resolves.
    links = {}
    add_urls = []
    for a in selected:
        # Best-effort og:image so the site can pre-fill the newsletter image
        # (failures just fall back to a manual upload in the wizard).
        og_image = fetch_og_image(a["url"])
        lid = link_id(a["url"], month)
        links[lid] = build_add_payload(a, month, og_image)
        add_urls.append(f"{PAGES_ADD_BASE}/a/{lid}")
    save_links(links)

    msgmap = {}
    for i, a in enumerate(selected):
        if i:
            time.sleep(2)   # pace messages so Green API keeps order / avoids rate limits
        mid = send_whatsapp(format_article(a, add_urls[i]))
        if mid:
            msgmap[mid] = {
                "url": a["url"],
                "title": a["title"],
                "summary": a["summary"],
                "story_key": a.get("story_key", ""),
                "category": a.get("category", "market"),
                "sent_at": now.isoformat(),
            }
    save_msgmap(msgmap)
    update_memory(sent, selected)
    log("\n✅ Done.")


if __name__ == "__main__":
    main()
