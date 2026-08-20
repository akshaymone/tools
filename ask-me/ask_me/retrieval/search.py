import logging
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, Prefetch
from ..config import settings
from ..api_client import FMGatewayClient
from ..models.siglip import SigLIPEncoder

logger = logging.getLogger(__name__)

class Retriever:
    def __init__(self):
        self.qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self.api = FMGatewayClient()
        self.siglip = SigLIPEncoder()
        
    def search(self, query: str, query_image_base64: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Executes a dual-embedding search with Qdrant Reciprocal Rank Fusion (RRF).
        Embeds the query text using BGE (for sections and logic) and SigLIP (for images).
        """
        logger.info(f"Executing retrieval for query: '{query}'")
        
        # 1. Embed Query Text (BGE space for sections and flowchart logic)
        bge_query_vector = self.api.get_embeddings(query)
        
        # 2. Embed Query Image (SigLIP space for visual search)
        siglip_query_vector = None
        if query_image_base64:
            logger.info("Image provided in query. Embedding via local SigLIP.")
            siglip_query_vector = self.siglip.embed_base64_image(query_image_base64)
        
        # 3. Retrieve Sections (Text only)
        logger.debug("Searching 'sections' collection.")
        section_results = self.qdrant.query_points(
            collection_name="sections",
            query=bge_query_vector,
            using="text",
            limit=top_k
        ).points
        
        # 4. Retrieve Visuals using RRF (Reciprocal Rank Fusion)
        logger.debug("Searching 'visuals' collection using Prefetch RRF.")
        visual_prefetches = []
        
        # Flowchart Logic Prefetch (using BGE vector)
        visual_prefetches.append(
            Prefetch(
                query=bge_query_vector,
                using="logic",
                limit=top_k,
                filter=Filter(
                    must=[FieldCondition(key="is_flowchart", match=MatchValue(value=True))]
                )
            )
        )
        
        # Visual/Image Prefetch (using SigLIP vector) if provided
        if siglip_query_vector:
            visual_prefetches.append(
                Prefetch(
                    query=siglip_query_vector,
                    using="image",
                    limit=top_k
                )
            )
            
        visual_results = self.qdrant.query_points(
            collection_name="visuals",
            prefetch=visual_prefetches,
            query=None, # None indicates pure RRF fusion of the prefetches
            limit=top_k
        )
        
        # 5. Merge and Group by Parent Section
        merged_context = {}
        
        for res in section_results:
            sec_id = res.payload["section_id"]
            if sec_id not in merged_context:
                merged_context[sec_id] = {
                    "doc_id": res.payload.get("doc_id", "Unknown"), 
                    "text": res.payload["text"], 
                    "visuals": []
                }
                
        for res in visual_results.points:
            parent_id = res.payload["parent_section_id"]
            if parent_id not in merged_context:
                # If we hit an image but didn't hit its parent text, fetch the parent text
                parent_res = self.qdrant.scroll(
                    collection_name="sections",
                    scroll_filter=Filter(must=[FieldCondition(key="section_id", match=MatchValue(value=parent_id))]),
                    limit=1
                )[0]
                if parent_res:
                    merged_context[parent_id] = {
                        "doc_id": parent_res[0].payload.get("doc_id", "Unknown"),
                        "text": parent_res[0].payload["text"], 
                        "visuals": []
                    }
            
            if parent_id in merged_context:
                merged_context[parent_id]["visuals"].append(res.payload)
                
        logger.info(f"Retrieved {len(merged_context)} distinct contextual sections.")
        return list(merged_context.values())
