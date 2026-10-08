from __future__ import annotations

import html
import re
from urllib.parse import unquote, urlparse

import httpx

from app.constants import HEADERS, WEB_SEARCH_RESULTS, WEB_SEARCH_TIMEOUT, WEB_SEARCH_URL

ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
HREF = re.compile(r'href="([^"]+)"', re.I)
TAG = re.compile(r"<[^>]+>")
SEARCH_HEADERS = {**HEADERS, "Accept": "text/html"}


def clean_text(value: str) -> str:
    text = html.unescape(TAG.sub(" ", value))
    return re.sub(r"\s+", " ", text).strip()


def page_url(href: str) -> str:
    decoded = html.unescape(href)
    match = re.search(r"[?&]uddg=([^&]+)", decoded)
    if match:
        return unquote(match.group(1))
    return decoded


def read_results(page: str) -> list[dict]:
    titles = []
    snippets = []
    for attrs, body in ANCHOR.findall(page):
        href_match = HREF.search(attrs)
        href = href_match.group(1) if href_match else ""
        text = clean_text(body)
        if "result__a" in attrs:
            titles.append((href, text))
        elif "result__snippet" in attrs:
            snippets.append(text)
    found = []
    for index, (href, title) in enumerate(titles):
        url = page_url(href)
        host = urlparse(url).netloc
        if not title or not host or "duckduckgo.com" in host:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        found.append({"title": title, "url": url, "snippet": snippet[:400]})
        if len(found) >= WEB_SEARCH_RESULTS:
            break
    return found


def web_search(query: str) -> list[dict]:
    text = " ".join(query.split())
    if not text:
        return []
    try:
        with httpx.Client(timeout=WEB_SEARCH_TIMEOUT, headers=SEARCH_HEADERS, follow_redirects=True) as client:
            response = client.post(WEB_SEARCH_URL, data={"q": text[:400]})
            response.raise_for_status()
    except Exception:
        return []
    return read_results(response.text)


def search_notes(pages: list[dict]) -> str:
    if not pages:
        return "none"
    lines = []
    for page in pages:
        snippet = page["snippet"] or "No snippet."
        lines.append(f"- {page['title']} ({page['url']}): {snippet}")
    return "\n".join(lines)
