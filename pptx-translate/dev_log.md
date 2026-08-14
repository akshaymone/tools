# pptx-translate — Developer Log

> A running log of all development sessions, decisions, bugs, and fixes.
> Updated after every conversation so any AI or human can quickly catch up.

---

## Project Overview

**Goal:** Fully offline Python CLI tool to translate Korean `.pptx` files into English.  
**Security constraint:** Zero network calls during translation — all data stays on-machine.  
**Platform:** Windows (primary), cross-platform compatible.

### Final Stack

| Role | Library | Notes |
|---|---|---|
| PPTX I/O | `python-pptx` | Extract/write slide content |
| Text translation | `argostranslate` | Offline, Helsinki-NLP models |
| Image OCR | `pytesseract` | Wraps user's existing Tesseract install |
| Image rendering | `Pillow` | Paint over Korean, draw English |
| Progress | `tqdm` + `logging` | Batch visibility |
| Font | Segoe UI | Windows native; DejaVu Sans fallback |

### Repo Structure

```
pptx-translate/
├── translate.py              ← CLI entry point
├── requirements.txt
├── README.md
├── dev_log.md                ← this file
└── translator/
    ├── __init__.py
    ├── text_engine.py        ← argostranslate ko→en wrapper
    ├── image_handler.py      ← Tesseract OCR + Pillow redraw
    └── pptx_handler.py       ← python-pptx traversal + orchestration
```

---

## Session 1 — 2026-08-14 (Conversation `34c84aa5`)

### Context

User has Korean `.pptx` technical documents containing:
- Slide text/titles
- Image flowcharts
- Complex mixed-content images

Security requirement: **no data leaves the machine**. Requested a simple CLI tool.

### Design Decisions

| Decision | Rationale |
|---|---|
| Python (not PowerShell) | Richer ecosystem for PPTX, OCR, and NLP |
| `argostranslate` for translation | Fully offline after one-time model download; Helsinki-NLP quality |
| `pytesseract` for OCR | Wraps existing Tesseract install; no new OCR engine needed |
| `--psm 11` (sparse text mode) | Best for flowcharts — text scattered in boxes/arrows, not paragraphs |
| Translate per block, not per line | Preserves sentence context for better translation quality |
| Paragraph-level write-back in PPTX | Preserves font size, bold, italic, colour on all runs |
| Auto-scale small images 2–3× before OCR | Tesseract accuracy degrades significantly below ~150 dpi |
| In-place blob swap via `img_part._blob` | Keeps all slide geometry/positioning intact |
| English-only output | User explicitly requested no bilingual output |
| Segoe UI font | Windows-native, clean for technical docs; DejaVu Sans fallback |

### Image OCR Pipeline (Phase 2 Architecture)

```
Extract image bytes → PIL Image
       ↓
pytesseract.image_to_data(lang='kor', config='--psm 11')
       ↓
word-level bounding boxes + confidence + text
       ↓
Filter: drop below confidence threshold (default: 60%)
       ↓
Group adjacent words → logical text blocks (by line/block number)
       ↓
Translate each block (Korean → English)
       ↓
For each block:
  1. Sample surrounding pixels → detect background color
  2. Paint rectangle over original Korean text
  3. Auto-fit font size (English is ~1.3× longer than Korean)
  4. Draw translated English at same bounding box
       ↓
Re-embed modified image back into slide (same position/size)
```

### What Was Built

- 7 files, 923 lines of code
- **Commit `534143b`** — `feat: add offline Korean→English PPTX translator CLI`

### Bug Found During Testing

**Error:**
```
[ERROR] Translation engine failed to load: 'Language' object has no attribute 'translations'
```

**Root cause:** `Language.translations` attribute was removed in `argostranslate >= 1.9`.

**Fix:** Switch to the stable public API `get_translation_from_codes('ko', 'en')` with a `getattr` fallback for older versions.

- **Commit `1f5cdc7`** — `fix: update argostranslate API for newer versions`

---

## Session 2 — 2026-08-14 (Conversation `be6cbda0`)

### Bug: Tool Fails When WiFi Is Off

**User report:** Translation worked with internet on. Fails when wifi turned off.

**Root cause analysis:**

`argostranslate` saves the downloaded model as a `.argosmodel` file on disk AND registers it in a local package registry. The registry entry can be lost (e.g., if AppData is cleared, or argostranslate is reinstalled). When `get_translation_from_codes()` returns `None`, the old code immediately tried to re-download — which fails offline.

**Fix: 3-Step Offline-First Model Loading**

| Step | What it does | Network? |
|---|---|---|
| 1 | Check argostranslate's local installed registry | ❌ No |
| 2 | Scan disk for cached `.argosmodel` file and install from it | ❌ No |
| 3 | Download from argostranslate online registry | ✅ Yes (one-time only) |

Once the model is downloaded once, **all future runs are 100% offline**, even if the registry is corrupted or argostranslate is reinstalled — Step 2 will find the cached file and recover without network.

**Files changed:**
- `translator/text_engine.py` — added `_find_cached_model_file()` and `_install_from_file()` methods; split `_install_package()` into `_download_and_install()` with a proper offline error message
- `translate.py` — removed misleading "Ensure you have internet access" error line

- **Commit `3921e64`** — `fix: proper offline support — install from cached .argosmodel if available`

---

## Commit History

| Commit | Description |
|---|---|
| `534143b` | feat: add offline Korean→English PPTX translator CLI |
| `1f5cdc7` | fix: update argostranslate API for newer versions |
| `3921e64` | fix: proper offline support — install from cached .argosmodel if available |
| `6707946` | fix: prevent stanza network calls offline; improve tessdata error message |
| `9c25e9e` | docs: add dev_log.md with full session history and design decisions |
| `f3d25bb` | fix: replace image blob-swap with notes-based OCR translation |
| `b5c9999` | docs: update dev_log — fix pending commit hash, add session 3 commits, update tips |
| `ee73791` | docs: update README — new image→notes approach, --min-text-height flag, setup simplification |
| `ee631cd` | fix: add Korean content filters to image OCR — prevent garbage translation |
| `d3828d1` | fix: stricter OCR filters — raise thresholds, add translation dedup and min-word filter |

---

## Known Behaviours / Tips

- **First run needs internet** — downloads the `ko→en` argostranslate model (~100MB). Every run after is offline.
- **Tesseract Korean data** — `kor.traineddata` must be in your Tesseract `tessdata/` folder. Download from [tesseract-ocr/tessdata](https://github.com/tesseract-ocr/tessdata) if missing.
- **Tune OCR confidence** — `--confidence 40` catches more text (but more noise); `--confidence 75` is stricter (may miss faint text). Default is `60`.
- **Tune image text size** — `--min-text-height 18` (default) skips tiny labels. Increase (e.g. `30`) for only large headings; decrease (e.g. `12`) to capture more text in notes.
- **Mixed-language slides** — use `--lang kor+eng` if slides mix Korean and English.
- **Skip image OCR** — use `--skip-images` if you only care about translating text boxes.
- **Dry run** — use `--dry-run` to preview without writing output files.
- **Images are never modified** — OCR text from images goes to speaker notes only (safe, no corruption risk).

---

## Quick Start (Windows)

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. First-time model download (internet required — ONE TIME ONLY)
python translate.py -i any_file.pptx -o ./output/
# It auto-downloads the model on first run

# 3. All subsequent runs — fully offline
python translate.py -i C:\path\to\docs\ -o C:\output\
```

---

## Open Items / Future Ideas

- [ ] Support other language pairs (e.g., Japanese `ja→en`, Chinese `zh→en`)
- [ ] Add `--download-model` flag for an explicit one-time setup step separate from translation
- [ ] Handle embedded charts/SmartArt (currently only bitmap images are processed)
- [ ] Confidence auto-tuning per image based on image resolution
- [ ] Progress bar per slide (not just per file)

---

## Session 3 — 2026-08-14 (Conversation `be6cbda0`, continued)

### Bug 1: `'SlidePart' object has no attribute 'related_parts'`

**Error:**
```
[WARNING] Failed to replace image blob [그림 2]: 'SlidePart' object has no attribute 'related_parts'
```

**Root cause:** `pptx_handler.py` line `shape.part.related_parts[rId]` uses `related_parts` (dict-style), which does not exist on `SlidePart`. The correct API is `shape.part.related_part(rId)` (method call). However rather than patching this, the entire image-blob-swap approach was abandoned in favour of a safer design.

### Bug 2: Some image text not getting translated

**Root cause:** The old approach required modifying the image in-place (OCR → paint over Korean → draw English). This was fragile for complex flowcharts and failed silently on many images.

### New Approach: Image text → Speaker Notes

**Decision:** Don't modify images at all. Instead:
1. OCR each image with Tesseract (`--psm 11` sparse mode)
2. Filter to only **considerable text** — blocks whose rendered pixel height ≥ `min_height` (default 18 px ≈ ~14 pt body text). Small axis labels, watermarks, tiny captions are skipped.
3. Translate each block
4. **Append all translations to the slide's speaker notes** under a labelled section `── Image Text (auto-translated) ──`

**Benefits:**
- Images are never touched → no corruption, no blob-swap errors
- Notes are easy to read while presenting
- `--min-text-height` CLI flag lets user tune what counts as "considerable"

### Files Changed

| File | What changed |
|---|---|
| `translator/image_handler.py` | Added `extract_text_for_notes(image_bytes, min_height)` method. Added `_ocr_dataframe()` and `_paragraph_text_and_height()` shared helpers. Old `process()` kept as legacy. |
| `translator/pptx_handler.py` | `_process_slide()` now collects image translations into a list, then calls `_append_image_notes()`. `_process_picture()` uses `extract_text_for_notes()` instead of blob replacement. Added `_MIN_TEXT_HEIGHT_PX = 18` constant. Added `min_text_height` param to `__init__`. |
| `translate.py` | Added `--min-text-height PX` CLI flag (default 18). Passes to `PPTXHandler`. |

### Speaker Notes Output Format (per slide)

```
[existing notes text, translated]

── Image Text (auto-translated) ──
1. Flow data enters the preprocessing module
2. System architecture overview
3. Output validation layer
```

### CLI Usage

```powershell
# Default — includes text >= 18px height in notes
python translate.py -i slides.pptx -o output/

# Stricter — only large headings (increase threshold)
python translate.py -i slides.pptx -o output/ --min-text-height 30

# More inclusive — smaller text too
python translate.py -i slides.pptx -o output/ --min-text-height 12
```

- **Commit `f3d25bb`** — `fix: replace image blob-swap with notes-based OCR translation`

---

## Session 4 — 2026-08-14 (Conversation `be6cbda0`, continued)

### Bug: Unusual / Garbage Translation Output from Images (Offline Mode)

**User report:** Image OCR translations in speaker notes are producing very unusual, incorrect text when running offline.

**Root cause:** The `extract_text_for_notes()` method had **zero content quality filters** before sending text to argostranslate. Every OCR fragment — regardless of whether it was actual Korean text — was passed straight to the translator. This caused:

| Problem | Result |
|---|---|
| OCR picks up English labels, axis numbers, symbols | Argostranslate tries to "translate" them → garbage |
| Broken/partial Korean syllables from noisy images | Translator produces nonsense |
| Very short 1–2 character fragments | Single-syllable translation is meaningless |
| Same text block detected multiple times | Repeated identical notes |
| Stray ASCII punctuation around Korean words | Distorts translation input |

**Fix: 5-Layer Filter Pipeline in `extract_text_for_notes()`**

Each OCR block now passes through these gates before reaching argostranslate:

| Filter | What it checks | Threshold |
|---|---|---|
| 1. Size | Block pixel height >= min_height | Default 18 px |
| 2. Hangul count | Must have >= 3 Hangul characters | `_MIN_HANGUL_CHARS = 3` |
| 3. Korean ratio | >= 25% of chars must be Hangul | `_MIN_KOREAN_RATIO = 0.25` |
| 4. OCR cleanup | Strip stray ASCII/punctuation around Korean; drop non-Korean lines | `_clean_ocr_text()` |
| 5. Deduplication | Same Korean text only translated once per image | `seen_raw: set` |

**New module-level helpers added to `image_handler.py`:**
- `_HANGUL_RE` — compiled regex for Hangul Unicode ranges (AC00–D7A3, 1100–11FF, 3130–318F)
- `_korean_ratio(text)` — fraction of characters that are Hangul
- `_is_korean_text(text)` — True if text passes both Hangul count and ratio thresholds
- `_clean_ocr_text(text)` — strips non-Korean lines, stray ASCII punctuation

**Files changed:**
- `translator/image_handler.py` — added `re`, `unicodedata` imports; added 4 filter utilities; rewrote `extract_text_for_notes()` with 5-filter pipeline

- **Commit `ee631cd`** — `fix: add Korean content filters to image OCR — prevent garbage translation`

### Session 4 Follow-up — Filters Still Too Loose

**User report (actual output):**
- "About Us" appearing 11 times, "Teen" 3 times — dedup only on source, not on translated output
- "YepTube", "Teen", "Home", "Bathroom", "Color" — single-word garbage from isolated syllables
- Biblical-style hallucinations — Helsinki-NLP offline model struggling with technical jargon

**Additional fixes applied (commit `ee631cd`+):**

| Fix | Detail |
|---|---|
| Raise `_MIN_HANGUL_CHARS` 3→5 | Stricter — needs more Korean content |
| Raise `_MIN_KOREAN_RATIO` 0.25→0.40 | Stricter — 40% of text must be Hangul |
| Add `_MIN_SOURCE_LEN = 6` | Micro-fragments (< 6 chars) skipped entirely |
| Add `_MIN_TRANSLATED_WORDS = 2` | 1-word translations killed ("Teen", "Home", etc.) |
| Add `seen_translated` dedup | "About Us" ×11 now appears at most once |

- **Commit `d3828d1`** — `fix: stricter OCR filters — raise thresholds, add translation dedup and min-word filter`
