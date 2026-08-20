import logging
import torch
from transformers import AutoProcessor, AutoModel
from PIL import Image
import io
import base64

logger = logging.getLogger(__name__)

class SigLIPEncoder:
    def __init__(self, model_id: str = "google/siglip-base-patch16-224"):
        logger.info(f"Loading local SigLIP model '{model_id}' into memory...")
        # Check if CUDA is available, otherwise fallback to CPU
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        
        # Load processor and model. This requires downloading weights once during setup,
        # but executes 100% locally and offline during runtime.
        # Try to load strictly from local cache first to prevent HF network pings
        try:
            self.processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
            self.model = AutoModel.from_pretrained(model_id, local_files_only=True).to(self.device)
            logger.info("SigLIP model loaded strictly from local offline cache. Zero public network calls made.")
        except Exception:
            logger.info("Local model not found in cache. Connecting to Hugging Face for one-time download...")
            self.processor = AutoProcessor.from_pretrained(model_id)
            self.model = AutoModel.from_pretrained(model_id).to(self.device)
            logger.info("SigLIP model downloaded and cached successfully.")
            
        self.model.eval()

    def embed_base64_image(self, base64_data: str) -> list[float]:
        """Decodes base64 image and returns the 768-dimensional SigLIP embedding."""
        try:
            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]
            image_bytes = base64.b64decode(base64_data)
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            with torch.no_grad():
                inputs = self.processor(images=image, return_tensors="pt").to(self.device)
                image_features = self.model.get_image_features(**inputs)
                
                # Normalize the embeddings for cosine similarity
                image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                
                # Convert to a flat python list of floats
                embedding = image_features.cpu().numpy().flatten().tolist()
                return embedding
        except Exception as e:
            logger.error(f"Failed to embed image with SigLIP: {e}")
            # Return zeroed vector as fallback to not break Qdrant
            return [0.0] * 768

    def embed_text(self, text: str) -> list[float]:
        """Encodes text using the SigLIP text tower for cross-modal visual search."""
        try:
            with torch.no_grad():
                inputs = self.processor(text=text, padding="max_length", truncation=True, return_tensors="pt").to(self.device)
                text_features = self.model.get_text_features(**inputs)
                
                # Handle older/different transformers versions that return an output object instead of a tensor
                if hasattr(text_features, "pooler_output"):
                    text_features = text_features.pooler_output
                elif isinstance(text_features, tuple):
                    text_features = text_features[0] if isinstance(text_features[0], torch.Tensor) and text_features[0].dim() == 2 else text_features[1]
                
                # Normalize the embeddings for cosine similarity
                text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)
                
                return text_features.cpu().numpy().flatten().tolist()
        except Exception as e:
            logger.error(f"Failed to embed text with SigLIP: {e}")
            return [0.0] * 768
