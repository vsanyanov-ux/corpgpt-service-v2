import asyncio
from rag_service import RAGService
import requests
import os
import json
from json.decoder import JSONDecodeError

# Копируем ваши настройки из main.py
XWIKI_EXPORT_URL = os.getenv(
    "XWIKI_EXPORT_URL",
    "http://158.255.1.153:8080/bin/view/Tech/CorpGPTExport/?outputSyntax=plain&xpage=plain"
)
XWIKI_USERNAME = os.getenv("XWIKI_USERNAME", "")
XWIKI_PASSWORD = os.getenv("XWIKI_PASSWORD", "")

def fetch_xwiki_export() -> list[dict]:
    """
    Получить все страницы из XWiki через export endpoint
    (копия вашей функции из main.py)
    """
    if not XWIKI_EXPORT_URL:
        print("⚠️ XWIKI_EXPORT_URL not configured")
        return []

    auth = (XWIKI_USERNAME, XWIKI_PASSWORD) if XWIKI_USERNAME and XWIKI_PASSWORD else None
    
    try:
        resp = requests.get(XWIKI_EXPORT_URL, timeout=30, auth=auth)
        resp.raise_for_status()

        text = resp.text
        print("XWIKI_EXPORT raw first 200:", repr(text[:200]))

        try:
            # сначала строгий парсер
            raw_pages = json.loads(text)
        except JSONDecodeError as e:
            print("XWIKI_EXPORT: strict JSON parse error:", e)
            # fallback — менее строгий режим
            try:
                raw_pages = json.loads(text, strict=False)
                print("XWIKI_EXPORT: parsed with strict=False fallback")
            except JSONDecodeError as e2:
                print("XWIKI_EXPORT: fallback JSON parse error:", e2)
                return []

        print(f"XWIKI_EXPORT: total pages = {len(raw_pages)}")
        return raw_pages
    
    except Exception as e:
        print(f"❌ Error fetching XWiki export: {e}")
        return []

async def index_xwiki_content(rag_service: RAGService):
    """
    Индексация всех страниц XWiki для RAG
    """
    print("\n" + "="*60)
    print("🚀 Starting XWiki RAG Indexing")
    print("="*60 + "\n")
    
    # 1. Получить все страницы через ваш export endpoint
    pages = fetch_xwiki_export()
    
    if not pages:
        print("⚠️ No pages found to index. Check XWIKI_EXPORT_URL configuration.")
        return
    
    print(f"✅ Fetched {len(pages)} pages from XWiki\n")
    
    total_chunks = 0
    indexed_pages = 0
    skipped_pages = 0
    
    for idx, page in enumerate(pages, 1):
        title = page.get("title", "Untitled")
        content = page.get("content", "")
        url = page.get("url", "")
        space = page.get("space", "")
        name = page.get("name", "")
        
        # Пропускаем страницы без контента
        if not content or len(content.strip()) < 100:
            print(f"⚠️  [{idx}/{len(pages)}] Skipping '{title}' - too short or empty (len={len(content)})")
            skipped_pages += 1
            continue
        
        print(f"\n📄 [{idx}/{len(pages)}] Indexing: {title}")
        print(f"   Space: {space}")
        print(f"   Name: {name}")
        print(f"   URL: {url}")
        print(f"   Content length: {len(content):,} chars")
        
        try:
            # 2. Разбить на чанки (2048 символов по рекомендации Mistral)
            chunks = rag_service.chunk_text(content, chunk_size=2048)
            print(f"   📦 Split into {len(chunks)} chunks")
            
            if not chunks:
                print(f"   ⚠️  No valid chunks created, skipping")
                skipped_pages += 1
                continue
            
            # 3. Создать эмбеддинги через Mistral API
            print(f"   🔮 Creating embeddings via Mistral API...")
            embeddings = rag_service.get_batch_embeddings(chunks)
            print(f"   ✅ Generated {len(embeddings)} embeddings")
            
            # 4. Подготовить метаданные
            metadata = [
                {
                    "page_name": title,
                    "url": url,
                    "space": space,
                    "name": name,
                    "updated": page.get("updated", ""),
                    "chunk_text": chunk,
                    "chunk_index": i,
                    "chunk_length": len(chunk)
                }
                for i, chunk in enumerate(chunks)
            ]
            
            # 5. Добавить в векторное хранилище
            rag_service.vector_store.add_documents(embeddings, metadata)
            total_chunks += len(chunks)
            indexed_pages += 1
            
            print(f"   ✅ Successfully indexed {len(chunks)} chunks")
            
        except Exception as e:
            print(f"   ❌ Error indexing '{title}': {e}")
            import traceback
            traceback.print_exc()
            skipped_pages += 1
            continue
    
    # 6. Сохранить индекс на диск
    print(f"\n{'='*60}")
    print(f"💾 Saving vector index to disk...")
    try:
        rag_service.save_index()
        print(f"✅ Index saved successfully!")
    except Exception as e:
        print(f"❌ Error saving index: {e}")
        import traceback
        traceback.print_exc()
    
    # 7. Итоговая статистика
    print(f"\n{'='*60}")
    print(f"✅ INDEXING COMPLETE!")
    print(f"{'='*60}")
    print(f"📊 Statistics:")
    print(f"   Total pages fetched:  {len(pages)}")
    print(f"   Pages indexed:        {indexed_pages}")
    print(f"   Pages skipped:        {skipped_pages}")
    print(f"   Total chunks created: {total_chunks}")
    print(f"   Avg chunks per page:  {total_chunks/indexed_pages:.1f}" if indexed_pages > 0 else "   Avg chunks per page:  N/A")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    print("Starting standalone indexing...")
    rag_service = RAGService()
    asyncio.run(index_xwiki_content(rag_service))
