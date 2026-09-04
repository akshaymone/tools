import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Settings
    fm_gateway_url: str = os.getenv("FM_GATEWAY_URL", "")
    fm_gateway_token: str = os.getenv("FM_GATEWAY_TOKEN", "")
    fm_gateway_verify_ssl: bool = str(os.getenv("FM_GATEWAY_VERIFY_SSL", "False")).lower() in ("true", "1", "yes")
    
    # Models
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3") 
    vlm_model: str = os.getenv("VLM_MODEL", "google/gemma-4-31B-it")
    synthesis_model: str = os.getenv("SYNTHESIS_MODEL", "Qwen/Qwen3.6-27B")
    vision_retriever_model: str = os.getenv("VISION_RETRIEVER_MODEL", "vidore/colSmol-500M")
    
    # Qdrant
    qdrant_host: str = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port: int = int(os.getenv("QDRANT_PORT", "6333"))
    
    # Ingestion Settings
    index_directory: str = os.getenv("INDEX_DIRECTORY", "./data")
    # Stable directory where extracted page JPEGs are persisted across reboots.
    # ask-me writes page images here during indexing so that file_path stored
    # in the Qdrant payload remains valid after server restarts.
    image_store_dir: str = os.getenv("IMAGE_STORE_DIR", str(Path.home() / ".ask_me_store" / "vision_pages"))
    # Optional: path for ingestion status JSON files (used by MCP poll_ingestion_status tool)
    status_dir: str = os.getenv("STATUS_DIR", str(Path.home() / ".ask_me_store" / "status"))

    # Logging
    debug_log: bool = str(os.getenv("DEBUG_LOG", "False")).lower() in ("true", "1", "yes")
    
    class Config:
        env_file = ".env"

settings = Settings()
