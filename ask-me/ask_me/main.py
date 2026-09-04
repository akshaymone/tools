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
    import json
    import time
    from pathlib import Path as _Path

    logger.info(f"Starting Vision-RAG ingestion on {settings.index_directory}...")
    pipeline = IndexingPipeline()

    status_dir = _Path(settings.status_dir)
    status_dir.mkdir(parents=True, exist_ok=True)

    path = _Path(settings.index_directory).resolve()
    if not path.exists():
        logger.error(f"Index directory does not exist: {path}")
        return

    logger.debug(f"Crawling directory {path} for documents (.pdf, .docx, .pptx)...")
    for filepath in path.rglob("*"):
        if filepath.is_file():
            ext = filepath.suffix.lower()
            if ext in [".pdf", ".docx", ".pptx"]:
                # Use stem (no extension) — consistent with server.py's Path.stem convention
                doc_name = filepath.stem
                status_file = status_dir / f"{doc_name}.json"

                if pipeline.is_document_indexed(doc_name):
                    logger.info(f"Document '{doc_name}' is already indexed. Skipping.")
                    continue

                logger.info(f"Processing file: {filepath.name} (doc_name='{doc_name}')")

                # ── Write 'running' status ────────────────────────────────────
                status_file.write_text(json.dumps({
                    "doc_name": doc_name,
                    "file": str(filepath),
                    "status": "running",
                    "pages_done": 0,
                    "pages_total": None,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "finished_at": None,
                    "error": None,
                }, indent=2))

                try:
                    # 1. Ensure it's a PDF (convert if DOCX/PPTX)
                    pdf_path = convert_to_pdf(str(filepath))

                    # 2. Extract page images and 3. Embed in batches to prevent OOM
                    pages_done = 0
                    pages_extracted = False
                    for start_page, page_images in extract_page_images(pdf_path):
                        if not page_images:
                            continue
                        pages_extracted = True
                        pipeline.index_document_pages(doc_name, page_images, start_page=start_page)
                        pages_done += len(page_images)

                        # Update progress in status file after each batch
                        status_file.write_text(json.dumps({
                            "doc_name": doc_name,
                            "file": str(filepath),
                            "status": "running",
                            "pages_done": pages_done,
                            "pages_total": None,
                            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "finished_at": None,
                            "error": None,
                        }, indent=2))

                    if not pages_extracted:
                        logger.warning(f"No pages extracted for '{doc_name}', skipping.")
                        status_file.write_text(json.dumps({
                            "doc_name": doc_name, "file": str(filepath),
                            "status": "error", "pages_done": 0, "pages_total": None,
                            "started_at": None, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "error": "No pages were extracted from the PDF.",
                        }, indent=2))
                    else:
                        logger.info(f"Indexing completely finished for '{doc_name}'!")
                        # ── Write 'done' status ───────────────────────────────
                        status_file.write_text(json.dumps({
                            "doc_name": doc_name,
                            "file": str(filepath),
                            "status": "done",
                            "pages_done": pages_done,
                            "pages_total": pages_done,
                            "started_at": None,
                            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "error": None,
                        }, indent=2))

                except Exception as e:
                    logger.error(f"Failed to ingest '{doc_name}': {e}")
                    # ── Write 'error' status ──────────────────────────────────
                    status_file.write_text(json.dumps({
                        "doc_name": doc_name, "file": str(filepath),
                        "status": "error", "pages_done": 0, "pages_total": None,
                        "started_at": None, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "error": str(e),
                    }, indent=2))

    logger.info("All documents in the index directory have been ingested successfully!")


def chat():
    """Starts the interactive CLI chat."""
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    
    console = Console()
    console.print(Panel.fit("[bold blue]Welcome to Ask-Me![/bold blue]\n(Local Multimodal RAG)\nType 'exit' or 'quit' to close."))
    
    agent = ChatAgent()
    history = []
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit"]:
                break
                
            response, history = agent.chat(user_input=user_input, chat_history=history)
            console.print("\n[bold green]Assistant:[/bold green]")
            console.print(Markdown(response))
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}")

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
