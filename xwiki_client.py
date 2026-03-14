import os
import re
import json
import logging
from typing import List, Dict, Any

import httpx
import requests
from json.decoder import JSONDecodeError

logger = logging.getLogger(__name__)

# ========= ENV =========

XWIKI_BASE_URL = os.getenv("XWIKI_BASE_URL", "")
XWIKI_USERNAME = os.getenv("XWIKI_USERNAME", "")
XWIKI_PASSWORD = os.getenv("XWIKI_PASSWORD", "")

XWIKI_EXPORT_URL = os.getenv("XWIKI_EXPORT_URL", "")

# ========= CHUNKING =========

MAX_CHARS = 2000
OVERLAP_CHARS = 300  # размер overlap рекомендуется 10-20%


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + max_chars, n)

        cut = text.rfind("\\n", start, end)
        if cut == -1:
            cut = text.rfind(". ", start, end)
        if cut == -1 or cut <= start + max_chars * 0.5:
            cut = end

        chunk = text[start:cut].strip()
        if chunk:
            chunks.append(chunk)

        if cut >= n:
            break

        # ключевая строчка: шаг с overlap
        start = max(cut - overlap, 0)

    return chunks

# ========= EXPORT =========


def fetch_xwiki_export() -> List[Dict[str, Any]]:
    """
    Тянет JSON-экспорт XWiki из XWIKI_EXPORT_URL.
    Возвращает список страниц (raw_pages), как у тебя сейчас в indexer.py
    """
    if not XWIKI_EXPORT_URL:
        return []

    auth = (XWIKI_USERNAME, XWIKI_PASSWORD) if XWIKI_USERNAME and XWIKI_PASSWORD else None
    resp = requests.get(XWIKI_EXPORT_URL, timeout=10, auth=auth)
    resp.raise_for_status()

    text = resp.text
    print("XWIKI_EXPORT raw first 200:", repr(text[:200]))

    try:
        raw_pages = json.loads(text)
    except JSONDecodeError as e:
        print("XWIKI_EXPORT: strict JSON parse error:", e)
        try:
            raw_pages = json.loads(text, strict=False)
            print("XWIKI_EXPORT: parsed with strict=False fallback")
        except JSONDecodeError as e2:
            print("XWIKI_EXPORT: fallback JSON parse error:", e2)
            return []

    print(f"XWIKI_EXPORT: total pages = {len(raw_pages)}")
    return raw_pages

# ========= SEARCH (RAW REST) =========


async def search_xwiki_raw(query: str, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Низкоуровневый поиск по XWiki REST API.
    Возвращает список raw-объектов из 'searchResults' (как есть).
    """
    if not XWIKI_BASE_URL:
        raise RuntimeError("XWIKI_BASE_URL is not configured")

    limit = min(limit, 50)
    print(f"🔍 DEBUG: Searching for '{query}' with limit {limit}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{XWIKI_BASE_URL}/rest/wikis/xwiki/search",
            params={
                "q": query,
                "number": limit,
                "start": offset,
                "scope": "name,content",
            },
            headers={"Accept": "application/json"},
            auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
            follow_redirects=True,
        )

        if response.status_code != 200:
            print(f"❌ DEBUG: Bad response code {response.status_code}")
            return []

        data = response.json()
        print(f"✅ DEBUG: Got {len(data.get('searchResults', []))} results from API")
        return data.get("searchResults", [])

# ========= SEARCH (ENRICHED) =========


async def enrich_xwiki_results(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Принимает raw searchResults, тянет HTML для каждой страницы,
    чистит его и возвращает список dict с полями:
    { 'title': ..., 'url': ..., 'text': ... }.
    """
    results: List[Dict[str, Any]] = []

    if not raw_items:
        return results

    async with httpx.AsyncClient(timeout=30.0) as client:
        for item in raw_items:
            title = item.get("title") or item.get("FullName") or ""
            links = item.get("links") or []
            url = ""
            if links:
                url = links[0].get("href") or ""

            print(f"📄 DEBUG: Processing item: {title}")
            page_html = ""

            # 1. Строим рабочий bin/view URL
            view_url = ""
            hierarchy = (item.get("hierarchy") or {}).get("items") or []
            if hierarchy:
                view_url = hierarchy[-1].get("url") or ""

            if not view_url:
                space_path = item.get("space", "")
                page_name = item.get("pageName", "WebHome")
                space_path_slash = "/".join(space_path.split(".")) if space_path else ""
                if space_path_slash:
                    view_url = f"{XWIKI_BASE_URL}/bin/view/{space_path_slash}/"
                else:
                    view_url = f"{XWIKI_BASE_URL}/bin/view/{page_name}"

            # 2. Тянем HTML и чистим его
            if view_url:
                try:
                    print(f"🌐 DEBUG: view_url='{view_url}'")
                    page_resp = await client.get(
                        view_url,
                        auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
                        follow_redirects=True,
                    )
                    if page_resp.status_code == 200:
                        html = page_resp.text

                        match = re.search(
                            r"<!--XWikiContent-->(.*)<!--XWikiEndContent-->",
                            html,
                            re.DOTALL,
                        )
                        if match:
                            main_html = match.group(1)
                        else:
                            main_html = html

                        content_match = re.search(
                            r'<div[^>]+class="[^"]*(xwikidoccontent|xwiki-content|contentinner)[^"]*"[^>]*>(.*)</div>',
                            main_html,
                            re.DOTALL | re.IGNORECASE,
                        )
                        if content_match:
                            article_html = content_match.group(2)
                        else:
                            p_match = re.search(
                                r"<p[^>]*>.*</p>",
                                main_html,
                                re.DOTALL | re.IGNORECASE,
                            )
                            if p_match:
                                article_html = p_match.group(0)
                            else:
                                article_html = main_html

                        page_html = re.sub(r"<[^>]+>", " ", article_html)
                        page_html = re.sub(r"\\\\s+", " ", page_html).strip()
                        print(f"📄 DEBUG: view_html_len={len(page_html)}")

                        cut_markers = [
                            "Комментарии (",
                            "Annotations (",
                            "History ",
                            "Attachments (",
                            "Export Choose the export format",
                            "Toggle the left panel column",
                        ]
                        for marker in cut_markers:
                            idx = page_html.find(marker)
                            if idx != -1:
                                page_html = page_html[:idx].strip()
                                break

                        sentences = []
                        for part in page_html.split("."):
                            s = part.strip()
                            if len(s) < 10:
                                continue
                            if not re.search(r"[А-Яа-я]", s):
                                continue
                            sentences.append(s)

                        if sentences:
                            page_html = ". ".join(sentences).strip()
                    else:
                        print(f"❌ DEBUG: view_url status={page_resp.status_code}")
                        page_html = ""
                except Exception as e:
                    print(f"❌ ERROR: Failed to fetch view_url '{view_url}': {e}")
                    page_html = ""
            else:
                print("⚠️ DEBUG: view_url is empty, skip HTML fetch")

            excerpt = item.get("excerpt") or ""
            content = item.get("content") or ""

            print(
                f"📄 DEBUG: excerpt_len={len(excerpt)}, content_len={len(content)}, title='{title}'"
            )
            print(
                f"📄 DEBUG: raw excerpt='{excerpt[:80]}', raw content='{content[:80]}'"
            )

            snippet = page_html or excerpt or content or title
            print(
                f"📦 DEBUG: final snippet length={len(snippet)}, content_preview='{snippet[:100]}'"
            )

            if not snippet.strip():
                print(f"⚠️ DEBUG: snippet is EMPTY for '{title}' – skipping item")
                continue

            print(f"🧹 DEBUG: BEFORE regex - snippet length={len(snippet)}")
            source_text = page_html or excerpt or content or title

            clean_text = re.sub(r"<[^>]+>", " ", source_text)
            clean_text = re.sub(r"\\s+", " ", clean_text).strip()
            print(
                f"🧹 DEBUG: AFTER regex - clean_text length={len(clean_text)}"
            )

            MAX_LEN = 10000
            if len(clean_text) > MAX_LEN:
                clean_text = clean_text[:MAX_LEN]

            if not clean_text:
                raw_fallback = (excerpt or content or title).strip()
                if raw_fallback:
                    clean_text = raw_fallback
                else:
                    print(f"⚠️ DEBUG: clean_text is EMPTY for '{title}' – skipping item")
                    continue

            results.append(
                {
                    "title": title,
                    "url": url,
                    "text": clean_text,
                }
            )
            print(f"✅ DEBUG: Added result: {title}")

    print(f"🏁 DEBUG: Returning {len(results)} enriched results")
    return results
