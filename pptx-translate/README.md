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
python -c "
import argostranslate.package, argostranslate.translate
argostranslate.package.update_package_index()
pkgs = argostranslate.package.get_available_packages()
pkg = next(p for p in pkgs if p.from_code=='ko' and p.to_code=='en')
pkg.install()
print('Model ready.')
"
```

---

## Usage

```powershell
# Translate a single file
python translate.py -i report.pptx -o report_en.pptx

# Translate an entire folder (preserves sub-folder structure)
python translate.py -i C:\docs\pptx\ -o C:\docs\translated\

# Text shapes only — skip image OCR (faster)
python translate.py -i slides.pptx -o slides_en.pptx --skip-images

# Raise OCR confidence bar (fewer but more accurate detections)
python translate.py -i slides.pptx -o slides_en.pptx --confidence 75

# Preview what would be translated — writes nothing
python translate.py -i slides.pptx --dry-run

# Verbose debug output
python translate.py -i slides.pptx -o slides_en.pptx --verbose
```

### All flags

| Flag | Default | Description |
|------|---------|-------------|
| `-i / --input` | *(required)* | `.pptx` file or folder |
| `-o / --output` | `./translated` | Output file or folder |
| `--skip-images` | off | Skip OCR on embedded images |
| `--confidence` | `60` | Min Tesseract word confidence (0–100) |
| `--lang` | `kor` | Tesseract language code (`kor+eng` for mixed) |
| `--dry-run` | off | Print translations, write nothing |
| `--verbose` | off | Debug logging |

---

## What gets translated

| Content | Translated? |
|---------|------------|
| Slide titles | ✅ |
| Body text / bullet points | ✅ |
| Text boxes | ✅ |
| Table cells | ✅ |
| Group shapes (recursively) | ✅ |
| Speaker notes | ✅ |
| Embedded images (JPEG/PNG) | ✅ via Tesseract OCR |
| Embedded EMF/WMF vectors | ⚠️ Skipped (not raster images) |
| Rotated diagram labels | ⚠️ Best-effort |

---

## Known Limitations

- **Rotated text** on flowchart arrows may be missed or imprecise — Tesseract
  handles horizontal text best.
- **Very small labels** (<12 px in the image) are often below Tesseract's
  detection threshold. Try `--confidence 40` to catch more (at the cost of
  more false positives).
- **English text is ~30% longer** than Korean on average. The font is
  auto-shrunk to fit each block's bounding box; very tight diagram boxes
  may display in a small font.
- **Textured / gradient backgrounds** use an averaged colour fill — the patch
  may be slightly visible on complex backgrounds.
- **Translation quality** depends on argostranslate's Helsinki-NLP model.
  Technical jargon and acronyms are usually preserved as-is.

---

## Project layout

```
pptx-translate/
├── translate.py              ← CLI entry point
├── requirements.txt
├── README.md
└── translator/
    ├── __init__.py
    ├── text_engine.py        ← argostranslate wrapper (ko→en)
    ├── image_handler.py      ← Tesseract OCR + Pillow redraw pipeline
    └── pptx_handler.py       ← python-pptx traversal + orchestration
```
