from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import httpx
import os
import re
from typing import Optional, List

app = FastAPI()

# Load environment variables
Confluence_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "")
Confluence_USERNAME = os.getenv("CONFLUENCE_USERNAME", "")
Confluence_PASSWORD = os.getenv("CONFLUENCE_API_TOKEN", "")

print(f"DEBUG: Confluence_BASE_URL = {Confluence_BASE_URL}")

class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    offset: int = 0

async def search_confluence(query: str, limit: int = 10, offset: int = 0) -> list: 
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
                follow_redirects=True            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            results = []
            
            for result in data.get("results", [])[:limit]:
                try:
                    # Try to get content from body.view or excerpt
                    body_text = result.get("body", {}).get("view", {}).get("value", "")
                    if body_text:
                        # Strip HTML tags and limit to 500 chars
                        excerpt = re.sub(r'<[^>]+>', '', body_text)[:500]
                    else:
                        excerpt = result.get("excerpt", "")[:200]
                    
                results.append({
                                        "score": 1.0,
                                        "metadata": {
                                                                    "title": result.get("title", ""),
                                                                    "source": result.get("_links", {}).get("webui", "")
                                                                },
                                        "content": excerpt
                ))
                                    except Exception as e:
                    print(f"Error processing result: {e}")
                    continue
            return results
            
    except httpx.TimeoutException:
        return []
    except Exception as e:
        print(f"Search error: {e}")
        return []

@app.get("/")
async def root():
    return {
        "message": "Confluence Search Service is running",
        "Confluence_configured": bool(Confluence_BASE_URL)
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/search")
async def search(request: SearchRequest):
    try:
        results = await search_confluence(request.query, request.limit, request.offset)
                return {"records": results}

@app.get("/retrieval")
async def retrieval(
    query: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0)
):
    if not query:
        return {"records": []}    
    try:
        results = await search_confluence(query, limit, offset)
                return {"records": results}
    except Exception as e:
        print(f"Retrieval error: {e}")
        return {"records": []}
@app.post("/retrieval")
async def retrieval_post(request: SearchRequest):
    try:
        results = await search_confluence(request.query, request.limit, request.offset)
        return {"records": results}    except Exception as e:
        print(f"Retrieval POST error: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
