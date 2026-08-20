# Ask-Me: Local Multimodal RAG Pipeline

A Python CLI tool designed to build a fully local, offline-capable Multimodal RAG pipeline. It allows you to ask questions against a local corpus of technical documents (PPTX, Word, PDF) containing dense text, tables, charts, diagrams, and flowcharts.

This pipeline respects a tight 4GB VRAM constraint by offloading large model inference (LLM and Text Embeddings) to an internal FM Gateway API, while keeping Vector Storage and Image Embeddings strictly local.

## Architecture Highlights
- **Document Ingestion:** Recursively crawls directories. Uses native Windows COM (`win32com`) to perfectly convert `.docx` and `.pptx` to PDF entirely offline without formatting loss.
- **Extraction & OCR:** Sends PDFs to the FM Gateway for Markdown conversion. Automatically applies Windows native PowerShell OCR to images as a fallback to catch hidden text.
- **Dual Vector Storage:** Runs Qdrant locally via Docker. Uses two collections: `sections` (text chunks) and `visuals` (images).
- **Embeddings:** Text is embedded using the `bge-m3` model via the API. Images are embedded locally using `google/siglip-base-patch16-224`.
- **Chat Agent:** Powered by LangGraph to maintain chat history and seamlessly route context to the `gemma-4-31B-it` Vision-Language Model.

---

## Prerequisites

1. **Python 3.10+**
2. **Microsoft Office** (Installed locally on Windows to enable the DOCX/PPTX to PDF conversion)
3. **Windows 10/11** (Required for the built-in PowerShell OCR engine)
4. **Docker Desktop** (To run the local Qdrant vector database)
   - *If you don't have Docker installed, you can quickly install it via PowerShell as Administrator using the Windows Package Manager:*
     ```powershell
     winget install Docker.DockerDesktop
     ```
     *(Note: You will need to restart your computer and open Docker Desktop once to accept the terms before running containers).*

---

## Setup Instructions

### 1. Start Qdrant (Local Vector Database)
We use Qdrant to store vectors locally. Start a Qdrant container using Docker:

```bash
docker run -d -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant
```
*This exposes the Qdrant HTTP API on `localhost:6333` and saves your vectors to a persistent Docker volume.*

### 2. Install the Python Package
You can install the package directly from the Git repository. This will automatically download and install all dependencies (`transformers`, `torch`, `qdrant-client`, `langgraph`, etc.) and register the `ask-me` CLI command.

Run this command in your PowerShell terminal:
```bash
pip install "git+https://github.com/akshaymone/tools.git@feature/docx-translator#subdirectory=ask-me"
```

### 3. Configure the Environment
Create a `.env` file in the root directory (where you run the tool) with the following configurations:

```env
# API Connectivity
FM_GATEWAY_URL="https://fmgateway.proxem.dsone.3ds.com"
FM_GATEWAY_TOKEN="your_auth_token_here"

# Models
EMBEDDING_MODEL="BAAI/bge-m3"
VLM_MODEL="google/gemma-4-31B-it"

# Local Qdrant
QDRANT_HOST="localhost"
QDRANT_PORT="6333"

# Ingestion
INDEX_DIRECTORY="C:/Path/To/Your/Documents"
```

---

## How to Use the CLI

Once installed, the package exposes the `ask-me` command globally in your virtual environment.

### Step 1: Ingest Documents
To crawl your `INDEX_DIRECTORY`, convert files, run OCR, extract metadata, generate embeddings, and store them in Qdrant, simply run:

```bash
ask-me ingest
```
*Note: The first time you run this, it will take a moment to download the `< 1GB` local SigLIP model weights from HuggingFace to your cache.*

### Step 2: Chat with your Documents
To launch the interactive LangGraph agent and ask questions against your indexed documents:

```bash
ask-me chat
```

You can now chat naturally with the agent. It will maintain your conversation history in memory, automatically fetch the relevant document chunks and images from Qdrant via Reciprocal Rank Fusion (RRF), and formulate highly grounded technical answers.
