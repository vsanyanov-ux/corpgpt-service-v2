from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import os
import re
import requests
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict
from urllib.parse import quote

app = FastAPI()

# Load environment variables
Confluence_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "")
Confluence_USERNAME = os.getenv("CONFLUENCE_USERNAME", "")
Confluence_PASSWORD = os.getenv("CONFLUENCE_API_TOKEN", "")

XWIKI_BASE_URL = os.getenv("XWIKI_BASE_URL", "")
XWIKI_USERNAME = os.getenv("XWIKI_USERNAME", "")
XWIKI_PASSWORD = os.getenv("XWIKI_PASSWORD", "")

XWIKI_EXPORT_URL = os.getenv(
    "XWIKI_EXPORT_URL",
    "http://158.255.1.153:8080/bin/view/Tech/CorpGPTExport/?outputSyntax=plain&xpage=plain"
)

print(f"DEBUG: Confluence_BASE_URL = {Confluence_BASE_URL}")

# CorpGPT Request Model
class RetrievalSettings(BaseModel):
    top_k: int = 10
    score_threshold: float = 0.5

class RetrievalRequest(BaseModel):
    knowledge_id: str
    query: str
    retrieval_setting: RetrievalSettings = RetrievalSettings()

class SearchResult(BaseModel):
    title: str
    url: str
    excerpt: str

# ===== XWiki FAQ export (CorpGPT) =====

MAX_CHARS = 1200  # размер чанка, потом подберём

def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        cut = text.rfind("\n", start, end)
        if cut == -1:
            cut = text.rfind(". ", start, end)
        if cut == -1 or cut <= start + max_chars * 0.5:
            cut = end
        chunks.append(text[start:cut].strip())
        start = cut
    return chunks

import json
import string

def fetch_xwiki_export() -> list[dict]:
    if not XWIKI_EXPORT_URL:
        return []

    auth = None
    if XWIKI_USERNAME and XWIKI_PASSWORD:
        auth = (XWIKI_USERNAME, XWIKI_PASSWORD)

    resp = requests.get(XWIKI_EXPORT_URL, timeout=10, auth=auth)
    resp.raise_for_status()

    pages = resp.json()
    print(f"XWIKI_EXPORT: got {len(pages)} pages")
    return pages


async def search_confluence(query: str, limit: int = 10, offset: int = 0) -> List[SearchResult]:
    """Search Confluence with pagination"""
    if not Confluence_BASE_URL:
        raise HTTPException(status_code=500, detail="Confluence_BASE_URL is not configured")
    
    limit = min(limit, 50)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            cql_query = f'text ~ "{query}"'
            
            response = await client.get(
                f"{Confluence_BASE_URL}/rest/api/content/search",
                params={
                    "cql": cql_query,
                    "limit": limit,
                    "start": offset,
                    "expand": "body.view"
                },
                auth=(Confluence_USERNAME, Confluence_PASSWORD),
                follow_redirects=True
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            results = []
            
            for result in data.get("results", [])[:limit]:
                # Get full content from body.view.value instead of short excerpt
                body_html = result.get('body', {}).get('view', {}).get('value', '')
                
                # Clean HTML tags to get plain text
                clean_text = re.sub('<[^<]+?>', '', body_html)
                # Remove extra whitespace
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                
                # Use full cleaned text (not just 200 chars)
                content = clean_text if clean_text else result.get("excerpt", "")
                
                try:
                    results.append(SearchResult(
                        title=result.get("title", ""),
                        url=result.get("_links", {}).get("webui", ""),
                        excerpt=content
                    ))
                except Exception:
                    continue
            
            return results
        
    except Exception as e:
        return []

async def search_xwiki(query: str, limit: int = 10, offset: int = 0) -> List[SearchResult]:
    """Search XWiki using its REST API."""
    if not XWIKI_BASE_URL:
        raise HTTPException(status_code=500, detail="XWIKI_BASE_URL is not configured")
    
    limit = min(limit, 50)
    print(f"🔍 DEBUG: Searching for '{query}' with limit {limit}")  # DEBUG 1
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{XWIKI_BASE_URL}/rest/wikis/xwiki/search",
            params={
                "q": query,
                "number": limit,
                "start": offset,
                "scope": "name,content"
            },
            headers={"Accept": "application/json"},
            auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
            follow_redirects=True
        )
            
        if response.status_code != 200:
            print(f"❌ DEBUG: Bad response code {response.status_code}")  # DEBUG 2
            return []
            
        data = response.json()
        print(f"✅ DEBUG: Got {len(data.get('searchResults', []))} results from API")  # DEBUG 3        

        results: List[SearchResult] = []
            
        for item in data.get("searchResults", []):
            title = item.get("title") or item.get("FullName") or ""
            links = item.get("links") or []
            url = ""
            if links:
                url = links[0].get("href") or ""
        
            print(f"📄 DEBUG: Processing item: {title}")  # DEBUG 4
            page_html = ""

            # 1. Строим рабочий bin/view URL
            view_url = ""
            hierarchy = (item.get("hierarchy") or {}).get("items") or []
            if hierarchy:
                # Обычно последний элемент — документ с корректным bin/view URL
                view_url = hierarchy[-1].get("url") or ""
            
            # Fallback: конструируем из space и pageName, если в hierarchy нет url
            if not view_url:
                space_path = item.get("space", "")  # "Оборудование.FAQ.Как проверить статус крана?"
                page_name = item.get("pageName", "WebHome")
                # space_path в bin/view — через /
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
                        follow_redirects=True
                    )
                    if page_resp.status_code == 200:
                        html = page_resp.text

                        # 1) Сначала пробуем вырезать блок между <!--XWikiContent--> ... <!--XWikiEndContent-->
                        match = re.search(r"<!--XWikiContent-->(.*)<!--XWikiEndContent-->", html, re.DOTALL)
                        if match:
                            main_html = match.group(1)
                        else:
                            main_html = html
                        
                        # 2) Внутри main_html пытаемся найти div с основным содержимым
                        content_match = re.search(
                            r'<div[^>]+class="[^"]*(xwikidoccontent|xwiki-content|contentinner)[^"]*"[^>]*>(.*)</div>',
                            main_html,
                            re.DOTALL | re.IGNORECASE
                        )
                        if content_match:
                            article_html = content_match.group(2)
                        else:
                            # если не нашли – хотя бы отрежем шапку и подвал по первому и последнему <p>
                            p_match = re.search(r"<p[^>]*>.*</p>", main_html, re.DOTALL | re.IGNORECASE)
                            if p_match:
                                article_html = p_match.group(0)
                            else:
                                article_html = main_html
                        
                        # 3) Грубая очистка HTML → простой текст
                        page_html = re.sub(r"<[^>]+>", " ", article_html)
                        page_html = re.sub(r"\\s+", " ", page_html).strip()
                        print(f"📄 DEBUG: view_html_len={len(page_html)}")
                        
                        # 4) Обрезаем типичные хвосты интерфейса, если они есть
                        cut_markers = [
                            "Комментарии (", "Annotations (", "History ", "Attachments (",
                            "Export Choose the export format", "Toggle the left panel column"
                        ]
                        for marker in cut_markers:
                            idx = page_html.find(marker)
                            if idx != -1:
                                page_html = page_html[:idx].strip()
                                break 

                        # 5) Дополнительная фильтрация: оставляем строки с осмысленным текстом
                        sentences = []
                        for part in page_html.split("."):
                            s = part.strip()
                            # отбрасываем слишком короткие и «технические» куски
                            if len(s) < 10:
                                continue
                            # игнорируем строки без кириллицы (меню/английский UI)
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

            
                
            # Fallback: если полный контент не достали — используем snippet из поиска            
            excerpt = item.get("excerpt") or ""
            content = item.get("content") or ""
            
            print(f"📄 DEBUG: excerpt_len={len(excerpt)}, content_len={len(content)}, title='{title}'")
            print(f"📄 DEBUG: raw excerpt='{excerpt[:80]}', raw content='{content[:80]}'")
            
            snippet = page_html or excerpt or content or title
            print(f"📦 DEBUG: final snippet length={len(snippet)}, content_preview='{snippet[:100]}'")

            
            # Если и после этого пусто — не рубим весь ответ, а просто скипаем этот item
            if not snippet.strip():
                print(f"⚠️ DEBUG: snippet is EMPTY for '{title}' – skipping item")
                continue
            
            # 1. Clean data first
            print(f"🧹 DEBUG: BEFORE regex - snippet length={len(snippet)}")
            source_text = page_html or excerpt or content or title

            clean_text = re.sub(r"<[^>]+>", " ", source_text)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            print(f"🧹 DEBUG: AFTER regex - clean_text length={len(clean_text)}")
            
            MAX_LEN = 10000  # например
            if len(clean_text) > MAX_LEN:
                clean_text = clean_text[:MAX_LEN]

            
            # 2. Guard clause: Skip invalid data early
            if not clean_text:
                raw_fallback = (excerpt or content or title).strip()
                if raw_fallback:
                    clean_text = raw_fallback
                else:
                    print(f"⚠️ DEBUG: clean_text is EMPTY for '{title}' – skipping item")
                    continue   
            
    
            # 3. Specific operation block
            try:
                # Подстрахуемся: если title пустой, используем page_full_name
                safe_title = title or page_full_name
            
                # We only wrap the object creation and appending
                new_result = SearchResult(
                    title=safe_title,
                    url=url,
                    excerpt=clean_text  # здесь уже именно clean_text
                )
                results.append(new_result)
                print(f"✅ DEBUG: Added result: {safe_title}")  # DEBUG 6
            except Exception as e:
                print(f"❌ DEBUG: Error creating result: {e}")  # DEBUG 7
                # Logging the error helps you know WHY it failed
                print(f"Failed to process result: {e}")
                continue


        # 4. Return results ONLY after the loop finishes
        print(f"🏁 DEBUG: Returning {len(results)} results")  # DEBUG 8
        return results

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Confluence Search API",
        "confluence_configured": bool(Confluence_BASE_URL)
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/retrieval")
async def retrieval(request: RetrievalRequest):
    """CorpGPT External Knowledge endpoint"""

    # XWIKI: берём готовый JSON-экспорт и режем на чанки
    if request.knowledge_id == "xwiki":
        pages = fetch_xwiki_export()
        records = []

        for page in pages:
            base_meta = {
                "path": page.get("url", ""),
                "description": page.get("title", ""),
                "space": page.get("space", ""),
                "name": page.get("name", ""),
                "updated": page.get("updated"),
            }
            for i, chunk in enumerate(chunk_text(page.get("content", ""))):
                records.append({
                    "metadata": {
                        **base_meta,
                        "chunk_index": i,
                    },
                    "score": 1.0,
                    "title": page.get("title", ""),
                    "content": chunk,
                })

        return {"records": records}

    # Остальные — как раньше
    if request.knowledge_id == "confluence":
        results = await search_confluence(
            request.query,
            limit=request.retrieval_setting.top_k,
            offset=0
        )
    else:
        results = await search_confluence(
            request.query,
            limit=request.retrieval_setting.top_k,
            offset=0
        )

    records = []
    for result in results:
        text = result.excerpt
        print(f"🧪 DEBUG RAW CONTENT (len={len(text)}): {text}")
        records.append({
            "metadata": {
                "path": result.url,
                "description": result.title
            },
            "score": 1.0,
            "title": result.title,
            "content": text
        })

    return {"records": records}

