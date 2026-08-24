import torch
import logging
from typing import List
from PIL import Image
from colpali_engine.models import ColIdefics3, ColIdefics3Processor
from ..config import settings

logger = logging.getLogger(__name__)

class VisionRetriever:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VisionRetriever, cls).__new__(cls)
            cls._instance._init_model()
        return cls._instance
        
    def _init_model(self):
        logger.info(f"Loading Vision Retriever Model: {settings.vision_retriever_model}")
        logger.debug("If this is the first run, the model weights (~1GB) are being downloaded from HuggingFace to your local cache. This might take several minutes and appear stuck.")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = ColIdefics3Processor.from_pretrained(settings.vision_retriever_model)
        self.model = ColIdefics3.from_pretrained(
            settings.vision_retriever_model,
            torch_dtype=torch.bfloat16,
            device_map=self.device
        )
        self.model.eval()
        logger.info("Vision Retriever loaded successfully.")
        
    def embed_images(self, images: List[Image.Image]) -> List[List[List[float]]]:
        """
        Embeds a list of PIL Images into multi-vector representations.
        Returns a list of multi-vectors (one per image).
        Each multi-vector is a list of patch embeddings (e.g. 1030 x 128).
        """
        if not images:
            return []
            
        logger.info(f"Processing and tokenizing {len(images)} images for vision embedding...")
        inputs = self.processor.process_images(images).to(self.device)
        logger.debug(f"Computed inputs for {len(images)} images on {self.device}. Passing to model...")
        
        with torch.no_grad():
            embeddings = self.model(**inputs)
            logger.info(f"Successfully generated embeddings for {len(images)} images.")
            logger.debug(f"Generated embeddings shape: {embeddings.shape}")
            
        # embeddings shape: (batch_size, num_patches, dim)
        return embeddings.cpu().float().numpy().tolist()
        
    def embed_query(self, query: str) -> List[List[float]]:
        """
        Embeds a text query into a multi-vector representation.
        Returns a single multi-vector (list of token embeddings).
        """
        inputs = self.processor.process_queries([query]).to(self.device)
        with torch.no_grad():
            embeddings = self.model(**inputs)
            
        # embeddings shape: (1, num_tokens, dim)
        return embeddings[0].cpu().float().numpy().tolist()
