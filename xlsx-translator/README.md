# xlsx-translator — Korean XLSX Translator

Translates Korean `.xlsx` files into English by directly manipulating the underlying OOXML — **no python-openpyxl save involved**, so all original parts (charts, macros, SmartArt, custom XML) are preserved exactly.

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
pip install "git+https://github.com/akshaymone/tools.git#subdirectory=xlsx-translator"

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
xlsx-translator -i input.xlsx -o output_english.xlsx

# Override the LLM provider on the fly
xlsx-translator -i input.xlsx -o output_english.xlsx --provider ollama
xlsx-translator -i input.xlsx -o output_english.xlsx --provider office

# Only capture image text taller than 24px (filters out axis labels, tiny captions)
xlsx-translator -i input.xlsx -o output_english.xlsx --min-text-height 24

# Verbose mode — shows each <t> tag being translated and OCR results
xlsx-translator -i input.xlsx -o output_english.xlsx --verbose
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `-i` / `--input` | *(required)* | Input `.xlsx` file |
| `-o` / `--output` | *(required)* | Output `.xlsx` file |
| `--lang` | `kor` | OCR language hint (e.g. `ko-KR`) |
| `--min-text-height` | `5` | Minimum OCR text pixel height. Lines below this are ignored (filters small labels, watermarks) |
| `--provider` | *(from `.env`)* | LLM provider: `ollama` or `office` |
| `--verbose` | off | Enable debug-level logging |
| `--passthrough` | off | Unzip+rezip only — no changes. |
| `--skip-translate` | off | Run everything EXCEPT LLM translation calls. |
| `--save-stages` | off | Save checkpoints for inspection. |

---

## How it works

```
input.xlsx (original, untouched)
    │
    ▼
Unzip to temp directory
    │
    ├─► Batch OCR  (ocr_batch.ps1)
    │       Runs Windows.Media.Ocr.OcrEngine on all images in xl/media/
    │       Outputs bounding-box heights + Korean text → ocr_results.json
    │       Filters: lines below --min-text-height are discarded
    │
    ├─► inject_ocr_text_as_textbox()
    │       Injects a yellow text box (Shape) containing the OCR translations
    │       right next to the original image directly inside xl/drawings/drawing*.xml.
    │
    ├─► translate_xml_file()
    │       Translates xl/sharedStrings.xml, sheet*.xml, chart*.xml, and drawing*.xml.
    │       Regex finds every <t> and <a:t> tag
    │       If content contains Hangul → LLM translates → write back in-place
    │       clean_text() strips control chars and newlines before injection
    │
    ├─► Pre-zip XML validation
    │       ElementTree.parse() checks every .xml — logs [XML INVALID] on failure
    │
    └─► Re-zip with forward-slash arcnames  →  output.xlsx
```

> **Why not python-openpyxl for saving?**  
> `python-openpyxl` silently drops parts it doesn't understand perfectly when saving. This causes Excel's repair
> prompt and permanent content loss for complex workbooks. We unzip the original directly and only append/replace
> content using raw string manipulation.

---

## Output

- **Workbook text** — Korean `<t>` content in `sharedStrings.xml` and sheets is translated in-place; all fonts, sizes, colours and styles are preserved.
- **Images** — Never modified. OCR results are appended as a yellow text box overlaid next to the images in the worksheet:
  ```
  Image Text: 데이터 흐름 -> Data flow
  ```

---

## Debugging

**OCR log** — saved alongside the output file as `<output_stem>_ocr_logs/ocr_batch.log`.  
Check for the version line (`ocr_batch.ps1 v8 starting`) to confirm the latest script is running.

**XML validation** — if any `.xml` file is malformed before zipping, the log shows:
```
[WARNING] [XML INVALID] xl/sharedStrings.xml — ...
```

**Verbose mode** — `--verbose` prints every `<t>` translation and OCR match.

---

## Project layout

```
xlsx-translator/
├── pyproject.toml          ← Dependencies and package metadata (v0.1.0)
├── MANIFEST.in             ← Ensures ocr_batch.ps1 is bundled in the wheel
├── .env.example            ← LLM configuration template
├── xlsx_translator/
│   ├── main.py             ← CLI entry point; ZIP unpack, translate, repack
│   ├── llm_factory.py      ← LLM provider factory (Ollama, Office)
│   ├── image_handler.py    ← Calls ocr_batch.ps1 and parses results
│   └── ocr_batch.ps1       ← Native Windows Media OCR (PowerShell 5.1, WinRT async)
└── README.md
```
