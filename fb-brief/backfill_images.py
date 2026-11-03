#!/usr/bin/env python3
"""
Backfill missing article images in a monthly selection file.

For every article in fb-brief/monthly/selection-<MONTH>.json whose "image"
field is empty, fetch the article page and extract its og:image (or
twitter:image) and store it. Failures are skipped (one attempt per article,
hard timeout) so a single bad URL never stalls the run.

Also mirrors any discovered image into links.json (matched by URL) when that
entry's image is empty, so both data sources stay consistent.

Usage:  python fb-brief/backfill_images.py <MONTH>     e.g. 2026-09
Runs on the GitHub Actions runner (open internet); this repo's cloud session
cannot reach news hosts directly.
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error

MONTH = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MONTH", "")
if not re.fullmatch(r"\d{4}-\d{2}", MONTH or ""):
    print(f"✗ bad or missing MONTH argument: {MONTH!r} (expected YYYY-MM)")
    sys.exit(2)

MON_DIR = os.path.join(os.path.dirname(__file__), "monthly")
SEL_PATH = os.path.join(MON_DIR, f"selection-{MONTH}.json")
LINKS_PATH = os.path.join(MON_DIR, "links.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

OG_PATTERNS = [
    r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::url)?["\']',
    r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
]


def _fetch(url, timeout=18):
    """GET a URL following redirects; return (final_url, html_text)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        final = r.geturl()
        raw = r.read(1_500_000)  # cap: og tags live in the <head>
    return final, raw.decode("utf-8", "ignore")


def _abs_image(src, page_url):
    src = (src or "").strip().replace("&amp;", "&")
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    m = re.match(r"(https?://[^/]+)", page_url or "")
    if src.startswith("/") and m:
        return m.group(1) + src
    return src


def _extract_og(html, page_url):
    for pat in OG_PATTERNS:
        m = re.search(pat, html, re.I)
        if m:
            img = _abs_image(m.group(1), page_url)
            if img.startswith("http"):
                return img
    return ""


def resolve_image(url):
    """Best-effort image for an article URL. Handles Google News redirect
    wrappers by following redirects to the real publisher page. Returns an
    image URL or "" (caller skips on "")."""
    final, html = _fetch(url)
    host = re.sub(r"^https?://", "", final).split("/")[0].lower()

    # Google News wrapper that didn't bounce to a publisher: try to find the
    # real article link inside, else give up (skip).
    if "news.google.com" in host or "google.com" in host:
        m = re.search(r'<a[^>]+href=["\'](https?://(?!news\.google|www\.google|google\.)[^"\']+)', html, re.I)
        if not m:
            m = re.search(r'data-n-au=["\'](https?://[^"\']+)', html, re.I)
        if m:
            try:
                final, html = _fetch(m.group(1))
            except Exception:
                return ""
        else:
            return ""
    return _extract_og(html, final)


def main():
    if not os.path.exists(SEL_PATH):
        print(f"✗ no selection file: {SEL_PATH}")
        sys.exit(1)
    sel = json.load(open(SEL_PATH, encoding="utf-8"))
    links = {}
    if os.path.exists(LINKS_PATH):
        try:
            links = json.load(open(LINKS_PATH, encoding="utf-8"))
        except Exception:
            links = {}
    # url -> list of links.json keys (to mirror image back)
    url2keys = {}
    for k, p in links.items():
        u = (p.get("url") or "").strip()
        if u:
            url2keys.setdefault(u, []).append(k)

    added = sel.get("added", [])
    todo = [it for it in added if not (it.get("image") or "").strip()]
    print(f"month {MONTH}: {len(added)} article(s), {len(todo)} missing image\n")

    filled, skipped = 0, 0
    for i, it in enumerate(todo, 1):
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "")[:60]
        if not url:
            print(f"[{i:02d}/{len(todo)}] SKIP (no url) — {title}")
            skipped += 1
            continue
        try:
            img = resolve_image(url)
        except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:  # noqa: BLE001
            print(f"[{i:02d}/{len(todo)}] SKIP ({type(e).__name__}: {str(e)[:70]}) — {title}")
            skipped += 1
            continue
        if not img:
            print(f"[{i:02d}/{len(todo)}] SKIP (no og:image found) — {title}")
            skipped += 1
            continue
        it["image"] = img
        filled += 1
        # mirror into links.json entries sharing this url, if empty
        for k in url2keys.get(url, []):
            if not (links[k].get("image") or "").strip():
                links[k]["image"] = img
        print(f"[{i:02d}/{len(todo)}] ✓ {title}\n         {img[:100]}")

    if filled:
        sel["updated_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        json.dump(sel, open(SEL_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        if links:
            json.dump(links, open(LINKS_PATH, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)

    print(f"\n✅ done — filled {filled}, skipped {skipped} "
          f"(of {len(todo)} missing). {len(added) - len(todo) + filled}/"
          f"{len(added)} now have images.")


if __name__ == "__main__":
    main()
