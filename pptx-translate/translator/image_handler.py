import logging
import re
import subprocess
import json
from pathlib import Path

log = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")
_MIN_KOREAN_RATIO = 0.40
_MIN_HANGUL_CHARS = 1
_MIN_SOURCE_LEN = 1

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
    def __init__(self, confidence: int = 60, ocr_lang: str = "ko-KR", min_text_height: int = 18) -> None:
        # Note: confidence is no longer used by native Windows OCR, kept for compat
        self.ocr_lang = ocr_lang if ocr_lang != "kor" else "ko-KR"
        self.min_text_height = min_text_height

    def process_batch(self, images_dir: Path, log_dir: Path = None) -> dict[str, list[str]]:
        # log_dir MUST be outside the extracted PPTX directory — anything written
        # inside extract_dir ends up in the re-zipped PPTX and corrupts it.
        if log_dir is None:
            log_dir = images_dir.parent.parent.parent / "ocr_logs"  # outside extract_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        
        script_path = Path(__file__).parent / "ocr_batch.ps1"
        
        # Run PowerShell script
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(script_path),
            "-ImagesDir", str(images_dir),
            "-LogDir", str(log_dir),
            "-LangCode", self.ocr_lang
        ]
        
        try:
            log.info(f"Running native Windows OCR batch on {images_dir}...")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            log.info(f"PowerShell STDOUT:\n{result.stdout}")
            if result.stderr:
                log.warning(f"PowerShell STDERR:\n{result.stderr}")
        except subprocess.CalledProcessError as e:
            log.error(f"PowerShell OCR script failed with code {e.returncode}")
            log.error(f"PowerShell STDOUT:\n{e.stdout}")
            log.error(f"PowerShell STDERR:\n{e.stderr}")
            return {}
        except FileNotFoundError:
            # If running on Linux or without powershell available
            log.error("powershell.exe not found. This OCR implementation requires Windows.")
            return {}

        json_file = log_dir / "ocr_results.json"
        if not json_file.exists():
            log.error("OCR batch script did not produce ocr_results.json")
            return {}
            
        try:
            with open(json_file, "r", encoding="utf-8-sig") as f:
                raw_results = json.load(f)
        except Exception as e:
            log.error(f"Failed to read OCR results: {e}")
            return {}
            
        results = {}
        for img_name, lines_data in raw_results.items():
            seen_raw = set()
            valid_lines = []
            if not isinstance(lines_data, list):
                continue
            
            for item in lines_data:
                text = item.get("text", "")
                height = item.get("height", 0)
                
                if not text:
                    continue
                    
                log.info(f"[{img_name}] Raw OCR text (height={height}): {text}")
                
                if height < self.min_text_height:
                    log.info(f"  -> Dropped: height {height} < min {self.min_text_height}")
                    continue
                if not _is_korean_text(text):
                    log.info("  -> Dropped: Not enough Korean characters")
                    continue
                    
                cleaned = _clean_ocr_text(text)
                if not cleaned:
                    log.info("  -> Dropped: Cleaned text is empty")
                    continue
                if len(cleaned) < _MIN_SOURCE_LEN:
                    log.info(f"  -> Dropped: Cleaned length {len(cleaned)} < min {_MIN_SOURCE_LEN}")
                    continue
                if not _is_korean_text(cleaned):
                    log.info("  -> Dropped: Cleaned text has not enough Korean characters")
                    continue
                    
                if cleaned in seen_raw:
                    log.info("  -> Dropped: Duplicate text")
                    continue
                    
                seen_raw.add(cleaned)
                valid_lines.append(cleaned)
                log.info(f"  -> Kept for translation: {cleaned}")
                
            results[img_name] = valid_lines
            
        return results
