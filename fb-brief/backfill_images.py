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
    """GET a URL following redirects; return (final_url, html_text).
    Sends a full set of browser headers — many publishers (e.g. fooddive)
    return 403 to a bare urllib User-Agent."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
        "Accept-Encoding": "identity",
        "Referer": "https://www.google.com/",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Upgrade-Insecure-Requests": "1",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        final = r.geturl()
        raw = r.read(1_500_000)  # cap: og tags live in the <head>
    return final, raw.decode("utf-8", "ignore")


_ICON_HINTS = ("logo", "icon", "favicon", "sprite", "avatar", "placeholder",
               "1x1", "pixel", "spacer", "/ads/", "doubleclick")


def _good_img(u):
    u = (u or "").strip().rstrip(").,;'\"")
    if not u.startswith("http"):
        return ""
    low = u.lower()
    if low.endswith(".svg") or low.endswith(".gif"):
        return ""
    if any(h in low for h in _ICON_HINTS):
        return ""
    return u


def _jina_image(url, timeout=28):
    """Fallback: ask the r.jina.ai reader (its own fetcher + redirect follow)
    for the page and pull the best image out of what it returns. Recovers
    bot-blocked publishers and Google News redirect wrappers."""
    try:
        req = urllib.request.Request("https://r.jina.ai/" + url, headers={
            "User-Agent": UA,
            "X-With-Images-Summary": "true",
            "X-Return-Format": "markdown",
        })
        txt = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""
    cands = re.findall(r'!\[[^\]]*\]\((https?://[^)\s]+)', txt)
    cands += re.findall(r'https?://[^\s)"\']+\.(?:jpg|jpeg|png|webp)(?:\?[^\s)"\']*)?', txt)
    for c in cands:
        g = _good_img(c)
        if g:
            return g
    return ""


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
    """Best-effort image for an article URL. Tries a direct fetch + og:image
    first (handling Google News redirect wrappers), then falls back to the
    r.jina.ai reader for bot-blocked pages and unresolved wrappers. Returns an
    image URL or "" (caller skips on "")."""
    try:
        final, html = _fetch(url)
        host = re.sub(r"^https?://", "", final).split("/")[0].lower()
        if "news.google.com" in host or "google.com" in host:
            # Wrapper page: look for the real publisher link inside.
            m = re.search(r'<a[^>]+href=["\'](https?://(?!news\.google|www\.google|google\.)[^"\']+)', html, re.I)
            if not m:
                m = re.search(r'data-n-au=["\'](https?://[^"\']+)', html, re.I)
            if m:
                final, html = _fetch(m.group(1))
                img = _extract_og(html, final)
                if img:
                    return img
        else:
            img = _extract_og(html, final)
            if img:
                return img
    except Exception:  # noqa: BLE001  (403s, timeouts → fall through to reader)
        pass
    # Fallback: reader service (follows redirects, bypasses most bot walls).
    return _jina_image(url)


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
