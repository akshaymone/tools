# docx-translator — Korean DOCX Translator

Translates Korean `.docx` files into English by directly manipulating the underlying OOXML — **no python-docx save involved**, so all original parts (charts, SmartArt, media, custom XML) are preserved exactly.

Image text is extracted via the **native Windows Media OCR API** (built into Windows 10/11 — no Tesseract, no external install).  
Translation is powered by the `agents` package LLM factory, supporting local **Ollama** or the **Office API**.

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Windows 10/11 | Required for native Windows Media OCR via PowerShell |
| Korean Language Pack | Install in **Windows Settings → Time & Language → Language & Region** |
| `agents` package | Must be installed and configured in your Python environment |

---

## Setup

```powershell
# 1. Install the translator package directly from GitHub
pip install "git+https://github.com/akshaymone/tools.git#subdirectory=docx-translator"

# 2. Copy the example config and fill in your LLM settings
copy .env.example .env
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
docx-translator -i input.docx -o output_english.docx

# Override the LLM provider on the fly
docx-translator -i input.docx -o output_english.docx --provider ollama
docx-translator -i input.docx -o output_english.docx --provider office

# Only capture image text taller than 24px (filters out axis labels, tiny captions)
docx-translator -i input.docx -o output_english.docx --min-text-height 24

# Verbose mode — shows each <w:t> tag being translated and OCR results
docx-translator -i input.docx -o output_english.docx --verbose
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `-i` / `--input` | *(required)* | Input `.docx` file |
| `-o` / `--output` | *(required)* | Output `.docx` file |
| `--lang` | `kor` | OCR language hint (e.g. `ko-KR`) |
| `--min-text-height` | `5` | Minimum OCR text pixel height. Lines below this are ignored (filters small labels, watermarks) |
| `--provider` | *(from `.env`)* | LLM provider: `ollama` or `office` |
| `--verbose` | off | Enable debug-level logging |

---

## How it works

```
input.docx (original, untouched)
    │
    ▼
Unzip to temp directory
    │
    ├─► Batch OCR  (ocr_batch.ps1)
    │       Runs Windows.Media.Ocr.OcrEngine on all images in word/media/
    │       Outputs bounding-box heights + Korean text → ocr_results.json
    │       Filters: lines below --min-text-height are discarded
    │
    ├─► translate_xml_file()  [per document, header, footer XML]
    │       Regex finds every <w:p> paragraph and <w:t> text tag
    │       If content contains Hangul → LLM translates → write back in-place
    │       clean_text() strips control chars and newlines before injection
    │
    ├─► inject_ocr_text()  [only in document.xml]
    │       Injects Korean + English OCR pairs as proper <w:p><w:r><w:t> paragraphs
    │       immediately following the image tag (<w:drawing>).
    │
    ├─► Pre-zip XML validation
    │       ElementTree.parse() checks every .xml — logs [XML INVALID] on failure
    │
    └─► Re-zip with forward-slash arcnames  →  output.docx
```

> **Why not python-docx for saving?**  
> `python-docx` silently drops any OOXML part it doesn't understand (charts, SmartArt, ink,
> video, custom XML, external data connections) when saving. This causes PowerPoint's repair
> prompt and permanent content loss. We unzip the original directly and only append/replace
> content using raw string manipulation.

---

## Output

- **Document text** — Korean `<w:t>` content is translated in-place; all fonts, sizes, colours and styles are preserved.
- **Images** — Never modified. OCR results are appended directly below the images in the document as an italicised paragraph:
  ```
  Image Text: 데이터 흐름 -> Data flow
  ```

---

## Debugging

**OCR log** — saved alongside the output file as `<output_stem>_ocr_logs/ocr_batch.log`.  
Check for the version line (`ocr_batch.ps1 v8 starting`) to confirm the latest script is running.

**XML validation** — if any `.xml` file is malformed before zipping, the log shows:
```
[WARNING] [XML INVALID] word/document.xml — ...
```

**Verbose mode** — `--verbose` prints every `<w:t>` translation and OCR match.

---

## Project layout

```
docx-translator/
├── pyproject.toml          ← Dependencies and package metadata (v0.1.0)
├── MANIFEST.in             ← Ensures ocr_batch.ps1 is bundled in the wheel
├── .env.example            ← LLM configuration template
├── docx_translator/
│   ├── main.py             ← CLI entry point; ZIP unpack, translate, repack
│   ├── image_handler.py    ← Calls ocr_batch.ps1 and parses results
│   └── ocr_batch.ps1       ← Native Windows Media OCR (PowerShell 5.1, WinRT async)
├── README.md
└── dev_log.md              ← Full session history, bug log, design decisions
```

---

## Known behaviours

- **First run** needs the `agents` package set up and your LLM reachable.
- **Korean Language Pack** must be installed — the Windows OCR engine silently returns no results without it.
- **Mixed-language documents** — English text in `<w:t>` tags is left untouched (Hangul filter).
- Documents without any Korean text pass through unchanged.
