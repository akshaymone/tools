import logging
from typing import List, Dict, Any
from qdrant_client import QdrantClient, models
from ..config import settings
from ..models.vision_retriever import VisionRetriever

logger = logging.getLogger(__name__)

class Retriever:
    def __init__(self):
        self.qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self.vision = VisionRetriever()
        self.pages_col = "vision_pages"
        
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Executes a MultiVector (ColBERT-style) search against the vision_pages collection.
        Returns the most relevant page images.
        """
        logger.info(f"Executing Vision-RAG retrieval for query: '{query}'")
        
        # 1. Embed Query Text into MultiVector
        query_multi_vector = self.vision.embed_query(query)
        
        # 2. Search Qdrant
        logger.debug(f"Searching '{self.pages_col}' collection.")
        results = self.qdrant.query_points(
            collection_name=self.pages_col,
            query=query_multi_vector,
            limit=top_k
        ).points
        
        # 3. Format results
        formatted_results = []
        for res in results:
            formatted_results.append({
                "doc_name": res.payload.get("doc_name", "Unknown"),
                "page_number": res.payload.get("page_number", 0),
                "base64": res.payload.get("image_base64", ""),
                "score": res.score
            })
            
        logger.info(f"Retrieved {len(formatted_results)} relevant pages.")
        return formatted_results
