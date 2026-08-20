import logging
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from typing import List, Dict, Any
from ..api_client import FMGatewayClient
from ..config import settings
import uuid

logger = logging.getLogger(__name__)

class IndexingPipeline:
    def __init__(self):
        logger.info(f"Initializing Qdrant client at {settings.qdrant_host}:{settings.qdrant_port}")
        self.qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self.api = FMGatewayClient()
        self.sections_col = "sections"
        self.visuals_col = "visuals"
        self._ensure_collections()
        
    def _ensure_collections(self):
        """Creates the Qdrant dual-collection schema if it doesn't exist."""
        # 1. Sections collection
        if not self.qdrant.collection_exists(self.sections_col):
            logger.info(f"Creating Qdrant collection: {self.sections_col}")
            self.qdrant.create_collection(
                collection_name=self.sections_col,
                vectors_config={
                    "text": VectorParams(size=1024, distance=Distance.COSINE) # BGE dimension
                }
            )
            
        # 2. Visuals collection
        if not self.qdrant.collection_exists(self.visuals_col):
            logger.info(f"Creating Qdrant collection: {self.visuals_col}")
            self.qdrant.create_collection(
                collection_name=self.visuals_col,
                vectors_config={
                    "image": VectorParams(size=768, distance=Distance.COSINE), # SigLIP dimension
                    "logic": VectorParams(size=1024, distance=Distance.COSINE) # BGE dimension
                }
            )
            
    def index_document(self, processed_sections: List[Dict[str, Any]]):
        """
        Takes the chunks from chunker.py, calls BGE for text, SigLIP for images,
        and VLM for flowchart captioning. Pushes to Qdrant.
        """
        logger.info(f"Beginning embedding & indexing for {len(processed_sections)} sections.")
        
        section_points = []
        visual_points = []
        
        for sec in processed_sections:
            logger.debug(f"Embedding text for section {sec['section_id']}")
            text_vector = self.api.get_embeddings(sec["text"])
            
            # Point for `sections` collection
            section_points.append(PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, sec["section_id"])),
                vector={"text": text_vector},
                payload={
                    "doc_id": sec["doc_id"],
                    "section_id": sec["section_id"],
                    "text": sec["text"],
                    "has_table": sec["has_table"]
                }
            ))
            
            for vis in sec["visuals"]:
                vis_id = vis["image_id"]
                logger.info(f"Processing visual: {vis_id}")
                
                # 1. Flowchart Captioning via VLM
                logic_vector = None
                caption = None
                if vis["is_flowchart"]:
                    logger.info(f"Visual {vis_id} detected as flowchart. Requesting VLM caption.")
                    try:
                        caption = self.api.chat_completion(messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Extract and explain the logical flow or data represented in this flowchart. Be concise and structured."},
                                    {"type": "image_url", "image_url": {"url": vis["base64"]}}
                                ]
                            }
                        ])
                        logger.info("Caption generated successfully. Embedding caption logic.")
                        logic_vector = self.api.get_embeddings(caption)
                    except Exception as e:
                        logger.error(f"Failed to caption flowchart {vis_id}: {e}")
                
                # 2. Image Embedding via local SigLIP 
                # (Assuming SigLIP model integration will be added here in a local model loader class)
                # For placeholder logic, we're passing a zeroed vector to satisfy Qdrant until the local SigLIP loads
                image_vector = [0.0] * 768 
                
                vector_dict = {"image": image_vector}
                if logic_vector:
                    vector_dict["logic"] = logic_vector
                    
                visual_points.append(PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, vis_id)),
                    vector=vector_dict,
                    payload={
                        "doc_id": sec["doc_id"],
                        "parent_section_id": sec["section_id"],
                        "is_flowchart": vis["is_flowchart"],
                        "flowchart_description": caption,
                        "base64": vis["base64"]
                    }
                ))
                
        # Push to Qdrant
        if section_points:
            logger.info(f"Upserting {len(section_points)} points to '{self.sections_col}'")
            self.qdrant.upsert(collection_name=self.sections_col, points=section_points)
            
        if visual_points:
            logger.info(f"Upserting {len(visual_points)} points to '{self.visuals_col}'")
            self.qdrant.upsert(collection_name=self.visuals_col, points=visual_points)
            
        logger.info("Indexing complete.")
