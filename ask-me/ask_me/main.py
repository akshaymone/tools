import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

from .config import settings
from .ingestion.converter import convert_to_pdf, extract_page_images
from .indexing.pipeline import IndexingPipeline
from .api_client import FMGatewayClient
from .generation.chat import ChatAgent

# Setup logging
log_level = logging.DEBUG if settings.debug_log else logging.INFO
logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', force=True)
logger = logging.getLogger(__name__)

def ingest():
    """Crawls the index directory and ingests documents using Vision-RAG (ColPali)."""
    logger.info(f"Starting Vision-RAG ingestion on {settings.index_directory}...")
    pipeline = IndexingPipeline()
    
    path = Path(settings.index_directory).resolve()
    if not path.exists():
        logger.error(f"Index directory does not exist: {path}")
        return
        
    logger.debug(f"Crawling directory {path} for documents (.pdf, .docx, .pptx)...")
    for filepath in path.rglob("*"):
        if filepath.is_file():
            ext = filepath.suffix.lower()
            if ext in [".pdf", ".docx", ".pptx"]:
                if pipeline.is_document_indexed(filepath.name):
                    logger.info(f"Document {filepath.name} is already indexed. Skipping.")
                    continue
                    
                logger.info(f"Processing file: {filepath.name}")
                try:
                    # 1. Ensure it's a PDF (convert if DOCX/PPTX)
                    pdf_path = convert_to_pdf(str(filepath))
                    
                    # 2. Extract page images and 3. Embed in batches to prevent OOM
                    pages_extracted = False
                    for start_page, page_images in extract_page_images(pdf_path):
                        if not page_images:
                            continue
                        pages_extracted = True
                        pipeline.index_document_pages(filepath.name, page_images, start_page=start_page)
                    
                    if not pages_extracted:
                        logger.warning(f"No pages extracted for {filepath.name}, skipping.")
                    
                    
                except Exception as e:
                    logger.error(f"Failed to ingest {filepath.name}: {e}")
                    
    logger.info("All documents in the index directory have been ingested successfully!")

def chat():
    """Starts the interactive CLI chat."""
    print("Welcome to Ask-Me! (Local Multimodal RAG)")
    print("Type 'exit' or 'quit' to close.")
    
    agent = ChatAgent()
    history = []
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit"]:
                break
                
            response, history = agent.chat(user_input=user_input, chat_history=history)
            print(f"\nAssistant: {response}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\nError: {e}")

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ask-Me Local Multimodal RAG")
    parser.add_argument("mode", choices=["ingest", "chat"], help="Mode to run the application in.")
    args = parser.parse_args()
    
    if args.mode == "ingest":
        ingest()
    elif args.mode == "chat":
        chat()

if __name__ == "__main__":
    main()
