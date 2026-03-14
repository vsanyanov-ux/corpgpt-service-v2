from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import os
from typing import List
from rag_service import RAGService
from xwiki_client import search_xwiki_raw, enrich_xwiki_results, fetch_xwiki_export, chunk_text
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app = FastAPI()

# Инициализация RAG-сервиса
rag_service = RAGService(api_key=os.getenv("MISTRAL_API_KEY"))

@app.get("/")
async def root():
    return {"message": "CorpGPT XWiki RAG Service"}

@app.post("/rag/query")
async def rag_query(question: str, k: int = 3):
    """
    RAG endpoint для поиска релевантного контекста
    """
    try:
        result = rag_service.retrieve(question, k=k)
        return {
            "success": True,
            "question": question,
            "answer_prompt": result["prompt"],
            "sources": result["sources"],
            "distances": result["distances"]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/rag/index")
async def trigger_indexing(x_api_key: str = Header(None)):
    """
    Требуется API ключ в заголовке запроса
    """
    # Проверяем API-ключ
    expected_key = os.getenv("ADMIN_API_KEY")
    if not expected_key:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not configured")
    
    if x_api_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    # Только если ключ правильный - запускаем индексацию
    from indexer import index_xwiki_content
    await index_xwiki_content(rag_service)
    return {"success": True, "message": "Indexing completed"}


@app.on_event("startup")
async def startup_event():
    """
    Выполняется ОДИН РАЗ при запуске FastAPI приложения
    """
    print("🚀 Starting up CorpGPT RAG Service...")
    
    # 1. Проверяем, сколько векторов в индексе
    total_vectors = rag_service.vector_store.index.ntotal
    print(f"📊 Current index size: {total_vectors} vectors")
    
    # 2. Если индекс пустой - запускаем индексацию
    if total_vectors == 0:
        print("⚠️ Index is empty. Starting auto-indexing...")
        try:
            from indexer import index_xwiki_content
            await index_xwiki_content(rag_service)
            print("✅ Auto-indexing completed successfully")
        except Exception as e:
            print(f"❌ Auto-indexing failed: {e}")
    else:
        print(f"✅ Index loaded: {total_vectors} vectors ready")


# CorpGPT Request Model
class RetrievalSettings(BaseModel):
    top_k: int = 5
    score_threshold: float = 0.5

class RetrievalRequest(BaseModel):
    knowledge_id: str
    query: str
    retrieval_setting: RetrievalSettings = RetrievalSettings()

class SearchResult(BaseModel):
    title: str
    url: str
    excerpt: str


@app.get("/health")
async def health():
    return {"status": "healthy"}

# Модели CorpGPT-запроса/ответа уже есть у тебя выше:
# class RetrievalSettings(BaseModel):
#     top_k: int = 5
#     score_threshold: float = 0.5
#
# class RetrievalRequest(BaseModel):
#     knowledge_id: str
#     query: str
#     retrieval_setting: RetrievalSettings = RetrievalSettings()

@app.post("/retrieval")
async def retrieval(request: RetrievalRequest):
    """
    Совместимо с CorpGPT и Dify External KB.
    """
    logger.info(f"Dify/CorpGPT req: knowledge_id={request.knowledge_id}, query='{request.query}', top_k={getattr(request.retrieval_setting, 'top_k', 5)}")
    
    if request.knowledge_id != "xwiki":
        logger.warning(f"Wrong knowledge_id: {request.knowledge_id}")
        return {"records": []}

    query = (request.query or "").strip()
    if not query or len(query) < 2:
        logger.info("Query too short")
        return {"records": []}

    top_k = getattr(request.retrieval_setting, "top_k", 5)
    score_threshold = getattr(request.retrieval_setting, "score_threshold", 0.5)

    try:
        rag_result = rag_service.retrieve(query, k=top_k)
        sources_count = len(rag_result.get("sources", []))
        logger.info(f"RAG retrieve: {sources_count} sources, distances={rag_result.get('distances', [])}")
        
        records = []
        for i, source in enumerate(rag_result.get("sources", [])):
            distance = float(rag_result.get("distances", [1.0])[i])
            score = 1.0 / (1.0 + distance)
            
            logger.debug(f"Source {i}: distance={distance:.3f}, score={score:.3f}, title='{source.get('page', '')[:50]}...'")

            if score < score_threshold:
                logger.debug(f"Filtered: score {score:.3f} < threshold {score_threshold}")
                continue

            record_base = {
                "score": score,
                "title": source.get("page") or source.get("name", ""),
                "content": source.get("content", ""),
                "metadata": {
                    "document_id": source.get("url", "") or source.get("name", ""),
                    "path": source.get("url", ""),
                    "description": source.get("page", ""),
                    "space": source.get("space", ""),
                    "name": source.get("name", ""),
                    "updated": source.get("updated", ""),
                    "distance": distance,
                }
            }
            records.append(record_base)

        logger.info(f"Final records sent: {len(records)}/{sources_count} (threshold={score_threshold})")
        return {"records": records[:top_k]}

    except Exception as e:
        logger.error(f"❌ RAG error: {e}", exc_info=True)
        return {"records": []}





