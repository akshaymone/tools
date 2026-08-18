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

---

## Session 5 — 2026-08-14 (Conversation `Current`)

### Context
User reported that translation was producing explicit/garbage texts and opted to pivot the tool. The new goal: drop translation entirely, extract Korean text, and format it cleanly into a Markdown document reflecting the PPT layout. Also extract the actual images from the presentation, save them locally, and link them directly in the Markdown file using standard `![Image](path)` syntax, making validation easy alongside clear slide numbers.

### Architectural Pivot
- **Removed Argostranslate**: Completely removed `argostranslate`, `stanza`, `spacy` and `text_engine.py` to eliminate heavy, noisy translation logic.
- **Renamed Entry Point**: Changed `translate.py` to `extract.py`.
- **Markdown Generation**: Rather than writing modifications back into the PPTX files, the tool now generates a structured `[filename].md` file.
- **Image Extraction**: Extracted images from the PPTX are written to a sidecar folder (e.g., `./presentation_images/`) and linked natively in the Markdown text.
- **Retained Quality Filters**: The Tesseract OCR still applies the Korean-only filter heuristics from previous sessions to ensure only actual Korean text is extracted from images, keeping noise to a minimum.

### New Output Format
```markdown
## Slide 1
- Heading Text

### Speaker Notes
- Note text

### Images
#### Image 1
![Slide 1 Image 1](./your_presentation_images/slide_1_img_1.png)

**Extracted Korean Text:**
- ... (Korean OCR results here, if any) ...
```

### Commit History (Session 5)

| Commit | Description |
|---|---|
| `c0b346e` | refactor: simplify to MD text extraction (remove translation) |
| `3e4fe05` | feat: extract and link images in markdown |

---

## Session 6 — 2026-08-14 (Conversation `Current`)

### Context
User reported that the Markdown extraction wasn't fitting their needs and wanted to return to a PPTX-to-PPTX approach but doing it at the raw XML level to prevent styling corruption that `python-pptx` might cause.

### Design Decisions
- **Hybrid XML Approach**: We use `python-pptx` initially *only* to generate an empty Speaker Notes slide for every slide (because manually wiring notes XML files and `_rels` is excessively complex and prone to corruption).
- **Direct XML Manipulation**: After the notes are generated, we unzip the `.pptx`, read `ppt/slides/slide*.xml`, and directly translate text within the `<a:t>` tags. This perfectly preserves parent `<a:rPr>` and `<a:pPr>` styling attributes.
- **Image Translation via Notes**: We run Tesseract on images in `ppt/media/` (mapped via slide `_rels`). We now inject both the original Korean text and the English translation into the speaker notes XML. This allows for side-by-side verification of Tesseract's accuracy vs translation accuracy.
- **Bulletproof Offline Loading**: We brought back `argostranslate` and re-implemented the 3-step offline loading, ensuring it scans multiple cache directories before attempting a network connection.

### Files Changed
- `xml_translate.py` (New file)
- `requirements.txt` (Added argostranslate back)
- `README.md` (Updated docs)

### Commit History (Session 6)

| Commit | Description |
|---|---|
| `ce943de` | docs: update README and dev_log for extraction pivot |
| `3fec477` | feat: add xml_translate.py for direct XML manipulation, update docs |

---

## Session 7 — 2026-08-14 (Conversation `Current`)

### Bug: Stanza Offline Patch Bypassed in xml_translate.py

**Error:**
`getaddrinfo failed` on `raw.githubusercontent.com` when running offline.

**Root cause:**
The offline patch for Stanza's `download_resources_json` was placed *after* the `import argostranslate.translate` statement. `argostranslate` implicitly imports `stanza.pipeline.core`, which binds the original unpatched `download_resources_json` function to its namespace (`from stanza.resources.common import download_resources_json`). Therefore, the patch was bypassed.

**Fix:**
Moved the Stanza offline patch to execute *before* `argostranslate` is imported. Added an explicit patch for `stanza.pipeline.core.download_resources_json` to guarantee all internal Stanza modules use the offline-safe version.

### Bug 2: Stanza Patch TypeError with `resources_url`

**Error:**
`TypeError: safe_download() got an unexpected keyword argument 'resources_url'`

**Root cause:**
Newer versions of `stanza` call `download_resources_json` with a `resources_url` keyword argument. The custom `safe_download` patch had a strict signature (`def safe_download(dir, filename='resources.json', url=None, proxies=None, resources_version=None)`) that did not accept this new kwargs, causing the patch itself to crash.

**Fix:**
Updated `safe_download` to use `*args, **kwargs` to dynamically accept any arguments and pass them cleanly to the original function. The fallback logic was updated to use `kwargs.get()` and positional argument index checks to locate the `dir` and `filename` needed for the cache fallback.

### Commit History (Session 7)

| Commit | Description |
|---|---|
| (Pending) | fix: fix import ordering bug bypassing Stanza offline patch in xml_translate.py |
| (Pending) | fix: update Stanza offline patch to accept arbitrary kwargs to prevent TypeError |

---

## Session 8 — 2026-08-14 (Conversation `Current`)

### Context
User requested to convert the `pptx-translate` tool into a standalone installable Python package named `translator`, and completely replace the `argostranslate` engine with the LLM models provided by the `agents` package (using local Ollama or the Office API).

### Design Decisions
- **Packaging**: Converted the directory to a standard Python package using `pyproject.toml`. The main entry point `translator` is exposed as a console script.
- **Removed Argos**: Stripped out all `argostranslate` logic, requirements, and the complex offline Stanza patching.
- **Integrated Agents LLM**: Created an `LLMTranslator` class that dynamically imports `get_llm()` from the `agents` module (`agents.llm.factory`).
- **Configuration**: Added `python-dotenv` and an `.env.example` file to allow configuring `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, etc.
- **CLI Options**: Added `--provider` argument to the CLI so users can switch between `ollama` and `office` on the fly.

### Files Changed
- `pyproject.toml` (New)
- `.env.example` (New)
- `translator/main.py` (Renamed from `xml_translate.py` and updated)
- `requirements.txt` (Removed `argostranslate`)

### Commit History (Session 8)

| Commit | Description |
|---|---|
| (Pending) | feat: convert pptx-translate to translator package and integrate agents LLM factory |

---

## Session 9 — 2026-08-14 (Conversation `Current`)

### Bug: Unexpected keyword argument 'temperature' for Client.chat()

**Error:**
```
[WARNING] LLM translation failed for text '...': Client.chat() got an unexpected keyword argument 'temperature'
```

**Root cause:**
When integrating the `agents` LLM factory in Session 8, the `get_llm()` call was passing `temperature=0.1`. The underlying LLM client wrapped by the `agents` module does not accept `temperature` as a valid keyword argument for its `chat()` method, causing the translation step to fail with a `TypeError`.

**Fix:**
Removed the unsupported `temperature=0.1` keyword argument from the `get_llm(provider=provider)` call inside `translator/main.py`. The backend LLM client now defaults to its internal parameter settings and execution succeeds.

### Commit History (Session 9)

| Commit | Description |
|---|---|
| (Pending) | fix: remove unsupported temperature kwarg from get_llm call in main.py |

---

## Session 10 — 2026-08-16 (Conversation `Current`)

### Context
User reported that `pytesseract` was still finicky/not working properly. We discussed switching to native PowerShell commands (using the `Windows.Media.Ocr` engine built into Windows 10/11) to perform the OCR tasks, eliminating the need to install Tesseract or download `.traineddata` files.

### Design Decisions
- **Native Windows OCR**: Decided to utilize the highly accurate `Windows.Media.Ocr.OcrEngine` which is native to Windows 10/11.
- **PowerShell Batching**: Spawning `powershell.exe` per image adds a ~0.5s overhead per call. To fix this, we wrote `ocr_batch.ps1` to take a whole directory of images, run OCR on all of them in a single PowerShell process, and write the output (including bounding box heights) to a single `ocr_results.json`.
- **Placeholder Pattern**: Instead of rewriting the main `pptx_handler.py` traversal logic, we inject a placeholder `[[OCR_PLACEHOLDER:filename]]` where the image text should go, run the batch OCR once, and then replace all placeholders.
- **Main.py Refactor**: Integrated the new `ImageHandler.process_batch()` directly into `main.py`. The `media/` folder extracted from the PPTX is perfectly suited for this. We run OCR across all media upfront, then inject the text and its LLM translation into the speaker notes XML as before.
- **Dependencies Cleaned**: Completely removed `pytesseract`, `Pillow`, and `pandas` from `requirements.txt`.

### Files Changed
- `translator/ocr_batch.ps1` (New script for batch processing)
- `translator/image_handler.py` (Rewritten to call PowerShell and parse JSON)
- `translator/pptx_handler.py` (Updated to use batch and placeholder injection)
- `translator/main.py` (Removed Tesseract, integrated `ImageHandler.process_batch`)
- `requirements.txt` (Removed heavy OCR dependencies)
- `README.md` (Updated docs to reflect Windows OCR)

### Commit History (Session 10)

| Commit | Description |
|---|---|
| `b72adb8` | feat: replace tesseract with batched native windows OCR via powershell |

---

## Session 11 — 2026-08-16 (Conversation `Current`)

### Context
Since the tool was previously converted to a proper Python package (installable via `pip install .`), maintaining a separate `requirements.txt` became redundant and led to out-of-sync dependencies after removing Tesseract. Furthermore, the newly added `.ps1` script wouldn't be included in the Python wheel without explicit configuration.

### Design Decisions
- **Delete `requirements.txt`**: Completely removed to enforce a single source of truth for dependencies.
- **Update `pyproject.toml` Dependencies**: Removed `pytesseract`, `Pillow`, and `pandas`.
- **Fix PowerShell Packaging**: Added `[tool.setuptools.package-data]` pointing to `*.ps1` so that `ocr_batch.ps1` gets bundled properly when the package is installed via `pip`.

### Files Changed
- `requirements.txt` (Deleted)
- `pyproject.toml` (Updated dependencies and package-data)

### Commit History (Session 11)

| Commit | Description |
|---|---|
| `5967fc1` | chore: remove requirements.txt and update pyproject.toml dependencies |

---

## Session 12 — 2026-08-16 (Conversation `Current`)

### Bug: PowerShell script missing from installed package

**Error:**
```
PowerShell OCR script failed: The argument '...\site-packages\translator\ocr_batch.ps1' to the -File parameter does not exist.
```

**Root cause:**
The `ocr_batch.ps1` file was not being included in the built wheel when running `pip install .`. The `[tool.setuptools.package-data]` configuration alone in `pyproject.toml` was insufficient because `setuptools` often requires `include-package-data = true` and sometimes a `MANIFEST.in` to reliably include non-Python data files during the build process.

**Fix:**
- Added a `MANIFEST.in` file containing `include translator/*.ps1`.
- Updated `pyproject.toml` to explicitly set `include-package-data = true` under the `[tool.setuptools]` table.

**Files Changed:**
- `MANIFEST.in` (New)
- `pyproject.toml` (Updated)

### Commit History (Session 12)

| Commit | Description |
|---|---|
| (Pending) | fix: add MANIFEST.in and include-package-data to fix missing ps1 in pip install |

---

## Session 13 — 2026-08-16 (Conversation `Current`)

### Bug: PowerPoint file corruption from Speaker Notes

**Error:**
After translation, opening the output `.pptx` file in PowerPoint triggers a "PowerPoint found a problem with content in the file. PowerPoint can attempt to repair the presentation." prompt. The repair process deletes the speaker notes entirely.

**Root cause:**
The original implementation of `append_to_notes_xml` combined all translated image text lines using `\n.join(slide_ocr_texts)` and inserted the resulting string into a single `<a:t>` (text) tag in the speaker notes XML.
The Office Open XML drawing text schema (`<a:t>`) strictly prohibits newline characters. When PowerPoint's XML parser encountered these newlines, it considered the XML malformed, leading to the corruption prompt and subsequent deletion of the notes.

**Fix:**
Updated `append_to_notes_xml` in `translator/main.py` to:
1. Accept a list of strings instead of a single string.
2. Iterate through the lines and generate a separate `<a:p>` (paragraph), `<a:r>` (run), and `<a:t>` element for each text line, which complies with the Open XML standard.
3. Added more robust targeting to ensure text is appended to the specific shape matching `<p:ph type="body"/>` instead of the first text body it finds.

**Files Changed:**
- `translator/main.py`

### Commit History (Session 13)

| Commit | Description |
|---|---|
| (Pending) | fix: fix PPTX corruption caused by injecting newline characters into speaker notes XML tags |

---

## Session 14 — 2026-08-16 (Conversation `Current`)

### Bug: PowerPoint file corruption from invalid XML control characters

**Error:**
After translation, opening the output `.pptx` file in PowerPoint still triggers a "PowerPoint found a problem with content in the file" prompt. The repair process deletes the speaker notes entirely, and potentially some slides.

**Root cause:**
The LLM output for translated text frequently included newlines (`\n`) and occasionally invisible control characters (e.g., `\x00`, `\x08`). In the OpenXML DrawingML schema, the `<a:t>` (text) node strictly does not support newline characters, carriage returns, or tabs. When PowerPoint's XML parser encounters a `\n` inside an `<a:t>` tag, it considers the schema violated, triggering a file corruption prompt and causing it to completely delete the affected slides/notes during its repair process.

**Fix:**
Implemented a `clean_text(text)` helper function in `translator/main.py` that:
1. Uses regex to strip all invalid XML 1.0 control characters.
2. Explicitly calls `.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')` to convert formatting characters into spaces before injecting them into the OpenXML `<a:t>` nodes.

**Files Changed:**
- `translator/main.py`

### Commit History (Session 14)

| Commit | Description |
|---|---|
| (Pending) | fix: strip invalid XML control characters from LLM translations to prevent PPTX corruption |

---

## Session 15 — 2026-08-16 (Conversation `Current`)

### Bug: PowerPoint file corruption from ElementTree Namespace Stripping

**Error:**
Despite fixing the newline and control characters in Session 14, PowerPoint continued to prompt for repair and delete slides.

**Root cause:**
Python's `xml.etree.ElementTree`, when parsing and writing XML, strips out XML namespace declarations (`xmlns:p14="..."`) if they are not explicitly used as tag prefixes in the document. PowerPoint OpenXML heavily relies on these namespaces being declared because they are referenced as *string values* inside attributes like `mc:Ignorable="p14"`. Because `ElementTree` didn't recognize `"p14"` as a namespace usage, it deleted the `xmlns:p14` declaration. When PowerPoint reads a file with `mc:Ignorable="p14"` but no `p14` namespace declared, it considers the file completely corrupted.

**Fix:**
Ripped out `xml.etree.ElementTree` entirely for reading/writing the final XML structures. Both `translate_xml_file` and `append_to_notes_xml` were rewritten to use safe, raw string manipulation (via regex `re.sub` and string slicing). This guarantees that no XML namespaces, original structure, or `mc:Ignorable` attributes are destroyed during the translation process.

**Files Changed:**
- `translator/main.py`

### Commit History (Session 15)

| Commit | Description |
|---|---|
| `9168ab8` | fix: replace ElementTree parsing with string regex to prevent destruction of unused namespaces and Office OpenXML schema violations |

---

## Session 16 — 2026-08-16 (Conversation `Current`)

### Overview
Live end-to-end testing of `ocr_batch.ps1` on Windows PowerShell 5.1 with real PPTX images. Required multiple rounds of debugging to work around PowerShell 5.1's inability to natively interact with WinRT async APIs.

---

### Bug 1: `GetAwaiter` not found on `System.__ComObject`

**Error:**
```
Method invocation failed because [System.__ComObject] does not contain a method named 'GetAwaiter'.
```

**Root cause:**
`.GetAwaiter()` is an extension method from `System.Runtime.WindowsRuntime.dll`. Without this assembly loaded (or with the COM wrapper not recognizing it), PowerShell 5.1 wraps WinRT objects in `System.__ComObject` which has no such method.

**Fix attempted:** Load `System.Runtime.WindowsRuntime` via `Add-Type -AssemblyName` — but the STA thread deadlocked during WinRT completion callbacks.

---

### Bug 2: Infinite hang after `Processing: image1.png`

**Root cause:**
PowerShell 5.1 runs in a Single-Threaded Apartment (STA). The WinRT async completion callback needs to be marshalled back to the main thread. Our polling loop blocked the main thread with `Thread.Sleep`, preventing the callback from ever firing → deadlock.

**Fix attempted:** Move polling to `Task.Run(...)` and use `.GetAwaiter().GetResult()` on the task to pump STA messages. But then C# `Add-Type` compilation failed.

---

### Bug 3: `Add-Type` compilation error — `IAsyncInfo` / `AsyncStatus` not found

**Error:**
```
The type or namespace name 'IAsyncInfo' could not be found
The name 'AsyncStatus' does not exist in the current context
```

**Root cause:**
The `Add-Type` C# compiler cannot find `Windows.Foundation` types because the Windows SDK `.winmd` files are not on the compiler's reference path by default.

**Fix attempted:** Define `IAsyncInfo` as a `[ComImport]` interface inline to avoid the SDK dependency — but then `GetResults()` failed.

---

### Bug 4: `GetResults` not found on `System.__ComObject`

**Error:**
```
Method invocation failed because [System.__ComObject] does not contain a method named 'GetResults'.
```

**Root cause:**
Even after waiting correctly, PowerShell's COM wrapper does not expose the generic `GetResults()` method on the underlying WinRT object.

**Fix:** Switch entirely to the official .NET bridging approach: use **reflection** to find `System.WindowsRuntimeSystemExtensions.AsTask<T>()` from `System.Runtime.WindowsRuntime.dll`. This converts WinRT `IAsyncOperation<T>` into a standard .NET `Task<T>`, which can be awaited normally.

---

### Bug 5: `MakeGenericMethod` receives a string instead of a `Type`

**Error:**
```
Cannot convert argument "methodInstantiation", with value: "[Windows.Storage.StorageFile]",
for "MakeGenericMethod" to type "System.Type"
```

**Root cause:**
In PowerShell 5.1, when a `[TypeName]` expression is passed as a function argument **without parentheses**, PowerShell evaluates it as a plain `string` literal rather than a .NET `Type` object. Wrapping in `()` partially helped but was unreliable through function parameter binding.

**Final Fix (v8 — working):**
Completely removed the generic `Await-WinRt` function that accepted `$ResultType` as a parameter. Instead, **pre-build all 5 strongly-typed `AsTask` methods upfront** using direct type literals in `()` at the top of the script, before any loop. Call them directly — no Type ever passes through a function parameter:

```powershell
$awaitStorageFile = $asTaskGeneric.MakeGenericMethod([Windows.Storage.StorageFile])
$awaitStream      = $asTaskGeneric.MakeGenericMethod([Windows.Storage.Streams.IRandomAccessStream])
$awaitDecoder     = $asTaskGeneric.MakeGenericMethod([Windows.Graphics.Imaging.BitmapDecoder])
$awaitBitmap      = $asTaskGeneric.MakeGenericMethod([Windows.Graphics.Imaging.SoftwareBitmap])
$awaitOcrResult   = $asTaskGeneric.MakeGenericMethod([Windows.Media.Ocr.OcrResult])

# Usage in loop:
$file = $awaitStorageFile.Invoke($null, @($op1)).GetAwaiter().GetResult()
```

Also added `$SCRIPT_VERSION` printed at the start of the log so it is easy to confirm which version is running.

---

### `--min-text-height` parameter confirmed working

The `--min-text-height` flag is fully wired end-to-end:
- `main.py` argparse: `--min-text-height` (default: `18`)
- `ImageHandler.__init__`: accepts `min_text_height`
- `image_handler.py` line 106: drops any OCR line with `height < min_text_height`

Usage:
```bash
translator -i input.pptx -o output.pptx --min-text-height 18
```

---

### Files Changed in Session 16
- `translator/ocr_batch.ps1` — complete rewrite of WinRT async handling

### Commit History (Session 16)

| Commit | Description |
|---|---|
| `e9a215c` | feat: add comprehensive OCR filtering logs for debugging |
| `0bbc050` | fix: restore GetAwaiter() and Add-Type for WinRT async |
| `e3c1888` | fix: use IAsyncInfo casting to support PowerShell 5.1 WinRT async |
| `2b1035c` | fix: use IAsyncInfo casting to support PowerShell 5.1 WinRT async |
| `d8bbd5b` | fix: use C# helper to correctly cast IAsyncInfo and prevent infinite loop |
| `0a0007f` | fix: prevent STA deadlock during WinRT async wait |
| `7b280ed` | fix: use ComImport for IAsyncInfo to avoid WinMD compilation errors |
| `2112c63` | fix: complete rewrite of WinRT wait using pure PowerShell Reflection of AsTask |
| `6262338` | fix: cast ResultType from string to type to fix MakeGenericMethod error |
| `f25545e` | fix: wrap type args in () so PowerShell evaluates them as Type objects |
| `8c8356a` | fix(v8): pre-build typed AsTask methods upfront — final working solution |

---

## Session 17 — 2026-08-16 (Conversation `Current`)

### Bug: PowerPoint repair prompt on every output file

**User report:** Opening the translated `.pptx` triggers PowerPoint's "repair" prompt on every run. Content is removed after repair.

**Root cause analysis — two independent bugs found:**

#### Bug 1: `append_to_notes_xml` injected text into the wrong `</p:txBody>`

The old implementation searched for `<p:ph type="body"` to locate the body text shape, then called `content.find('</p:txBody>', body_ph_idx)`. However, a notes slide XML has **two shapes** — a title shape and a body shape. The title shape's `<p:txBody>` **always comes first** in the XML. Because the body placeholder `<p:ph type="body"` is declared inside the body shape's `<p:sp>`, but `content.find('</p:txBody>', body_ph_idx)` searched *from the placeholder's character position*, which is **inside** the body `<p:sp>` but *after* the title's `</p:txBody>` — this accidentally targeted the correct one in some layouts, but failed on others where the body `<p:sp>` came first in the XML.

The real failure mode: if the `<p:ph type="body"` attribute used double-quotes vs single-quotes, or had attributes in different order (e.g. `<p:ph idx="1" type="body"/>`), the `content.find` missed entirely and fell back to `search_from = 0`, injecting paragraphs after the **title shape's** `</p:txBody>` — producing XML like `</p:txBody><a:p>...` at the wrong nesting level, which is a schema violation.

**Fix:** Switched to a regex search `re.search(r'<p:ph\s[^>]*type=["\']body["\']', content)` that handles any attribute ordering. Then searches for `>` from the match start to find the end of the placeholder tag, and uses that as `search_from` for `</p:txBody>`. This guarantees we always find the `</p:txBody>` of the **same** `<p:sp>` that contains the body placeholder.

#### Bug 2: ZIP arcnames used backslashes on Windows

`Path.relative_to(extract_dir)` on Windows returns backslash-separated paths (e.g. `ppt\slides\slide1.xml`). The ZIP specification requires **forward slashes** as path separators. When PowerPoint opens a ZIP with backslash paths, it cannot resolve part relationships → triggers the repair prompt and deletes slides/notes.

**Fix:** Changed `arcname = file_path.relative_to(extract_dir)` → `arcname = file_path.relative_to(extract_dir).as_posix()` to always produce forward-slash paths regardless of OS.

#### Bonus: Pre-zip XML validation

Added a validation pass before zipping that runs `ElementTree.parse()` on every `.xml` file in the extracted directory. Any malformed XML is logged as `[XML INVALID] <path> — <error>` so corruption is surfaced immediately rather than discovered only after opening the file in PowerPoint.

**Files changed:**
- `translator/main.py` — fixed `append_to_notes_xml` regex targeting; fixed zip `arcname` to use `.as_posix()`; added pre-zip XML validation loop

### Commit History (Session 17)

| Commit | Description |
|---|---|
| `a2f9e50` | fix: correct notes XML body targeting with regex; fix zip arcnames to use forward slashes |

---

## Session 18 — 2026-08-16 (Conversation `Current`)

### Bug: PowerPoint repair prompt still appears after Session 17 fixes

**User report:** Still getting the repair/corruption prompt even after the regex and arcname fixes. No `[XML INVALID]` lines in log.

**Root cause:** The real culprit was **Step 1 — `python-pptx` saving the presentation**.

`python-pptx` when saving silently **drops any OOXML part it does not understand** (charts, custom XML, SmartArt, ink shapes, video, external data connections, etc.) and also removes their `[Content_Types].xml` entries. This means the output PPTX is structurally incomplete compared to the original. When PowerPoint opens it, the missing parts trigger the repair prompt and those parts are permanently removed.

The prior Session 15 fix (replacing `ElementTree` write-back with regex) solved namespace stripping by *our code* but the damage from `python-pptx.save()` was happening *before* our code even ran — on the `temp_init_pptx` intermediate file.

No `[XML INVALID]` lines appeared because `ElementTree.parse()` only validates XML well-formedness. A file can be perfectly well-formed XML but still missing required OOXML parts, which is what PowerPoint detects.

**Fix: Eliminate `python-pptx` from the save path entirely.**

Replaced the 3-step process (python-pptx load → save → unzip) with:
1. **Unzip the ORIGINAL PPTX directly** — zero transformation, all parts preserved.
2. **`ensure_notes_slides(extract_dir)`** — pure string-template function that:
   - Scans slide `.rels` files to find slides already having notes
   - For slides without notes: writes a minimal `notesSlide{N}.xml` from `_NOTES_XML_TEMPLATE`
   - Creates the corresponding `notesSlides/_rels/notesSlide{N}.xml.rels` using `_NOTES_RELS_TEMPLATE`
   - Inserts a `<Relationship>` entry into the slide's `.rels` file using raw string replacement
   - Adds `<Override>` entry to `[Content_Types].xml` using raw string replacement
   - **Never uses `ET.write()` or python-pptx for writing** — all file writes are raw strings

**Also removed `python-pptx` from `pyproject.toml` dependencies** (no longer needed at all). Bumped version to `0.1.3`.

**Files changed:**
- `translator/main.py` — removed `from pptx import Presentation`; added `_NOTES_XML_TEMPLATE`, `_NOTES_RELS_TEMPLATE`, `_parse_rels()`, `_next_free_rid()`, `ensure_notes_slides()`; rewrote `process_presentation` Step 1–2
- `pyproject.toml` — removed `python-pptx` dependency, bumped to `0.1.3`

### Commit History (Session 18)

| Commit | Description |
|---|---|
| `40c9e82` | fix: eliminate python-pptx save — unzip original directly and create notes via string templates |

---

## Session 19 — 2026-08-18 (Conversation `Current`)

### Bug: XML mismatched tag corruption and aggressive OCR filtering

**User report:** 
1. `[XML INVALID] ppt/slides/slide1.xml — mismatched tag: line 2, column 9442`
2. Valid short Korean OCR lines like `텸C쳄작죌` were dropped due to "Not enough Korean characters".

**Root cause analysis & Fixes:**

#### Bug 1: `translate_xml_file` regex matching parent tags
The regex `r'(<a:t[^>]*>)(.*?)(</a:t>)'` was matching tags like `<a:txBody>` and `<a:tc>` instead of just `<a:t>`. When matching the parent tag, it consumed the entire internal XML structure and replaced it with just the translated text, leading to unclosed child tags and causing the mismatched tag error upon parsing.
**Fix:** Tightened the regex to strictly match `<a:t>` or `<a:t\s[^>/]*>` to prevent it from matching parent tags or self-closing tags.

#### Bug 2: `_MIN_HANGUL_CHARS` too high for line-by-line OCR
When switching from `pytesseract` to Native Windows OCR in an earlier session, the tool changed from extracting paragraph-blocks to line-by-line output. However, the thresholds `_MIN_HANGUL_CHARS = 5` and `_MIN_SOURCE_LEN = 6` were kept intact. Legitimate short Korean lines (like `시작` or `확인` on buttons) were now being aggressively dropped because they had fewer than 5 Hangul characters per line.
**Fix:** Lowered `_MIN_HANGUL_CHARS` and `_MIN_SOURCE_LEN` to `1`. The 40% `_MIN_KOREAN_RATIO` check handles dropping noisy strings effectively.

**Files changed:**
- `translator/main.py` — updated regex in `translate_xml_file` to strictly target `<a:t>` tags.
- `translator/image_handler.py` — lowered `_MIN_HANGUL_CHARS` and `_MIN_SOURCE_LEN` thresholds.

### Commit History (Session 19)

| Commit | Description |
|---|---|
| `HEAD` | fix: resolve XML mismatched tag corruption and relax OCR character limits |
