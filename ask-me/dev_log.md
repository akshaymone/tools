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
