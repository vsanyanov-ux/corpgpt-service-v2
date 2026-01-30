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
                    print(f"DEBUG Full response: {data}")
                    print(f"DEBUG Results count: {len(data.get('results', []))}")
            
            
            for result in data.get("results", [])[:limit]:
                                # DEBUG: Log raw Confluence API response
                                print(f"DEBUG keys: {list(result.keys())}")
                                print(f"DEBUG title: {result.get('title', 'NO_TITLE')}")
                                print(f"DEBUG excerpt: {result.get('excerpt', 'NO_EXCERPT')[:100]}")
                                print(f"DEBUG Body.view exists: {'body' in result and 'view' in result.get('body', {})}")
                                if 'body' in result and 'view' in result.get('body', {}):
                                                        view_value = result['body']['view'].get('value', '')
                                                        print(f"DEBUG Body.view.value length: {len(view_value)}")
                                                        print(f"DEBUG Body.view.value preview (first 200 chars): {view_value[:200]}")
                                    
                                    
                                
                    excerpt = result.get("excerpt", "")[:200]
                    results.append(SearchResult(
                        title=result.get("title", ""),
                        url=result.get("_links", {}).get("webui", ""),
                        excerpt=excerpt
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
async def retrieval(request: RetrievalRequest):
    """CorpGPT External Knowledge endpoint"""
    top_k = request.retrieval_setting.top_k
    results = await search_confluence(request.query, limit=top_k, offset=0)
    
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
