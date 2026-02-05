from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import os
import re
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
            title = item.get("pageTitle", "")
            print(f"📄 DEBUG: Processing item: {title}")  # DEBUG 4
            url = item.get("url", "")
            page_html = ""
            
            # Получаем полное имя и готовим иерархический путь
            page_full_name = item.get('pageFullName', '')
            print(f"🔍 DEBUG: Fetching full content for pageFullName='{page_full_name}'")
            
            # --- ЖЕСТКИЙ БЛОК ОБРАБОТКИ ---
            import re
            # 1. Принудительно удаляем .WebHome в любом регистре через регулярку
            temp_name = re.sub(r'\.webhome$', '', page_full_name, flags=re.IGNORECASE)
            
            # 2. Разбиваем по точкам, фильтруем пустые части и кодируем каждую отдельно
            path_parts = [quote(p.strip(), safe='') for p in temp_name.split('.') if p.strip()]
            
            # 3. Собираем иерархию через /pages/
            encoded_path = "/pages/".join(path_parts)
            # ------------------------------
            
            # Используй pageFullName напрямую, просто удали .WebHome
            page_name_only = re.sub(r'\.webhome$', '', page_full_name, flags=re.IGNORECASE)
            request_url = f"{XWIKI_BASE_URL}/rest/wikis/xwiki/spaces/{quote(page_name_only, safe='')}/pages/WebHome"
            print(f"🔗 DEBUG: Requested URL = {request_url}")
            
            try:
                # Попытаемся получить полный контент страницы отдельным запросом
                page_resp = await client.get(
                    request_url,
                    auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
                    follow_redirects=True
                )
                
                if page_resp.status_code == 200:
                    page_html = page_resp.text
                    print(f"✅ DEBUG: Got page_html, length={len(page_html)}")
                else:
                    print(f"⚠️ DEBUG: page_resp.status_code = {page_resp.status_code}")
                    if page_resp.status_code == 404:
                        print(f"❌ DEBUG: Page not found (404): {request_url}")
                        print(f"📄 DEBUG: page_resp.text = '{page_resp.text[:100]}'")
                        page_html = ""
            except Exception as e:
                print(f"❌ ERROR: Failed to fetch page content for '{page_full_name}': {e}")
                page_html = ""
                
            # Fallback: если полный контент не достали — используем snippet из поиска
            excerpt = item.get("excerpt", "")
            content = item.get("content", "")
            print(f"📄 DEBUG: excerpt='{excerpt[:50]}...', content='{content[:50]}...'") # DEBUG
            snippet = page_html or excerpt or content
            print(f"📦 DEBUG: final snippet length={len(snippet)}, content='{snippet[:100]}...'") # DEBUG
            
            # 1. Clean data first
            print(f"🧹 DEBUG: BEFORE regex - snippet length={len(snippet)}") # DEBUG
            clean_text = re.sub(r"<[^>]+>", " ", snippet)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            print(f"🧹 DEBUG: AFTER regex - clean_text length={len(clean_text)}")  # DEBUG
    
            # 2. Guard clause: Skip invalid data early
            if not clean_text:
                print(f"⚠️ DEBUG: clean_text is EMPTY for {title}")  # DEBUG 5
                continue
    
            # 3. Specific operation block
            try:
            # We only wrap the object creation and appending
                new_result = SearchResult(
                    title=title,
                    url=url,
                    excerpt=clean_text
                )
                results.append(new_result)
                print(f"✅ DEBUG: Added result: {title}")  # DEBUG 6
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
    if request.knowledge_id == "xwiki":
        results = await search_xwiki(
            request.query,
            limit=request.retrieval_setting.top_k,
            offset=0
        )
    elif request.knowledge_id == "confluence":
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
        records.append({
            "metadata": {
                "path": result.url,
                "description": result.title
            },
            "score": 1.0,
            "title": result.title,
            "content": result.excerpt
        })
    
    return {"records": records}
