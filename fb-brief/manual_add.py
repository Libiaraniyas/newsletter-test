#!/usr/bin/env python3
"""Manually add specific article URLs to the active month's newsletter selection
AND the taste-learning file — exactly like tapping the "add to newsletter" link.

For each URL it fetches the page's og:title / og:description / og:image, files the
article (starred) into fb-brief/monthly/selection-<active-month>.json, and appends
a taste example to fb-brief/learning/added-examples.json. The workflow commits it.

Env inputs:
  URLS  - article URLs, newline- or comma-separated
  CATS  - optional categories parallel to URLS (macro|mna|market|tech);
          anything missing/invalid defaults to 'market'
"""
import os
import re
import json
import html
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
MONTHLY = HERE / "monthly"
LEARN_FILE = HERE / "learning" / "added-examples.json"
STATE_FILE = MONTHLY / "state.json"
VALID = {"macro", "mna", "market", "tech"}
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122 Safari/537.36")


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def active_month():
    st = load(STATE_FILE, {})
    cm = st.get("current_month") if isinstance(st, dict) else None
    return cm or f"{datetime.now(timezone.utc):%Y-%m}"


def _meta(text, *keys):
    for k in keys:
        for pat in (
            r'<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % re.escape(k),
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']%s["\']' % re.escape(k),
            r'<meta[^>]+name=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % re.escape(k),
        ):
            m = re.search(pat, text, re.I)
            if m:
                return html.unescape(m.group(1).strip())
    return ""


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:60] or "story"


def fetch(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    t = r.text[:300000]
    title = _meta(t, "og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", t, re.I)
        title = m.group(1).strip() if m else url
    summ = _meta(t, "og:description", "twitter:description", "description")
    img = _meta(t, "og:image", "twitter:image")
    return html.unescape(title), summ, img


def main():
    urls = [u.strip() for u in re.split(r"[\n,]+", os.environ.get("URLS", "")) if u.strip()]
    cats = [c.strip() for c in os.environ.get("CATS", "").split(",")]
    if not urls:
        print("No URLS provided.")
        return
    month = active_month()
    print("active month:", month)

    sel_path = MONTHLY / f"selection-{month}.json"
    sel = load(sel_path, {})
    if not isinstance(sel, dict):
        sel = {}
    sel.setdefault("month", month)
    sel.setdefault("added", [])
    sel.setdefault("starred", [])
    sel.setdefault("category_names", {})
    sel.setdefault("category_overrides", {})
    sel.setdefault("hidden", [])

    learn = load(LEARN_FILE, [])
    if not isinstance(learn, list):
        learn = []

    added_urls = {a.get("url") for a in sel["added"] if isinstance(a, dict)}
    learn_urls = {e.get("url") for e in learn if isinstance(e, dict)}

    for i, u in enumerate(urls):
        cat = cats[i] if i < len(cats) and cats[i] in VALID else "market"
        try:
            title, summ, img = fetch(u)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ fetch failed {u}: {str(e)[:140]}")
            continue
        item = {
            "url": u, "title": title, "summary": summ, "category": cat,
            "story_key": slugify(title), "image": img, "month": month,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        if u in added_urls:
            print(f"  • already in selection: {title[:60]}")
        else:
            sel["added"].append(item)
            added_urls.add(u)
            print(f"  ✓ added [{cat}] {title[:60]}  img={'yes' if img else 'NO'}")
        if u not in sel["starred"]:
            sel["starred"].append(u)
        if u not in learn_urls:
            learn.append({
                "title": title, "category": cat, "summary": (summ or "")[:200],
                "url": u, "month": month, "source": "added",
            })
            learn_urls.add(u)

    sel_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LEARN_FILE.write_text(json.dumps(learn[-200:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"selection now: {len(sel['added'])} added, {len(sel['starred'])} starred; taste: {len(learn)}")


if __name__ == "__main__":
    main()
