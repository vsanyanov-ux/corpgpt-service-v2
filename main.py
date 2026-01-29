from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import httpx
import os
from typing import Optional, List

app = FastAPI()

XWIKI_BASE_URL = os.getenv("XWIKI_BASE_URL", "https://anianov.atlassian.net/wiki/home")
XWIKI_USERNAME = os.getenv("CONFLUENCE_USERNAME", "")
XWIKI_PASSWORD = os.getenv("CONFLUENCE_API_TOKEN", "")

class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    offset: int = 0

class SearchResult(BaseModel):
    title: str
    url: str
    excerpt: str

async def search_confluence(query: str, limit: int = 10, offset: int = 0) -> List[SearchResult]:
    """Search Confluence/XWiki with pagination"""
    limit = min(limit, 50)  # Max 50 results
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            cql_query = f'text ~ "{query}"'
            
            response = await client.get(
                f"{XWIKI_BASE_URL}/rest/api/content/search",
                params={
                    "cql": cql_query,
                    "limit": limit,
                    "start": offset,
                    "expand": "body.view"
                },
                auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
                follow_redirects=True
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Search failed")
            
            data = response.json()
            results = []
            
            for result in data.get("results", [])[:limit]:
                try:
                    excerpt = result.get("excerpt", "")[:200]
                    results.append(SearchResult(
                        title=result.get("title", ""),
                        url=result.get("_links", {}).get("webui", ""),
                        excerpt=excerpt
                    ))
                except Exception as e:
                    print(f"Error: {e}")
                    continue
            
            return results
            
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Search timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "XWiki Search Service is running"}

@app.post("/search")
async def search(
    request: SearchRequest,
    limit: Optional[int] = Query(10, ge=1, le=50),
    offset: Optional[int] = Query(0, ge=0)
):
    """Search with pagination"""
    try:
        search_limit = min(limit, 50)
        results = await search_confluence(request.query, search_limit, offset)
        
        return {
            "query": request.query,
            "results": results,
            "count": len(results),
            "limit": search_limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/retrieval")
async def retrieval(
    query: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0)
):
    """GET endpoint for retrieval"""
    try:
        results = await search_confluence(query, limit, offset)
        return {
            "query": query,
            "results": results,
            "count": len(results),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
