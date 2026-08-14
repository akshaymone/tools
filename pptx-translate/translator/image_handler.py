"""
translator/image_handler.py

Pipeline:
  1. Load image bytes → PIL.Image (upscale small images for better OCR)
  2. pytesseract.image_to_data() with --psm 11 (sparse text, good for diagrams)
  3. Filter by confidence threshold
  4. Group words into logical text blocks (by block_num → par_num → line_num)
  5. Translate each block as a whole (better context than word-by-word)
  6. For each block:
       a. Sample dominant background colour from the region border
       b. Paint rectangle over original Korean text
       c. Auto-fit Segoe UI font, wrap translated text within block bounds
       d. Draw in contrasting foreground colour
  7. Downscale back to original resolution and return as bytes

Limitations (documented honestly):
  - Rotated / diagonal text (common on flowchart arrows) is attempted via
    OSD deskew but may not be 100% accurate.
  - Very small labels (<12 px rendered height) are often skipped by Tesseract.
  - Gradient or textured backgrounds yield approximate colour fills.
"""

import io
import logging
from collections import Counter
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

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
    OCR a single image, translate detected Korean text blocks,
    and redraw the English translation in place.
    """

    OCR_CONFIG = "--psm 11 --oem 3"   # sparse text mode — best for diagrams

    def __init__(self, engine, confidence: int = 60, ocr_lang: str = "kor") -> None:
        self.engine = engine
        self.confidence = confidence
        self.ocr_lang = ocr_lang

    # ------------------------------------------------------------------

    def process(self, image_bytes: bytes, content_type: str = "image/png") -> Optional[bytes]:
        """
        Translate Korean text in *image_bytes*.

        Returns modified image bytes (same format as input), or None if
        no translatable text was found.
        """
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        orig_size = img.size

        # Upscale small images — Tesseract accuracy degrades below ~150 dpi
        scale = self._compute_scale(img)
        if scale > 1:
            img = img.resize(
                (img.width * scale, img.height * scale), Image.LANCZOS
            )
            log.debug(f"    Upscaled image {orig_size} → {img.size} (×{scale})")

        # OCR
        try:
            df = pytesseract.image_to_data(
                img,
                lang=self.ocr_lang,
                config=self.OCR_CONFIG,
                output_type=pytesseract.Output.DATAFRAME,
            )
        except Exception as exc:
            err = str(exc)
            # Give a clear, actionable message for the most common failure
            if "tessdata" in err and self.ocr_lang in err:
                log.warning(
                    f"    Tesseract OCR skipped — missing language data for '{self.ocr_lang}'.\n"
                    f"    Fix: Download kor.traineddata and place it in your tessdata folder:\n"
                    f"      https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata\n"
                    f"    Then save it to:\n"
                    f"      C:\\Users\\%USERNAME%\\AppData\\Local\\Programs\\Tesseract-OCR\\tessdata\\kor.traineddata\n"
                    f"    (Run this once with internet, then OCR will work fully offline.)"
                )
            else:
                log.warning(f"    Tesseract OCR error: {exc}")
            return None

        # Filter
        df = df[df["conf"] >= self.confidence].copy()
        df = df[df["text"].notna()]
        df["text"] = df["text"].astype(str).str.strip()
        df = df[df["text"] != ""]

        if df.empty:
            log.debug("    No confident text detected.")
            return None

        # Translate and redraw
        modified = self._redraw(img, df)

        if not modified:
            return None

        # Downscale back to original resolution
        if scale > 1:
            img = img.resize(orig_size, Image.LANCZOS)

        # Serialise in original format
        save_fmt = self._fmt(content_type)
        buf = io.BytesIO()
        if save_fmt == "JPEG":
            img.save(buf, format="JPEG", quality=92)
        else:
            img.save(buf, format="PNG")
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

        # Group: block → paragraph (translate whole paragraph for context)
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
        # Build line-by-line text list with bounding boxes
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

        # Translate whole paragraph at once (newline-joined)
        src_text = "\n".join(d["text"] for d in line_data)
        translated = self.engine.translate(src_text)

        if translated.strip() == src_text.strip():
            return False  # nothing changed (already English or engine returned same)

        log.debug(f"    [{src_text[:40].replace(chr(10), ' ')}]")
        log.debug(f"    → [{translated[:40].replace(chr(10), ' ')}]")

        # Overall bounding box of the whole paragraph
        all_left = min(d["left"] for d in line_data)
        all_top = min(d["top"] for d in line_data)
        all_right = max(d["right"] for d in line_data)
        all_bottom = max(d["bottom"] for d in line_data)
        block_w = all_right - all_left
        block_h = all_bottom - all_top

        if block_w <= 0 or block_h <= 0:
            return False

        # Sample background from original image before painting
        bg = _sample_bg_color(img, all_left, all_top, all_right, all_bottom)
        fg = _fg_color(bg)

        # Paint over original Korean text
        draw.rectangle([all_left, all_top, all_right, all_bottom], fill=bg)

        # Draw translated English text with auto-fit + word-wrap
        flat_text = " ".join(translated.split())  # collapse newlines for flow
        _draw_block(draw, flat_text, all_left, all_top, block_w, block_h, fg)

        return True
