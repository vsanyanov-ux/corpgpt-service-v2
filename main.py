from fastapi import FastAPI, HTTPException, Query
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
async def retrieval(query: str = Query(...), top_k: int = Query(10), page: int = Query(1)):
    """CorpGPT External Knowledge endpoint"""
    results = await search_confluence(query, limit=top_k, offset=0)
    
    records = []
    for result in results:
        records.append({
            "score": 1.0,
            "metadata": {
                "title": result.title,
                "source": result.url
            },
            "content": result.excerpt
        })
    
    return {"records": records}
