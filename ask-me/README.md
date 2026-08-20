# Ask-Me: Local Multimodal RAG Pipeline

A Python CLI tool designed to build a fully local, offline-capable Multimodal RAG pipeline. It allows you to ask questions against a local corpus of technical documents (PPTX, Word, PDF) containing dense text, tables, charts, diagrams, and flowcharts.

This pipeline respects a tight 4GB VRAM constraint by offloading large model inference (LLM and Text Embeddings) to an internal FM Gateway API, while keeping Vector Storage and Image Embeddings strictly local.

## Architecture Highlights
- **Document Ingestion:** Recursively crawls directories. Uses native Windows COM (`win32com`) to perfectly convert `.docx` and `.pptx` to PDF entirely offline without formatting loss.
- **Page-Level Vision-RAG:** Converts every PDF page into a high-resolution image snapshot using `pdf2image`. This completely bypasses error-prone text extraction and OCR steps!
- **Multi-Vector Storage:** Runs Qdrant locally via Docker, using a single `vision_pages` collection that supports MultiVector MAX_SIM distance.
- **Local Vision Embeddings:** Page images and user queries are embedded locally using the lightweight `vidore/colSmol-500M` model. At ~500M parameters, it comfortably runs within the 4GB VRAM constraint.
- **Chat Agent:** Powered by LangGraph. When asking a question, it retrieves the most relevant page snapshots from Qdrant and sends the raw images directly to the `gemma-4-31B-it` Vision-Language Model via the FM Gateway for grounded answering.

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
5. **Poppler** (Required by `pdf2image` to convert PDFs into page images)
   - **Windows:** Download the latest `Release-xx.xx.x-0.zip` from [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases/), extract it, and add the `Library/bin` or `poppler-xx/bin` folder to your system `PATH`.
   - **Mac:** `brew install poppler`
   - **Linux:** `sudo apt-get install poppler-utils`

---

## Setup Instructions

### 1. Start Qdrant (Local Vector Database)
We use Qdrant to store vectors locally. We have provided a `docker-compose.yml` file to make this easy and secure.

**Storage Warning (Saving your C:\ Drive):** 
By default, Docker saves data inside its own virtual machine on your C:\ drive. To prevent this, our configuration uses a **Bind Mount**. It will create a folder called `qdrant_data` directly inside this project folder. 
*If you want to store the data on an entirely different drive, open `docker-compose.yml` and change `./qdrant_data` to something like `D:/qdrant_data` before running the command below.*

**Step-by-step:**
1. Open PowerShell.
2. Use the `cd` command to navigate to the `ask-me` directory (where the `docker-compose.yml` file is located).
3. Run the following command to start the database in the background:

```bash
docker-compose up -d
```
*(To stop the database later, run `docker-compose down` from the same folder).*

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
VLM_MODEL="google/gemma-4-31B-it"
VISION_RETRIEVER_MODEL="vidore/colSmol-500M"

# Local Qdrant
QDRANT_HOST="localhost"
QDRANT_PORT="6333"

# Ingestion Settings
INDEX_DIRECTORY="C:/Path/To/Your/Documents"
DEBUG_LOG="False"
```

---

## How to Use the CLI

Once installed, the package exposes the `ask-me` command globally in your virtual environment.

### Step 1: Ingest Documents
To crawl your `INDEX_DIRECTORY`, convert files, render page images, generate local vision embeddings, and store them in Qdrant, simply run:

```bash
ask-me ingest
```
*Note: The first time you run this, it will take a moment to download the `< 1GB` local ColSmol model weights from HuggingFace to your cache.*

### Step 2: Chat with your Documents
To launch the interactive LangGraph agent and ask questions against your indexed documents:

```bash
ask-me chat
```

You can now chat naturally with the agent. It will maintain your conversation history in memory, automatically fetch the relevant document chunks and images from Qdrant via Reciprocal Rank Fusion (RRF), and formulate highly grounded technical answers.
