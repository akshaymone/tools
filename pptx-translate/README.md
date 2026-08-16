# translator (Korean PPTX Translator)

Offline PowerPoint text translator and Markdown extractor.  
Translates Korean `.pptx` files to English by directly manipulating XML to preserve exact styling. Image text is extracted via **native Windows OCR** (no external tools required).
Now powered by the `agents` package LLM models (supports both local Ollama and the Office API).

---

## Requirements

| Tool | Notes |
|------|-------|
| Python 3.10+ | |
| Windows 10/11 | Required for native Windows Media OCR API |
| Korean Language Pack | Must be installed in Windows Settings for Korean OCR |

---

## Setup

The tool is packaged as `translator` and relies on the `agents` package being installed in your environment.

```powershell
# 1. Install directly from Git
pip install "git+https://github.com/akshaymone/tools.git#subdirectory=pptx-translate"

# 2. Configure Environment
# Copy the example config and adjust as needed
copy .env.example .env
```

---

## Usage

### 1. Direct XML Translation (Primary Tool)

This command translates Korean `.pptx` files into English `.pptx` files by unzipping the archive and manipulating the `<a:t>` tags. This perfectly preserves all fonts, styles, and layouts.

It leverages the LLM setup from the `agents` package. Images are batched and processed using a PowerShell background script calling native Windows OCR. Both the Korean text and its translation are injected into the speaker notes.

```powershell
# Translate using the default provider from your .env
translator -i input.pptx -o output_english.pptx

# Force a specific provider
translator -i input.pptx -o output_english.pptx --provider ollama
translator -i input.pptx -o output_english.pptx --provider office
```

### 2. Markdown Extraction (`extract.py`) - Secondary Tool

Extract all slide text and embedded images into a clean Markdown layout.

```powershell
# Extract a single file (outputs to ./extracted/report.md)
python extract.py -i report.pptx

# Extract an entire folder
python extract.py -i C:\docs\pptx\ -o C:\docs\extracted\

# Skip image OCR and extraction (faster)
python extract.py -i slides.pptx --skip-images
```

---

## Project layout
 
 ```
 pptx-translate/
 ├── pyproject.toml          ← Packaging and dependencies
 ├── MANIFEST.in             ← Package data inclusion rules
 ├── .env.example            ← Configuration template
 ├── translator/             ← Main package source
 │   ├── main.py             ← Direct XML translation CLI (`translator` command)
 │   ├── image_handler.py    ← Orchestrates PowerShell OCR batching
 │   ├── pptx_handler.py     ← Handles markdown extraction
 │   └── ocr_batch.ps1       ← Native Windows OCR logic in PowerShell
 ├── extract.py              ← Markdown extraction CLI
 ├── README.md
 └── dev_log.md              ← Full session history and design decisions
 ```
