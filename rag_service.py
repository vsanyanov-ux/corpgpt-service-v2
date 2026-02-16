import os
from mistralai import Mistral
import numpy as np
from typing import List, Dict
from vector_store import VectorStore

class RAGService:
    """RAG сервис с использованием Mistral AI"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError("MISTRAL_API_KEY not found")
        
        self.client = Mistral(api_key=self.api_key)
        self.embedding_model = "mistral-embed"
        self.vector_store = VectorStore(dimension=1024)
        
        # Попытаться загрузить существующий индекс
        if self.vector_store.load():
            print("✅ RAG Service initialized with existing index")
        else:
            print("⚠️ RAG Service initialized without index. Run indexing first.")
    
    def get_embedding(self, text: str) -> np.ndarray:
        """Получить эмбеддинг для одного текста"""
        response = self.client.embeddings.create(
            model=self.embedding_model,
            inputs=[text]
        )
        return np.array(response.data[0].embedding)
    
    def get_batch_embeddings(self, texts: List[str]) -> np.ndarray:
        """Получить эмбеддинги для списка текстов"""
        embeddings = []
        # Батчами по 10 для стабильности API
        batch_size = 10
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            response = self.client.embeddings.create(
                model=self.embedding_model,
                inputs=batch
            )
            batch_embeddings = [item.embedding for item in response.data]
            embeddings.extend(batch_embeddings)
        return np.array(embeddings)
    
    def chunk_text(
        self,
        text: str,
        chunk_size: int = 400,
        overlap: int = 80,
    ) -> List[str]:
        """
        Разбить текст на чанки с overlap.
        Например, chunk_size=400, overlap=80.
        """
        text = (text or "").strip()
        chunks: List[str] = []
        if not text:
            return chunks
    
        step = max(chunk_size - overlap, 1)
    
        for start in range(0, len(text), step):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            if end >= len(text):
                break
    
        return chunks

    
    def retrieve(self, query: str, k: int = 5) -> Dict:
        """
        Найти k наиболее релевантных чанков для запроса
        """
        # 1. Создать эмбеддинг запроса
        query_embedding = self.get_embedding(query)
        
        # 2. Поиск в векторной базе
        retrieved_chunks, distances = self.vector_store.search(query_embedding, k=k)
        
        # 3. Построить контекст
        context = "\n---------------------\n".join(
            [chunk["chunk_text"] for chunk in retrieved_chunks]
        )
        
        # 4. Создать промпт по шаблону Mistrал
        prompt = f"""Context information is below.
        ---------------------
        {context}
        ---------------------
        Given the context information and not prior knowledge, answer the query.
        Query: {query}
        Answer:
        """
        
        return {
            "prompt": prompt,
            "context": context,
            "retrieved_chunks": retrieved_chunks,
            "sources": [
                {
                    "page":    chunk.get("page_name", ""),
                    "url":     chunk.get("url", ""),
                    "content": chunk.get("chunk_text", ""),
                    "space":   chunk.get("space", ""),
                    "name":    chunk.get("name", ""),
                    "updated": chunk.get("updated", ""),
                }
                for chunk in retrieved_chunks
            ],
            "distances": distances.tolist() if len(distances) > 0 else [],
        }

    
    def save_index(self):
        """Сохранить векторный индекс"""
        self.vector_store.save()
