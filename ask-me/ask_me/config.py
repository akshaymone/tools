import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Settings
    fm_gateway_url: str = os.getenv("FM_GATEWAY_URL", "")
    fm_gateway_token: str = os.getenv("FM_GATEWAY_TOKEN", "")
    
    # Models
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3") 
    vlm_model: str = os.getenv("VLM_MODEL", "google/gemma-4-31B-it")
    
    # Qdrant
    qdrant_host: str = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port: int = int(os.getenv("QDRANT_PORT", "6333"))
    
    # Ingestion Settings
    index_directory: str = os.getenv("INDEX_DIRECTORY", "./data")
    
    class Config:
        env_file = ".env"

settings = Settings()
