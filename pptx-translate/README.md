# pptx-translate

Offline Korean → English PowerPoint translator.  
No data leaves your machine after the one-time model download.

---

## Requirements

| Tool | Notes |
|------|-------|
| Python 3.10+ | |
| Tesseract OCR | Must be on `PATH` — already done ✔ |
| Korean Tesseract data | `kor.traineddata` must be in your `tessdata` folder |

---

## Setup

```powershell
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Download the ko→en translation model (ONE TIME — then fully offline)
#    Just run the translator normally — it auto-downloads on first run:
python extract.py -i any_file.pptx -o ./output/

#    After the first successful run the model is cached locally.
#    All future runs work with WiFi off.
```

> **Missing Korean tessdata?**  
> Download [`kor.traineddata`](https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata)  
> and place it in your Tesseract `tessdata/` folder (e.g. `C:\Program Files\Tesseract-OCR\tessdata\`).

---

## Usage

```powershell
# Translate a single file
python extract.py -i report.pptx -o report_en.pptx

# Translate an entire folder (preserves sub-folder structure)
python extract.py -i C:\docs\pptx\ -o C:\docs\translated\

# Text shapes only — skip image OCR (faster)
python extract.py -i slides.pptx -o slides_en.pptx --skip-images

# Raise OCR confidence bar (fewer but more accurate detections)
python extract.py -i slides.pptx -o slides_en.pptx --confidence 75

# Only include larger text from images in speaker notes (skip small labels)
python extract.py -i slides.pptx -o slides_en.pptx --min-text-height 30

# Preview what would be translated — writes nothing
python extract.py -i slides.pptx --dry-run

# Verbose debug output
python extract.py -i slides.pptx -o slides_en.pptx --verbose
```

### All flags

| Flag | Default | Description |
|------|---------|-------------|
| `-i / --input` | *(required)* | `.pptx` file or folder |
| `-o / --output` | `./translated` | Output file or folder |
| `--skip-images` | off | Skip OCR on embedded images entirely |
| `--confidence` | `60` | Min Tesseract word confidence (0–100) |
| `--min-text-height` | `18` | Min pixel height of OCR text block to include in notes. Increase to skip smaller text, decrease to capture more. |
| `--lang` | `kor` | Tesseract language code (`kor+eng` for mixed slides) |
| `--dry-run` | off | Print translations, write nothing |
| `--verbose` | off | Debug logging |

---

## What gets translated

| Content | How |
|---------|-----|
| Slide titles | ✅ In-place (text replaced, formatting preserved) |
| Body text / bullet points | ✅ In-place |
| Text boxes | ✅ In-place |
| Table cells | ✅ In-place |
| Group shapes (recursively) | ✅ In-place |
| Speaker notes | ✅ In-place |
| Embedded images (JPEG/PNG) | ✅ OCR → translated text appended to **speaker notes** |
| Embedded EMF/WMF vectors | ⚠️ Skipped (not raster images) |
| Rotated diagram labels | ⚠️ Best-effort by Tesseract |

> **Images are never modified.** Korean text found in images is extracted via
> Tesseract OCR, translated, and appended to the slide's speaker notes under
> the header `── Image Text (auto-translated) ──`. This avoids any risk of
> image corruption or layout breakage.

---

## Known Limitations

- **Rotated text** on flowchart arrows may be missed — Tesseract handles
  horizontal text best.
- **Very small labels** are skipped by default (`--min-text-height 18`).
  Lower this value to capture smaller text, at the cost of more noise.
- **Translation quality** depends on argostranslate's Helsinki-NLP model.
  Technical jargon and acronyms are usually preserved as-is.
- **Image text in notes only** — the flowchart images themselves remain in
  Korean; the English translation appears in the notes pane below each slide.

---

## Project layout

```
pptx-translate/
├── extract.py              ← CLI entry point
├── requirements.txt
├── README.md
├── dev_log.md                ← full session history and design decisions
└── translator/
    ├── __init__.py
    ├── text_engine.py        ← argostranslate wrapper (ko→en, offline-first)
    ├── image_handler.py      ← Tesseract OCR; extract_text_for_notes()
    └── pptx_handler.py       ← python-pptx traversal + orchestration
```
