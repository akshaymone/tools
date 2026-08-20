import requests
import logging
from typing import Dict, Any, List
from .config import settings

logger = logging.getLogger(__name__)

class FMGatewayClient:
    def __init__(self):
        self.base_url = settings.fm_gateway_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.fm_gateway_token}"
        }

    def extract_document(self, pdf_path: str) -> Dict[str, Any]:
        """Calls the extraction API to get Markdown and embedded base64 images."""
        url = f"{self.base_url}/v1/documents/extraction"
        logger.info(f"Extracting document via API: {pdf_path}")
        with open(pdf_path, "rb") as f:
            files = {"files": (pdf_path, f, "application/pdf")}
            data = {
                "to_formats": "md",
                "image_export_mode": "embedded",
                "do_ocr": "true",
                "force_ocr": "false"
            }
            logger.debug(f"POST {url} with data: {data}")
            response = requests.post(url, headers=self.headers, files=files, data=data)
            logger.debug(f"Response Status: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            logger.debug("Extraction API response received successfully.")
            return result

    def get_embeddings(self, text: str, model: str = None) -> List[float]:
        """Gets text embeddings using BGE."""
        url = f"{self.base_url}/v1/embeddings"
        payload = {
            "model": model or settings.embedding_model,
            "input": text
        }
        headers = {**self.headers, "Content-Type": "application/json"}
        logger.debug(f"POST {url} | Model: {payload['model']} | Text snippet: {text[:50]}...")
        response = requests.post(url, headers=headers, json=payload)
        logger.debug(f"Response Status: {response.status_code}")
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    def chat_completion(self, messages: List[Dict[str, Any]], max_tokens: int = 1000) -> str:
        """Calls the VLM for chat completions and image captioning."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": settings.vlm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1
        }
        headers = {**self.headers, "Content-Type": "application/json"}
        logger.debug(f"POST {url} | Model: {payload['model']} | Max Tokens: {max_tokens}")
        response = requests.post(url, headers=headers, json=payload)
        logger.debug(f"Response Status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Chat completion failed. Response: {response.text}")
            
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        logger.debug(f"VLM Output snippet: {content[:100]}...")
        return content
