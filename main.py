from fastapi import FastAPI, Request, HTTPException, Depends, Security
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import json
import httpx
from xml.etree import ElementTree
import os

CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
XWIKI_BASE_URL = os.getenv("XWIKI_BASE_URL", "https://anyanov.demo.xwiki.com/xwiki/rest")
WIKI_NAME = os.getenv("WIKI_NAME", "xwiki")
XWIKI_USERNAME = os.getenv("XWIKI_USERNAME", "xwiki:XWiki.VladimirAnyanov")
XWIKI_PASSWORD = os.getenv("XWIKI_PASSWORD", "Oshowiki")



def search_xwiki(query: str, top_k: int):
    url = f"{XWIKI_BASE_URL}/wikis/{WIKI_NAME}/search"
    params = {
        "q": query,
        "scope": "content",
        "number": top_k,
    }

    resp = httpx.get(
    url,
    params=params,
    auth=(XWIKI_USERNAME, XWIKI_PASSWORD),
    )
    resp.raise_for_status()
    print(resp.text)


    # По умолчанию XWiki возвращает XML SearchResults [web:3]
    root = ElementTree.fromstring(resp.content)

    records = []
    # Структура XML может отличаться, для демо берём общий пример [web:3]
    for page in root.findall(".//page"):
        title = page.findtext("title", default="") or ""
        content = page.findtext("content", default="") or ""
        full_name = page.findtext("fullName", default="") or title

        # Человекочитаемая ссылка на страницу
        view_url = f"https://anyanov.demo.xwiki.com/xwiki/bin/view/{full_name.replace('.', '/')}"

        record = {
            "metadata": {
                "path": view_url,
                "description": full_name,
            },
            # XWiki search API обычно не отдаёт числовой score, поэтому ставим заглушку
            "score": 1.0,
            "title": title,
            "content": content,
        }
        records.append(record)

    return {"records": records}

def search_confluence(query: str, top_k: int):
    cql = f'text ~ "{query}" and type=page'
    url = "https://anianov.atlassian.net/wiki/rest/api/search"
    params = {
        "cql": cql,
        "limit": top_k,
    }

    resp = httpx.get(
        url,
        params=params,
        auth=(CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN),  # Вместо жёсткого кода
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()

    records = []
    for item in data.get("results", []):
        content = item.get("content", {})
        title = content.get("title", "")
        content_id = content.get("id")
        view_link = f"https://anianov.atlassian.net/wiki{content.get('_links', {}).get('webui', '')}"

        # Второй запрос: получаем полное содержимое страницы (body.storage)
        page_content = ""
        try:
            content_url = f"https://anianov.atlassian.net/wiki/rest/api/content/{content_id}"
            content_params = {
                "expand": "body.storage",
            }
            content_resp = httpx.get(
                content_url,
                params=content_params,
                auth=(CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN),  # Вместо жёсткого кода
                headers={"Accept": "application/json"},
            )
            if content_resp.status_code == 200:
                page_data = content_resp.json()
                # Извлекаем HTML-контент из body.storage
                body_storage = page_data.get("body", {}).get("storage", {})
                page_content = body_storage.get("value", "")
        except Exception as e:
            logger.warning(f"Ошибка при получении содержимого страницы {content_id}: {str(e)}")

        records.append({
            "metadata": {
                "path": view_link,
                "description": f"Confluence page {content_id}",
            },
            "score": 1.0,
            "title": title,
            "content": page_content,
        })

    return {"records": records}



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Сервис поиска в базе знаний",
    description="API для получения релевантных документов из корпоративной базы знаний",
    version="1.0.0"
)


# модель запроса с подробным описанием полей
class RetrievalRequest(BaseModel):
    knowledge_id: str = Field(..., description="Идентификатор базы знаний")
    query: str = Field(..., description="Поисковый запрос")
    top_k: int = Field(5, description="Количество результатов для возврата")
    score_threshold: float = Field(0.5, description="Минимальный порог релевантности (0-1)")

# модель метаданных документа
class DocumentMetadata(BaseModel):
    path: str = Field(..., description="Путь к документу")
    description: Optional[str] = Field(None, description="Описание документа")

# модель документа в результатах поиска
class Document(BaseModel):
    metadata: DocumentMetadata
    score: float
    title: str
    content: str

# модель ответа
class RetrievalResponse(BaseModel):
    records: List[Document]


# авторизация по API ключу в заголовке
API_KEY = "my-super-secret-key-123"
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# тестовые данные для демонстрации
DEMO_RESPONSE = {
    "records": [
        {
            "metadata": {
                "path": "s3://corpgpt/тех_задание.txt",
                "description": "техзадание corpgpt документ"
            },
            "score": 0.98,
            "title": "тех_задание.txt",
            "content": "Этот документ содержит порядок работ и требований системы corpgpt."
        },
        {
            "metadata": {
                "path": "s3://corpgpt/договор.txt",
                "description": "corpgpt договор"
            },
            "score": 0.66,
            "title": "договор.txt",
            "content": "Этот документ содержит условия и правила использования corpgpt."
        }
    ]
}


# Функция зависимости для проверки API ключа
async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    else:
        logger.warning(f"Неудачная попытка доступа с неверным API ключом")
        raise HTTPException(
            status_code=403,
            detail="Недействительный API ключ. Доступ запрещен."
        )


def handle_api_error(status_code: int, detail: str):
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail}
    )


@app.post("/retrieval", response_model=RetrievalResponse, summary="Поиск документов")
async def retrieve_knowledge(
    request_data: RetrievalRequest,
    api_key: str = Depends(get_api_key)
):
    """
    Поиск релевантных документов в базе знаний.

    - **knowledge_id**: идентификатор базы знаний
    - **query**: текст запроса
    - **top_k**: количество возвращаемых документов
    - **score_threshold**: минимальный порог релевантности

    Требуется действительный API ключ в заголовке X-API-Key.
    """
    try:
        logger.info(f"Получен запрос с параметрами: {request_data.dict()}")

        # пример тела запроса для внешнего API
        request_body = {
            "knowledge_id": request_data.knowledge_id,
            "query": request_data.query,
            "retrieval_setting": {
                "top_k": request_data.top_k,
                "score_threshold": request_data.score_threshold
            }
        }
        # Выбираем источник по knowledge_id
        if request_data.knowledge_id == "xwiki":
            result = search_xwiki(
                query=request_data.query,
                top_k=request_data.top_k,
            )
        elif request_data.knowledge_id == "confluence":
            result = search_confluence(
                query=request_data.query,
                top_k=request_data.top_k,
            )
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Неизвестный knowledge_id: {request_data.knowledge_id}. Используйте 'xwiki' или 'confluence'."
            )



        if "records" not in result:
            logger.error("В ответе API отсутствуют записи")
            raise HTTPException(status_code=500, detail="Некорректный формат ответа от API")

        response_data = {"records": result["records"]}
        logger.info(f"Найдено {len(result['records'])} документов")

        return response_data

    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

