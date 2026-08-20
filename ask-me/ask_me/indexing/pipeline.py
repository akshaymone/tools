import logging
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct, MultiVectorConfig, MultiVectorComparator, Modifier
from typing import List, Dict, Any
from ..config import settings
from ..models.vision_retriever import VisionRetriever
import uuid
import base64
from io import BytesIO

logger = logging.getLogger(__name__)

class IndexingPipeline:
    def __init__(self):
        logger.info(f"Initializing Qdrant client at {settings.qdrant_host}:{settings.qdrant_port}")
        self.qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self.pages_col = "vision_pages"
        self._ensure_collections()
        
    def _ensure_collections(self):
        """Creates the Qdrant collection for Vision RAG (MultiVector)."""
        if not self.qdrant.collection_exists(self.pages_col):
            logger.info(f"Creating Qdrant MultiVector collection: {self.pages_col}")
            self.qdrant.create_collection(
                collection_name=self.pages_col,
                vectors_config=VectorParams(
                    size=128, # ColSmolVLM dimension per patch
                    distance=Distance.COSINE,
                    multivector_config=MultiVectorConfig(
                        comparator=MultiVectorComparator.MAX_SIM
                    )
                )
            )
            
    def is_document_indexed(self, doc_name: str) -> bool:
        """Checks if the document has already been indexed by looking for its page 1 ID."""
        if not self.qdrant.collection_exists(self.pages_col):
            return False
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_name}_page_1"))
        result = self.qdrant.retrieve(collection_name=self.pages_col, ids=[point_id])
        return len(result) > 0

    def index_document_pages(self, doc_name: str, page_images: List[Any]):
        """
        Takes page images, embeds them with VisionRetriever, and pushes to Qdrant.
        """
        logger.info(f"Beginning vision embedding for {len(page_images)} pages of {doc_name}.")
        
        vision_retriever = VisionRetriever()
        
        # Batch embed the images
        multi_vectors = vision_retriever.embed_images(page_images)
        
        points = []
        for i, (image, mv) in enumerate(zip(page_images, multi_vectors)):
            page_num = i + 1
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_name}_page_{page_num}"))
            
            # Convert image to base64 for payload (so we can display it later or send to VLM)
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            points.append(PointStruct(
                id=point_id,
                vector=mv,
                payload={
                    "doc_name": doc_name,
                    "page_number": page_num,
                    "image_base64": img_str
                }
            ))
            
        if points:
            logger.info(f"Upserting {len(points)} page vectors to '{self.pages_col}'")
            self.qdrant.upsert(collection_name=self.pages_col, points=points)
            
        logger.info(f"Indexing complete for {doc_name}.")
