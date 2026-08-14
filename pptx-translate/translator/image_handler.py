import io
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")
_MIN_KOREAN_RATIO = 0.40
_MIN_HANGUL_CHARS = 5
_MIN_SOURCE_LEN = 6

def _korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    hangul = len(_HANGUL_RE.findall(text))
    return hangul / len(text)

def _is_korean_text(text: str) -> bool:
    hangul_count = len(_HANGUL_RE.findall(text))
    if hangul_count < _MIN_HANGUL_CHARS:
        return False
    return _korean_ratio(text) >= _MIN_KOREAN_RATIO

def _clean_ocr_text(text: str) -> str:
    lines = text.splitlines()
    kept = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _HANGUL_RE.search(line):
            line = re.sub(r"^[^\w\uAC00-\uD7A3]+|[^\w\uAC00-\uD7A3]+$", "", line)
            if line:
                kept.append(line)
    return " ".join(kept).strip()

class ImageHandler:
    OCR_CONFIG = "--psm 11 --oem 3"

    def __init__(self, confidence: int = 60, ocr_lang: str = "kor") -> None:
        self.confidence = confidence
        self.ocr_lang = ocr_lang

    def extract_text(self, image_bytes: bytes, min_height: int = 18) -> list[str]:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        scale = self._compute_scale(img)
        if scale > 1:
            img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)

        df = self._ocr_dataframe(img)
        if df is None or df.empty:
            return []

        results: list[str] = []
        seen_raw: set[str] = set()

        for (block_num,), block_df in df.groupby(["block_num"]):
            for (par_num,), par_df in block_df.groupby(["par_num"]):
                block_text, block_h = self._paragraph_text_and_height(par_df)
                if not block_text:
                    continue

                if block_h < min_height:
                    continue

                if not _is_korean_text(block_text):
                    continue

                cleaned = _clean_ocr_text(block_text)
                if not cleaned or len(cleaned) < _MIN_SOURCE_LEN or not _is_korean_text(cleaned):
                    continue

                if cleaned in seen_raw:
                    continue
                seen_raw.add(cleaned)
                results.append(cleaned)

        return results

    def _ocr_dataframe(self, img):
        import pytesseract
        try:
            df = pytesseract.image_to_data(
                img,
                lang=self.ocr_lang,
                config=self.OCR_CONFIG,
                output_type=pytesseract.Output.DATAFRAME,
            )
        except Exception:
            return None

        df = df[df["conf"] >= self.confidence].copy()
        df = df[df["text"].notna()]
        df["text"] = df["text"].astype(str).str.strip()
        df = df[df["text"] != ""]
        return df

    @staticmethod
    def _paragraph_text_and_height(par_df) -> tuple[str, int]:
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
