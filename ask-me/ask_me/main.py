import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

from .config import settings
from .ingestion.converter import convert_to_pdf
from .ingestion.chunker import process_document_markdown
from .indexing.pipeline import IndexingPipeline
from .api_client import FMGatewayClient
from .generation.chat import ChatAgent

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def ingest():
    """Crawls the index directory and ingests everything."""
    logger.info(f"Starting ingestion process on {settings.index_directory}...")
    api = FMGatewayClient()
    pipeline = IndexingPipeline()
    
    path = Path(settings.index_directory).resolve()
    if not path.exists():
        logger.error(f"Index directory does not exist: {path}")
        return
        
    for filepath in path.rglob("*"):
        if filepath.is_file():
            ext = filepath.suffix.lower()
            if ext in [".pdf", ".docx", ".pptx"]:
                logger.info(f"Processing file: {filepath.name}")
                try:
                    pdf_path = convert_to_pdf(str(filepath))
                    doc_response = api.extract_document(pdf_path)
                    
                    # Assuming extraction API returns {"markdown": "..."} or similar
                    # For safety we get whatever text/markdown string is in the dict
                    md_text = doc_response.get("markdown") or doc_response.get("text") or str(doc_response)
                    
                    processed_sections = process_document_markdown(md_text, filepath.name)
                    pipeline.index_document(processed_sections)
                except Exception as e:
                    logger.error(f"Failed to ingest {filepath.name}: {e}")

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
