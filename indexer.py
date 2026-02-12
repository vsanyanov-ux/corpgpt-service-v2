import asyncio
from rag_service import RAGService
# Импортируйте ваши существующие классы для работы с XWiki
# from your_xwiki_module import get_all_pages, XWikiPage

async def index_xwiki_content(rag_service: RAGService):
    """
    Индексация всех страниц XWiki
    """
    print("🚀 Starting XWiki indexing...")
    
    # TODO: Замените на ваш метод получения страниц из XWiki
    # pages = await get_all_xwiki_pages()
    
    # Пример структуры страницы:
    # pages = [
    #     {"title": "Page 1", "content": "...", "url": "..."},
    #     {"title": "Page 2", "content": "...", "url": "..."},
    # ]
    
    # Для теста используем заглушку
    pages = [
        {
            "title": "Test Page 1",
            "content": "This is a test page content from XWiki. " * 100,
            "url": "https://xwiki.example.com/page1"
        }
    ]
    
    total_chunks = 0
    
    for page in pages:
        print(f"📄 Indexing: {page['title']}")
        
        # 1. Разбить контент на чанки
        chunks = rag_service.chunk_text(page['content'], chunk_size=2048)
        
        # 2. Создать эмбеддинги
        embeddings = rag_service.get_batch_embeddings(chunks)
        
        # 3. Подготовить метаданные
        metadata = [
            {
                "page_name": page['title'],
                "url": page['url'],
                "chunk_text": chunk,
                "chunk_index": i
            }
            for i, chunk in enumerate(chunks)
        ]
        
        # 4. Добавить в векторное хранилище
        rag_service.vector_store.add_documents(embeddings, metadata)
        total_chunks += len(chunks)
    
    # 5. Сохранить индекс
    rag_service.save_index()
    
    print(f"✅ Indexing complete! Total chunks: {total_chunks}")

if __name__ == "__main__":
    rag_service = RAGService()
    asyncio.run(index_xwiki_content(rag_service))
