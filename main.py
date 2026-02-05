from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import os
import re
from typing import Optional, List, Dict

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
                return []
            
            data = response.json()
            results: List[SearchResult] = []
            
            for item in data.get("searchResults", []):
                title = item.get("pageTitle", "")
                url = item.get("url", "")
                page_html = ""
            try:
                # попытаемся получить ПОЛНЫЙ контент страницы отдельным запросом
                page_resp = await client.get(
                    f"{XWIKI_BASE_URL}/xwiki/rest/wikis/xwiki/pages/{item.get('pageFullName', '')}/content",
                    auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
                    follow_redirects=True
                )
                if page_resp.status_code == 200:
                    page_html = page_resp.text
            except Exception:
                page_html = ""
            
            # Fallback: если полный контент не достали — используем snippet из поиска
            snippet = page_html or item.get("excerpt", "") or item.get("content", "")
            
            # 1. Clean data first
            clean_text = re.sub(r"<[^>]+>", " ", snippet)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()

            # 2. Guard clause: Skip invalid data early
            if not clean_text:
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
            except Exception as e:
            # Logging the error helps you know WHY it failed
                print(f"Failed to process result: {e}")
                continue

            # 4. Return results ONLY after the loop finishes
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
