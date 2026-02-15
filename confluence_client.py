# confluence_client.py
import os
import re
import httpx

CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "")
CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME", "")
CONFLUENCE_PASSWORD = os.getenv("CONFLUENCE_API_TOKEN", "")


class ConfluenceNotConfigured(Exception):
    pass


async def search_confluence_raw(query: str, limit: int = 10, offset: int = 0) -> dict:
    """
    Низкоуровневый вызов Confluence Search API, возвращает JSON как есть.
    """
    if not CONFLUENCE_BASE_URL:
        raise ConfluenceNotConfigured("CONFLUENCE_BASE_URL is not configured")

    limit = min(limit, 50)
    cql_query = f'text ~ "{query}"'

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{CONFLUENCE_BASE_URL}/rest/api/content/search",
            params={
                "cql": cql_query,
                "limit": limit,
                "start": offset,
                "expand": "body.view",
            },
            auth=(CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD),
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()

