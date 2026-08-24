# ask-me — Developer Log

> A running log of all development sessions, decisions, bugs, and fixes.
> Updated after every conversation so any AI or human can quickly catch up.

---

## Project Overview

**Goal:** A Python CLI tool designed to build a fully local, offline-capable Multimodal RAG pipeline. It allows users to ask questions against a local corpus of technical documents (PPTX, Word, PDF) containing dense text, tables, charts, diagrams, and flowcharts.
**Constraints:** Tight 4GB VRAM constraint. Offloads large model inference (LLM and Text Embeddings) to an internal FM Gateway API, while keeping Vector Storage and Image Embeddings strictly local.

### Architecture Highlights
- **Document Ingestion:** Recursively crawls directories. Uses native Windows COM (`win32com`) to perfectly convert `.docx` and `.pptx` to PDF entirely offline without formatting loss.
- **Extraction & OCR:** Sends PDFs to the FM Gateway for Markdown conversion. Automatically applies Windows native PowerShell OCR to images as a fallback to catch hidden text.
- **Dual Vector Storage:** Runs Qdrant locally via Docker. Uses two collections: `sections` (text chunks) and `visuals` (images).
- **Embeddings:** Text is embedded using the `bge-m3` model via the API. Images are embedded locally using `google/siglip-base-patch16-224`.
- **Chat Agent:** Powered by LangGraph to maintain chat history and seamlessly route context to the `gemma-4-31B-it` Vision-Language Model.

### Repo Structure

```
ask-me/
├── pyproject.toml
├── README.md
├── docker-compose.yml
├── dev_log.md                ← this file
└── ask_me/
    ├── __init__.py
    ├── api_client.py
    ├── config.py
    ├── main.py
    ├── generation/
    ├── indexing/
    ├── ingestion/
    ├── models/
    ├── retrieval/
    └── tests/
```

---

## Session 1 — 2026-08-20 (Current)

### Context

Starting development on the `ask-me` Multimodal RAG pipeline. Initializing the `dev_log.md` to track progress, design decisions, and debugging steps.

### Next Steps

---

## Session 2 — 2026-08-20 (Current)

### Context
The original extraction approach (sending PDFs to the FM Gateway for Markdown conversion) caused `429 Too Many Requests` errors when processing large batches of documents. Additionally, text extraction was lossy, often struggling with complex tables and multi-column layouts.

### Architectural Pivot: Vision-RAG (ColPali)
To solve both the rate-limiting and OCR quality issues, the architecture was pivoted to a true **Vision-RAG** model using the `colpali-engine`.

#### Design Decisions:
1. **Drop Extraction API:** We no longer convert PDFs to Markdown or chunk text.
2. **Page-Level Snapshots:** `pdf2image` is now used to render every page of the document into a high-res image.
3. **Local Vision Embeddings (`vidore/colSmol-500M`):** Each page image is embedded locally using `vidore/colSmol-500M`. At ~500M parameters, it comfortably runs within the 4GB VRAM constraint.
4. **Qdrant Multi-Vector Storage:** Updated `qdrant-client` to `>=1.11.0` to support `MultiVectorConfig` (MaxSim). We now have a single Qdrant collection called `vision_pages` that stores multi-vector patch embeddings along with the base64 page images.
5. **Direct Visual Context:** During chat, the user's text query is embedded using `colSmol-500M`, the top-K page images are retrieved, and the base64 images are sent directly to the `gemma-4-31B-it` VLM on the FM Gateway for grounded answering.

#### Files Changed:
- `pyproject.toml` (Added `colpali-engine`, `pdf2image`, updated `qdrant-client`)
- `ask_me/config.py` (Added `VISION_RETRIEVER_MODEL`)
- `ask_me/models/vision_retriever.py` (New local singleton for ColSmolVLM)
- `ask_me/ingestion/converter.py` (Swapped API call for `pdf2image` rendering)
- `ask_me/indexing/pipeline.py` (Refactored schema to MultiVector `vision_pages`)
- `ask_me/retrieval/search.py` (Updated to search MultiVector pages)
- `ask_me/generation/chat.py` (Passes raw retrieved page images to VLM)
- `ask_me/main.py` (Wired new ingestion flow)

### Next Steps
Test the ingestion pipeline end-to-end to ensure local VRAM usage remains stable and Qdrant successfully indexes the multi-vector representations.

### Post-Pivot Bug Fixes
1. **ColIdefics3 Architecture Mismatch:** Encountered an error (`'LlamaConfig' object has no attribute 'use_bidirectional_attention'`) when loading `vidore/colSmol-500M`. Fixed by bumping `colpali-engine` to `>=0.3.13` and switching instantiation classes to `ColIdefics3` and `ColIdefics3Processor` to match the model's actual architecture.
2. **Processor Input Bug:** Updated `vision_retriever.py` to use `process_images()` and `process_queries()` instead of direct processor calls, ensuring proper injection of visual prompt tokens.
3. **Data URI Bug:** Fixed a crash where the FM Gateway VLM rejected raw base64 images by properly formatting the Qdrant retrieval output as a Data URI (`data:image/jpeg;base64,...`) before injecting it into the LangGraph state.
4. **Ingestion Optimization:** Added an `is_document_indexed` check before processing files in `ask-me ingest` to skip already-indexed documents, saving massive amounts of compute time when appending new files to the directory.

### Next Steps
Deploy for a wider beta test and monitor response accuracy on complex diagram questions.

## Session 3 — 2026-08-24 (Current)

### Bug 1: Missing Debug Logs and Stuck Ingestion
**Error:** `ask-me ingest` appeared stuck, and no debug logs were shown even when `DEBUG_LOG=True` was set in `.env`.
**Root cause:** Third-party libraries (`transformers`, `huggingface_hub`) initialized the root logger upon import before `main.py` ran `logging.basicConfig()`, which silently caused Python to ignore our custom logging format and level.
**Fix:** Added `force=True` to `logging.basicConfig` in `main.py` to override any third-party loggers. Added detailed explicit `logger.debug` and `logger.info` checkpoints across `pipeline.py`, `converter.py`, and `vision_retriever.py` to show wait states (like downloading HuggingFace models, Qdrant startup, or invisible `win32com` dialogs).

### Bug 2: RAM OOM Error during Ingestion
**Error:** `Unable to allocate 9.00 MiB for an array...`
**Root cause:** `pdf2image` by default loads all pages of a PDF into a single Python list of PIL Images. For large documents, this triggered a massive burst in RAM usage (e.g., hundreds of 9MB images simultaneously), crashing the system before embedding even began.
**Fix:** Rewrote `extract_page_images` in `converter.py` to be a generator that uses `pdfinfo_from_path` to find total pages, and then extracts images in batches of 5 using the `first_page` and `last_page` arguments. `main.py` now loops over this generator, and `pipeline.py` embeds and stores just 5 images at a time before discarding them, strictly respecting both RAM limits and the 4GB VRAM constraint.

### Bug 3: Chat History Amnesia and Lazy Image Referencing
**Error 1:** The retriever only used the latest user message for vector search, causing follow-up questions (e.g., "Who approved it?") to yield zero relevant documents since context nouns were missing.
**Error 2:** The VLM response would sometimes lazily tell the user to "see the flowchart on page X" instead of extracting the information.
**Fix 1:** Modified `retrieve_node` in `chat.py` to combine the last two user messages into a single string for Qdrant `colSmol` retrieval, drastically improving context retention.
**Fix 2:** Injected a `CRITICAL INSTRUCTION` into the `system_prompt` in `chat.py` explicitly forbidding the VLM from referencing images or page numbers and forcing it to act as the user's "eyes" by fully transcribing/analyzing the visual data.

### Next Steps
Deploy fixes for wider testing and ensure users are pulling the latest batching pipeline for large PDFs.
