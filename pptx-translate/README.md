# translator — Korean PPTX Translator

Translates Korean `.pptx` files into English by directly manipulating the underlying OOXML — **no python-pptx save involved**, so all original parts (charts, SmartArt, media, custom XML) are preserved exactly.

Image text is extracted via the **native Windows Media OCR API** (built into Windows 10/11 — no Tesseract, no external install).  
Translation is powered by a built-in LLM factory (`llm_factory.py`), supporting local **Ollama** or the **Office API**.

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Windows 10/11 | Required for native Windows Media OCR via PowerShell |
| Korean Language Pack | Install in **Windows Settings → Time & Language → Language & Region** |

---

## Setup

```powershell
# 1. Install the translator package directly from GitHub
pip install "git+https://github.com/akshaymone/tools.git#subdirectory=pptx-translate"

# 2. Install your chosen LLM provider dependencies
# For Ollama: pip install langchain-ollama
# For Office: pip install langchain-openai httpx

# 3. Create the config directory and copy the template
mkdir ~/.translator
copy .env.example ~/.translator/.env
```

### `.env` keys

| Key | Description |
|---|---|
| `LLM_PROVIDER` | Default provider: `ollama` or `office` |
| `OLLAMA_BASE_URL` | Ollama server URL (e.g. `http://localhost:11434`) |
| `OLLAMA_MODEL` | Model name (e.g. `gemma3:12b`) |

---

## Usage

```powershell
# Translate using the provider configured in .env
translator -i input.pptx -o output_english.pptx

# Override the LLM provider on the fly
translator -i input.pptx -o output_english.pptx --provider ollama
translator -i input.pptx -o output_english.pptx --provider office

# Only capture image text taller than 24px (filters out axis labels, tiny captions)
translator -i input.pptx -o output_english.pptx --min-text-height 24

# Verbose mode — shows each <a:t> tag being translated and OCR results
translator -i input.pptx -o output_english.pptx --verbose
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `-i` / `--input` | *(required)* | Input `.pptx` file |
| `-o` / `--output` | *(required)* | Output `.pptx` file |
| `--lang` | `kor` | OCR language hint (e.g. `ko-KR`) |
| `--min-text-height` | `5` | Minimum OCR text pixel height. Lines below this are ignored (filters small labels, watermarks) |
| `--provider` | *(from `.env`)* | LLM provider: `ollama` or `office` |
| `--verbose` | off | Enable debug-level logging |
| `--passthrough` | off | Unzip+rezip only — no changes. |
| `--skip-translate` | off | Run everything EXCEPT LLM translation calls. |
| `--skip-notes` | off | Skip `ensure_notes_slides()`. |
| `--save-stages` | off | Save checkpoints for inspection. |

---

## How it works

```
input.pptx (original, untouched)
    │
    ▼
Unzip to temp directory
    │
    ├─► ensure_notes_slides()
    │       For every slide missing a notes slide:
    │       • Write notesSlide{N}.xml from a minimal XML template
    │       • Write notesSlide{N}.xml.rels
    │       • Patch slide{N}.xml.rels to add the notesSlide relationship
    │       • Patch [Content_Types].xml to register the new part
    │       All done via raw string writes — python-pptx never called for saving.
    │
    ├─► Batch OCR  (ocr_batch.ps1)
    │       Runs Windows.Media.Ocr.OcrEngine on all images in ppt/media/
    │       Outputs bounding-box heights + Korean text → ocr_results.json
    │       Filters: lines below --min-text-height are discarded
    │
    ├─► translate_xml_file()  [per slide + notes XML]
    │       Regex finds every <a:t>…</a:t> tag
    │       If content contains Hangul → LLM translates → write back in-place
    │       clean_text() strips control chars and newlines before injection
    │
    ├─► append_to_notes_xml()  [per slide with OCR hits]
    │       Injects Korean + English OCR pairs as proper <a:p><a:r><a:t> paragraphs
    │       into the body placeholder txBody — one paragraph per text block
    │
    ├─► Pre-zip XML validation
    │       ElementTree.parse() checks every .xml — logs [XML INVALID] on failure
    │
    └─► Re-zip with forward-slash arcnames  →  output.pptx
```

> **Why not python-pptx for saving?**  
> `python-pptx` silently drops any OOXML part it doesn't understand (charts, SmartArt, ink,
> video, custom XML, external data connections) when saving. This causes PowerPoint's repair
> prompt and permanent content loss. We unzip the original directly and only append/replace
> content using raw string manipulation.

---

## Output

- **Slide text** — Korean `<a:t>` content is translated in-place; all fonts, sizes, colours and styles are preserved.
- **Speaker notes** — Existing Korean notes text is translated. OCR results from images are appended as new paragraphs:
  ```
  Image Text: 데이터 흐름 -> Data flow
  Image Text: 처리 모듈 -> Processing module
  ```
- **Images** — Never modified. OCR results go to speaker notes only.

---

## Debugging

**OCR log** — saved alongside the output file as `<output_stem>_ocr_logs/ocr_batch.log`.  
Check for the version line (`ocr_batch.ps1 v8 starting`) to confirm the latest script is running.

**XML validation** — if any `.xml` file is malformed before zipping, the log shows:
```
[WARNING] [XML INVALID] ppt/notesSlides/notesSlide2.xml — ...
```

**Verbose mode** — `--verbose` prints every `<a:t>` translation and OCR match.

---

## Project layout

```
pptx-translate/
├── pyproject.toml          ← Dependencies and package metadata (v0.1.3)
├── MANIFEST.in             ← Ensures ocr_batch.ps1 is bundled in the wheel
├── .env.example            ← LLM configuration template
├── translator/
│   ├── main.py             ← CLI entry point; ZIP unpack, notes init, translate, repack
│   ├── llm_factory.py      ← LLM provider factory (Ollama, Office)
│   ├── image_handler.py    ← Calls ocr_batch.ps1 and parses results
│   ├── pptx_handler.py     ← Legacy markdown extraction helpers
│   └── ocr_batch.ps1       ← Native Windows Media OCR (PowerShell 5.1, WinRT async)
├── extract.py              ← Standalone Markdown extraction CLI (secondary tool)
├── README.md
└── dev_log.md              ← Full session history, bug log, design decisions
```

---

## Known behaviours

- **First run** needs your LLM reachable (Ollama running locally, or Office API endpoint configured).
- **Korean Language Pack** must be installed — the Windows OCR engine silently returns no results without it.
- **Mixed-language slides** — English text in `<a:t>` tags is left untouched (Hangul filter).
- **Images are never modified** — OCR text goes to speaker notes only.
- Slides without any Korean text pass through unchanged.
