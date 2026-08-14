"""
translator/image_handler.py

Two operating modes
-------------------
1. extract_text_for_notes(image_bytes, min_height) [DEFAULT]
   OCR the image, filter to only "considerable" text (rendered height >=
   min_height pixels), translate each block, and return a list of
   translated strings.  The image is NEVER modified.  The caller appends
   the translated strings to the slide's speaker notes.

2. process(image_bytes) [LEGACY — kept but not used by default]
   Full in-place redraw pipeline: OCR → translate → paint over Korean →
   draw English back onto the image.  Returns modified image bytes.
   (Disabled by default because blob replacement is fragile across
   python-pptx versions.)

OCR uses --psm 11 (sparse text) which is best for flowchart diagrams
where text is scattered in boxes and arrows, not continuous paragraphs.
"""

import io
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Korean text quality filters
# ---------------------------------------------------------------------------

# Hangul Unicode ranges:
#   AC00–D7A3  Hangul Syllables (가–힣)  — the vast majority of Korean text
#   1100–11FF  Hangul Jamo (individual consonants/vowels)
#   3130–318F  Hangul Compatibility Jamo
_HANGUL_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")

# Minimum fraction of characters that must be Hangul for a block to be translated
_MIN_KOREAN_RATIO = 0.40   # raised from 0.25 — filters mixed symbol/number junk

# Minimum number of Hangul characters required
_MIN_HANGUL_CHARS = 5      # raised from 3 — filters single-syllable noise

# Minimum total characters in the cleaned source text before attempting translation
_MIN_SOURCE_LEN = 6        # at least 6 chars (≈ 2 Korean words)

# Minimum words in a translated result — 1-word translations are almost always
# noise (isolated syllable → wrong English word mapping by offline model)
_MIN_TRANSLATED_WORDS = 2


def _korean_ratio(text: str) -> float:
    """Return the fraction of characters in *text* that are Hangul."""
    if not text:
        return 0.0
    hangul = len(_HANGUL_RE.findall(text))
    return hangul / len(text)


def _is_korean_text(text: str) -> bool:
    """
    Return True if *text* is worth translating:
      - Contains at least _MIN_HANGUL_CHARS Hangul characters, AND
      - At least _MIN_KOREAN_RATIO of all characters are Hangul.

    This filters out:
      - Pure English/number fragments produced by OCR noise
      - Single Korean syllable detections (meaningless in isolation)
      - Mixed symbol/number strings that confuse argostranslate
    """
    hangul_count = len(_HANGUL_RE.findall(text))
    if hangul_count < _MIN_HANGUL_CHARS:
        return False
    return _korean_ratio(text) >= _MIN_KOREAN_RATIO


def _clean_ocr_text(text: str) -> str:
    """
    Light cleanup of OCR output before translation:
      - Collapse runs of whitespace / newlines
      - Strip leading/trailing punctuation and stray ASCII symbols
        that Tesseract often inserts around Korean characters
      - Remove lines that are purely numbers, punctuation, or ASCII
        (keep lines that have at least one Hangul character)
    """
    lines = text.splitlines()
    kept = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Keep the line only if it has at least one Hangul character
        if _HANGUL_RE.search(line):
            # Strip leading/trailing non-alphanumeric, non-Korean chars
            line = re.sub(r"^[^\w\uAC00-\uD7A3]+|[^\w\uAC00-\uD7A3]+$", "", line)
            if line:
                kept.append(line)
    return " ".join(kept).strip()

# ---------------------------------------------------------------------------
# Font resolution — tries Windows system fonts first, then Linux fallbacks
# ---------------------------------------------------------------------------
_FONT_PATHS = [
    r"C:\Windows\Fonts\segoeui.ttf",           # Segoe UI — clean, modern, Windows default
    r"C:\Windows\Fonts\calibri.ttf",           # Calibri
    r"C:\Windows\Fonts\arial.ttf",             # Arial
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def _resolve_font_path() -> Optional[str]:
    for p in _FONT_PATHS:
        if Path(p).exists():
            return p
    return None


_RESOLVED_FONT: Optional[str] = _resolve_font_path()


def _get_font(size: int):
    """Return a PIL ImageFont at the requested size."""
    from PIL import ImageFont

    if _RESOLVED_FONT:
        try:
            return ImageFont.truetype(_RESOLVED_FONT, max(size, 6))
        except Exception:
            pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Colour utilities
# ---------------------------------------------------------------------------

def _sample_bg_color(img, left: int, top: int, right: int, bottom: int) -> tuple:
    """
    Sample background colour from a 4-pixel border around the bounding box.
    Falls back to white if the region is empty or out of bounds.
    """
    from PIL import Image

    pad = 5
    x0 = max(0, left - pad)
    y0 = max(0, top - pad)
    x1 = min(img.width, right + pad)
    y1 = min(img.height, bottom + pad)

    if x0 >= x1 or y0 >= y1:
        return (255, 255, 255)

    region = img.crop((x0, y0, x1, y1)).convert("RGB")

    # Exclude the inner text region pixels so we only sample the border
    inner_x0 = left - x0
    inner_y0 = top - y0
    inner_x1 = right - x0
    inner_y1 = bottom - y0

    pixels = []
    w, h = region.size
    for py in range(h):
        for px in range(w):
            if not (inner_x0 <= px <= inner_x1 and inner_y0 <= py <= inner_y1):
                pixels.append(region.getpixel((px, py)))

    if not pixels:
        return (255, 255, 255)

    counter = Counter(pixels)
    return counter.most_common(1)[0][0]


def _fg_color(bg: tuple) -> tuple:
    """Return black or white based on background luminance (WCAG formula)."""
    r, g, b = bg
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if luminance > 128 else (255, 255, 255)


# ---------------------------------------------------------------------------
# Text drawing helpers
# ---------------------------------------------------------------------------

def _auto_fit_font(draw, text: str, max_w: int, max_h: int):
    """Find the largest font size where *text* fits in (max_w × max_h)."""
    for size in range(max(max_h, 8), 5, -1):
        font = _get_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w and (bbox[3] - bbox[1]) <= max_h:
            return font
    return _get_font(6)


def _wrap_text(draw, text: str, max_w: int, font) -> list[str]:
    """Word-wrap *text* into lines that fit within *max_w* pixels."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_w:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))
    return lines or [text]


def _draw_block(draw, text: str, x: int, y: int, w: int, h: int, fg: tuple) -> None:
    """Fit-and-draw translated text inside the given bounding box."""
    font = _auto_fit_font(draw, text, w, h)
    lines = _wrap_text(draw, text, w, font)

    # Approximate line height from font metrics
    sample_bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_h = (sample_bbox[3] - sample_bbox[1]) + 2

    for i, line in enumerate(lines):
        ly = y + i * line_h
        if ly + line_h > y + h:
            break  # no more vertical space
        draw.text((x, ly), line, fill=fg, font=font)


# ---------------------------------------------------------------------------
# Main image processing class
# ---------------------------------------------------------------------------

class ImageHandler:
    """
    OCR a single image, translate detected Korean text blocks.
    Supports two modes — see module docstring.
    """

    OCR_CONFIG = "--psm 11 --oem 3"   # sparse text mode — best for diagrams

    def __init__(self, engine, confidence: int = 60, ocr_lang: str = "kor") -> None:
        self.engine = engine
        self.confidence = confidence
        self.ocr_lang = ocr_lang

    # ------------------------------------------------------------------
    # Mode 1 — extract text for speaker notes (no image modification)
    # ------------------------------------------------------------------

    def extract_text_for_notes(
        self,
        image_bytes: bytes,
        min_height: int = 18,
    ) -> list[str]:
        """
        OCR *image_bytes*, apply quality filters, translate genuine Korean
        text blocks, and return a list of translated strings.

        Filters applied (in order):
          1. Block pixel height >= min_height         (skips tiny labels)
          2. Block contains >= 5 Hangul characters    (skips OCR noise/English)
          3. >= 40% of characters are Hangul          (skips mixed junk)
          4. Cleaned source text >= 6 characters      (skips micro-fragments)
          5. OCR noise stripped (_clean_ocr_text)
          6. Source dedup — same Korean not translated twice
          7. Translation >= 2 words                   (kills 1-word garbage)
          8. Translation dedup — same English not repeated

        The image is never modified.  Returns [] if nothing passes filters.
        """
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        scale = self._compute_scale(img)
        if scale > 1:
            img = img.resize(
                (img.width * scale, img.height * scale), Image.LANCZOS
            )

        df = self._ocr_dataframe(img)
        if df is None or df.empty:
            return []

        results: list[str] = []
        seen_raw: set[str] = set()          # dedup on cleaned Korean source
        seen_translated: set[str] = set()   # dedup on translated output

        for (block_num,), block_df in df.groupby(["block_num"]):
            for (par_num,), par_df in block_df.groupby(["par_num"]):
                block_text, block_h = self._paragraph_text_and_height(par_df)
                if not block_text:
                    continue

                # Filter 1 — size
                if block_h < min_height:
                    log.debug(f"    [skip-size h={block_h}px] {block_text[:30]!r}")
                    continue

                # Filter 2 & 3 — Korean content
                if not _is_korean_text(block_text):
                    log.debug(f"    [skip-lang] {block_text[:40]!r}")
                    continue

                # Filter 4 & 5 — clean + min length
                cleaned = _clean_ocr_text(block_text)
                if not cleaned or len(cleaned) < _MIN_SOURCE_LEN or not _is_korean_text(cleaned):
                    log.debug(f"    [skip-clean/len] {block_text[:40]!r}")
                    continue

                # Filter 6 — source dedup
                if cleaned in seen_raw:
                    log.debug(f"    [skip-src-dup] {cleaned[:40]!r}")
                    continue
                seen_raw.add(cleaned)

                translated = self.engine.translate(cleaned)
                if not translated or translated.strip() == cleaned.strip():
                    continue

                translated = translated.strip()

                # Filter 7 — min 2 words in translation (1-word = noise)
                if len(translated.split()) < _MIN_TRANSLATED_WORDS:
                    log.debug(f"    [skip-short-translation] {translated!r} ← {cleaned[:30]!r}")
                    continue

                # Filter 8 — translation dedup
                t_lower = translated.lower()
                if t_lower in seen_translated:
                    log.debug(f"    [skip-trans-dup] {translated!r}")
                    continue
                seen_translated.add(t_lower)

                log.debug(f"    [{cleaned[:40]!r}] → [{translated[:40]!r}]")
                results.append(translated)

        return results

    # ------------------------------------------------------------------
    # Mode 2 — OCR + in-place image redraw (legacy, not default)
    # ------------------------------------------------------------------

    def process(self, image_bytes: bytes, content_type: str = "image/png") -> Optional[bytes]:
        """
        Translate Korean text in *image_bytes* by painting over the original
        and redrawing English text.

        Returns modified image bytes (same format as input), or None if
        no translatable text was found.
        """
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        orig_size = img.size

        scale = self._compute_scale(img)
        if scale > 1:
            img = img.resize(
                (img.width * scale, img.height * scale), Image.LANCZOS
            )
            log.debug(f"    Upscaled image {orig_size} → {img.size} (×{scale})")

        df = self._ocr_dataframe(img)
        if df is None or df.empty:
            return None

        modified = self._redraw(img, df)
        if not modified:
            return None

        if scale > 1:
            img = img.resize(orig_size, Image.LANCZOS)

        save_fmt = self._fmt(content_type)
        buf = io.BytesIO()
        if save_fmt == "JPEG":
            img.save(buf, format="JPEG", quality=92)
        else:
            img.save(buf, format="PNG")
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Shared internal helpers
    # ------------------------------------------------------------------

    def _ocr_dataframe(self, img):
        """Run Tesseract on *img* and return a confidence-filtered DataFrame, or None on error."""
        import pytesseract

        try:
            df = pytesseract.image_to_data(
                img,
                lang=self.ocr_lang,
                config=self.OCR_CONFIG,
                output_type=pytesseract.Output.DATAFRAME,
            )
        except Exception as exc:
            err = str(exc)
            if "tessdata" in err and self.ocr_lang in err:
                log.warning(
                    f"    Tesseract OCR skipped — missing language data for '{self.ocr_lang}'.\n"
                    f"    Fix: Download kor.traineddata from:\n"
                    f"      https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata\n"
                    f"    Save it to your Tesseract tessdata/ folder and retry."
                )
            else:
                log.warning(f"    Tesseract OCR error: {exc}")
            return None

        df = df[df["conf"] >= self.confidence].copy()
        df = df[df["text"].notna()]
        df["text"] = df["text"].astype(str).str.strip()
        df = df[df["text"] != ""]
        return df

    @staticmethod
    def _paragraph_text_and_height(par_df) -> tuple[str, int]:
        """Return (joined paragraph text, max line height in pixels)."""
        lines = []
        max_h = 0
        for (line_num,), line_df in par_df.groupby(["line_num"]):
            words = line_df[line_df["text"].str.strip() != ""]
            if words.empty:
                continue
            line_text = " ".join(words["text"].tolist()).strip()
            if not line_text:
                continue
            h = int(words["height"].max())
            max_h = max(max_h, h)
            lines.append(line_text)
        return " ".join(lines).strip(), max_h

    @staticmethod
    def _compute_scale(img) -> int:
        shortest = min(img.width, img.height)
        if shortest >= 1200:
            return 1
        if shortest >= 600:
            return 2
        return 3

    @staticmethod
    def _fmt(content_type: str) -> str:
        ct = content_type.lower()
        if "jpeg" in ct or "jpg" in ct:
            return "JPEG"
        return "PNG"

    def _redraw(self, img, df) -> bool:
        """
        Iterate over Tesseract blocks, translate each, redraw in place.
        Returns True if at least one block was modified.
        """
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        modified = False

        for (block_num,), block_df in df.groupby(["block_num"]):
            for (par_num,), par_df in block_df.groupby(["par_num"]):
                changed = self._process_paragraph(draw, img, par_df)
                if changed:
                    modified = True

        return modified

    def _process_paragraph(self, draw, img, par_df) -> bool:
        """
        Collect all lines in a paragraph, translate as a unit, redraw.
        Returns True if the paragraph was modified.
        """
        line_data: list[dict] = []
        for (line_num,), line_df in par_df.groupby(["line_num"]):
            words = line_df[line_df["text"].str.strip() != ""]
            if words.empty:
                continue
            line_text = " ".join(words["text"].tolist()).strip()
            if not line_text:
                continue
            left = int(words["left"].min())
            top = int(words["top"].min())
            right = int((words["left"] + words["width"]).max())
            bottom = int((words["top"] + words["height"]).max())
            line_data.append({
                "text": line_text,
                "left": left, "top": top, "right": right, "bottom": bottom,
            })

        if not line_data:
            return False

        src_text = "\n".join(d["text"] for d in line_data)
        translated = self.engine.translate(src_text)

        if translated.strip() == src_text.strip():
            return False

        log.debug(f"    [{src_text[:40].replace(chr(10), ' ')}]")
        log.debug(f"    → [{translated[:40].replace(chr(10), ' ')}]")

        all_left = min(d["left"] for d in line_data)
        all_top = min(d["top"] for d in line_data)
        all_right = max(d["right"] for d in line_data)
        all_bottom = max(d["bottom"] for d in line_data)
        block_w = all_right - all_left
        block_h = all_bottom - all_top

        if block_w <= 0 or block_h <= 0:
            return False

        bg = _sample_bg_color(img, all_left, all_top, all_right, all_bottom)
        fg = _fg_color(bg)

        draw.rectangle([all_left, all_top, all_right, all_bottom], fill=bg)
        flat_text = " ".join(translated.split())
        _draw_block(draw, flat_text, all_left, all_top, block_w, block_h, fg)

        return True
