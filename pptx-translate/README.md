# pptx-translate (Offline PPTX Translator & Extractor)

Offline PowerPoint text translator and Markdown extractor.  
Translates Korean `.pptx` files to English by directly manipulating XML to preserve exact styling. Also includes a utility to extract all slide text and embedded images into a clean Markdown layout. Uses local Tesseract OCR to extract image text.

---

## Requirements

| Tool | Notes |
|------|-------|
| Python 3.10+ | |
| Tesseract OCR | Must be on `PATH` |
| Korean Tesseract data | `kor.traineddata` must be in your `tessdata` folder |

---

## Setup

```powershell
# 1. Install Python dependencies
pip install -r requirements.txt
```

> **Missing Korean tessdata?**  
> Download [`kor.traineddata`](https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata)  
> and place it in your Tesseract `tessdata/` folder (e.g. `C:\Program Files\Tesseract-OCR\tessdata\`).

---

## Usage

```powershell
# Extract a single file (outputs to ./extracted/report.md)
python extract.py -i report.pptx

# Extract an entire folder
python extract.py -i C:\docs\pptx\ -o C:\docs\extracted\

# Skip image OCR and extraction (faster)
python extract.py -i slides.pptx --skip-images

# Raise OCR confidence bar (fewer but more accurate detections on images)
python extract.py -i slides.pptx --confidence 75

# Verbose debug output
python extract.py -i slides.pptx --verbose
```

### All flags

| Flag | Default | Description |
|------|---------|-------------|
| `-i / --input` | *(required)* | `.pptx` file or folder |
| `-o / --output` | `./extracted` | Output folder or `.md` file |
| `--skip-images` | off | Skip saving images and performing OCR |
| `--confidence` | `60` | Min Tesseract word confidence (0–100) |
| `--min-text-height` | `18` | Min pixel height of OCR text block. |
| `--lang` | `kor` | Tesseract language code |
| `--verbose` | off | Debug logging |

---

## What gets extracted

| Content | How |
|---------|-----|
| Slide titles | ✅ Markdown list |
| Body text / bullet points | ✅ Markdown list |
| Text boxes | ✅ Markdown list |
| Table cells | ✅ Markdown tables |
| Group shapes (recursively) | ✅ Markdown list |
| Speaker notes | ✅ Markdown under `### Speaker Notes` |
| Embedded images (JPEG/PNG) | ✅ Saved to disk and linked in Markdown |
| Image Text (Korean) | ✅ Extracted via OCR and placed under image links |

> **100% Offline.** All processing happens locally on your machine. Images are extracted as they are, without modification. 

---

## Project layout
 
 ```
 pptx-translate/
 ├── extract.py              ← Markdown extraction CLI
 ├── xml_translate.py        ← Direct XML translation CLI
 ├── requirements.txt
 ├── README.md
 ├── dev_log.md              ← full session history and design decisions
 └── translator/
     ├── __init__.py
     ├── image_handler.py    ← Tesseract OCR
     └── pptx_handler.py     ← python-pptx traversal + orchestration
 ```

---

## Direct XML Translation (`xml_translate.py`)

A secondary script is included to directly translate Korean PPTX files into English PPTX files by unzipping the archive and manipulating the `<a:t>` tags. This perfectly preserves all fonts, styles, and layouts.

Image text is extracted via Tesseract and appended to the Slide's Speaker Notes in the format: `Image Text: [Korean] -> [English]`. 

```powershell
# Direct XML translation (creates a new translated .pptx)
python xml_translate.py -i input.pptx -o output_english.pptx
```
