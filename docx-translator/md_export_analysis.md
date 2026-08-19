# PPTX → Markdown Export — Solution Analysis

> Date: 2026-08-18  
> Context: After translating Korean PPTX files to English, we want to export the translated content (including speaker notes with OCR translations) to a clean Markdown file.

---

## Goal

Take a **translated** `.pptx` file and produce a structured Markdown document that includes:
- Slide text with formatting (headings, bold, italic, lists)
- Tables
- Speaker notes (where our OCR image translations live)
- Images extracted and linked via `![](path)` syntax
- Clear slide-by-slide structure

---

## Option 1: `pptx2md` (Dedicated Python Package)

**Repository:** https://github.com/ssine/pptx2md  
**Install:** `pip install pptx2md`  
**Usage:** `pptx2md presentation.pptx`

| Pros | Cons |
|---|---|
| Purpose-built for PPTX → Markdown | Uses `python-pptx` internally (read-only, so no corruption risk) |
| Handles **bold**, *italic*, lists, tables, images | **Speaker notes support is uncertain** — may not extract them |
| Extracts images to `/img/` folder with relative links | Won't include our translated OCR text from notes |
| Mature, well-maintained | |
| Supports nested lists, merged table cells | |
| Custom heading hierarchy via title file | |

### Verdict
Good for basic slide text extraction, but **speaker notes are critical** for our use case (OCR translations live there). Would need verification or custom extension.

---

## Option 2: `markitdown` (Microsoft)

**Repository:** https://github.com/microsoft/markitdown  
**Install:** `pip install markitdown`  
**Usage:** `markitdown translated.pptx > output.md`

| Pros | Cons |
|---|---|
| Microsoft-built, actively maintained | More generic — less PPTX-specific formatting control |
| **Includes speaker notes** in output | Heavier dependency footprint |
| Multi-format support (PDF, Word, Excel, PPTX) | May be overkill for our needs |
| AI/LLM integration built-in for image captioning | |
| No MS Office installation required | |
| Runs entirely offline for core conversion | |

### Verdict
**Best fit** for our use case — speaker notes extraction is supported, which is essential since our OCR translations are stored there. Can be wrapped with minimal code for custom formatting.

---

## Option 3: Custom XML → Markdown (Build from Scratch)

**Approach:** Unzip PPTX, parse slide XML directly (same architecture as our translator), map XML elements to Markdown syntax.

| XML Element | Markdown |
|---|---|
| `<a:t>` inside title shape | `## Slide N: Title Text` |
| `<a:t>` with `<a:rPr b="1">` | `**bold text**` |
| `<a:t>` with `<a:rPr i="1">` | `*italic text*` |
| `<a:buChar>` / `<a:buAutoNum>` | `- item` / `1. item` |
| `<a:tbl>` | Markdown table `| col | col |` |
| `<p:ph type="body">` in notesSlide | `### Speaker Notes\n text` |
| Images in `ppt/media/` | Extract to folder, `![](path)` |

| Pros | Cons |
|---|---|
| Full control over output format | More code to write and maintain |
| Consistent with existing unzip+regex architecture | Need to handle many XML edge cases |
| No new dependencies | Tables and nested lists are complex |
| Can customize speaker notes formatting exactly | |

### Verdict
Maximum flexibility, but significant implementation effort. Best as a **fallback** if existing packages don't meet our needs.

---

## Option 4: Pandoc (System Tool)

**Install:** System package (`choco install pandoc` on Windows)  
**Usage:** `pandoc -f pptx -t markdown presentation.pptx -o output.md`

| Pros | Cons |
|---|---|
| Industry-standard document converter | External system dependency (not pip-installable) |
| Excellent formatting preservation | Speaker notes extraction depends on version |
| Handles complex tables well | Adds complexity to packaging/distribution |
| Supports many output formats | |

### Verdict
Powerful but adds a system-level dependency. Not ideal for a self-contained Python package.

---

## Recommendation

### Primary: `markitdown` (Microsoft)

1. **Speaker notes** — extracts them, which is critical for our OCR translations
2. **Read-only** — no corruption risk (we only read the translated PPTX)
3. **Minimal integration** — can be called as a library or CLI
4. **Single dependency** — `pip install markitdown`
5. **Microsoft-maintained** — good long-term support for OOXML format

### Fallback: Custom XML parser

If `markitdown` output isn't rich enough (e.g., missing image extraction or poor formatting), we layer our own XML parser for specific elements on top.

### Implementation Plan

1. Add `markitdown` to `pyproject.toml` dependencies
2. Add `--export-md` CLI flag to `translator`
3. After translation completes, run `markitdown` on the output PPTX
4. Post-process the Markdown:
   - Add slide numbers if missing
   - Extract images to a sidecar folder
   - Format speaker notes section clearly
5. Write `{output_stem}.md` alongside the `.pptx`

---

## Decision

**Pending user confirmation.** Leaning toward `markitdown` as primary engine.
