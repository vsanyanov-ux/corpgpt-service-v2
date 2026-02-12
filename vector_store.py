import faiss
import numpy as np
import pickle
import os
from typing import List, Dict, Tuple

class VectorStore:
    """Векторное хранилище на основе FAISS для RAG"""
    
    def __init__(self, dimension: int = 1024):
        """
        dimension: размерность эмбеддингов Mistral (1024 для mistral-embed)
        """
        self.dimension = dimension
        self.index = faiss.IndexFlatL2(dimension)
        self.chunks_metadata = []
        self.index_file = "xwiki_vectors.index"
        self.metadata_file = "xwiki_metadata.pkl"
    
    def add_documents(self, embeddings: np.ndarray, metadata: List[Dict]):
        """Добавить документы в индекс"""
        if embeddings.shape[1] != self.dimension:
            raise ValueError(f"Embeddings dimension mismatch: expected {self.dimension}, got {embeddings.shape[1]}")
        
        self.index.add(embeddings.astype('float32'))
        self.chunks_metadata.extend(metadata)
        print(f"✅ Added {len(metadata)} chunks. Total: {len(self.chunks_metadata)}")
    
    def search(self, query_embedding: np.ndarray, k: int = 3) -> Tuple[List[Dict], np.ndarray]:
        """
        Поиск k наиболее похожих документов
        Returns: (list of metadata dicts, distances array)
        """
        if self.index.ntotal == 0:
            return [], np.array([])
        
        # Reshape для FAISS
        query_vector = query_embedding.astype('float32').reshape(1, -1)
        
        # Поиск
        distances, indices = self.index.search(query_vector, min(k, self.index.ntotal))
        
        # Получить метаданные
        retrieved = [
            self.chunks_metadata[i] 
            for i in indices[0] 
            if i < len(self.chunks_metadata)
        ]
        
        return retrieved, distances[0]
    
    def save(self):
        """Сохранить индекс и метаданные на диск"""
        faiss.write_index(self.index, self.index_file)
        with open(self.metadata_file, 'wb') as f:
            pickle.dump(self.chunks_metadata, f)
        print(f"💾 Saved index: {self.index.ntotal} vectors")
    
    def load(self):
        """Загрузить индекс и метаданные с диска"""
        if os.path.exists(self.index_file) and os.path.exists(self.metadata_file):
            self.index = faiss.read_index(self.index_file)
            with open(self.metadata_file, 'rb') as f:
                self.chunks_metadata = pickle.load(f)
            print(f"📂 Loaded index: {self.index.ntotal} vectors")
            return True
        return False
    
    def clear(self):
        """Очистить индекс"""
        self.index = faiss.IndexFlatL2(self.dimension)
        self.chunks_metadata = []
