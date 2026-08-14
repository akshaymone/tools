import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytesseract
from PIL import Image
from pptx import Presentation
from tqdm import tqdm

# --- Offline Stanza Patch ---
# Stanza tries to fetch resources.json on every run. 
# We intercept it so if it fails (offline), it just uses the cached version.
try:
    import stanza.resources.common
    orig_download = stanza.resources.common.download_resources_json
    def safe_download(*args, **kwargs):
        try:
            orig_download(*args, **kwargs)
        except Exception as e:
            target_dir = kwargs.get('dir', args[0] if len(args) > 0 else None)
            target_filename = kwargs.get('filename', args[1] if len(args) > 1 else 'resources.json')
            if target_dir and os.path.exists(os.path.join(target_dir, target_filename)):
                import logging
                logging.getLogger(__name__).info("Offline mode: Using cached Stanza resources.json")
            else:
                raise e
    stanza.resources.common.download_resources_json = safe_download
    
    # Also patch pipeline.core in case it was already imported
    import stanza.pipeline.core
    stanza.pipeline.core.download_resources_json = safe_download
except ImportError:
    pass

import argostranslate.package
import argostranslate.translate



def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )

log = logging.getLogger(__name__)

# --- XML namespaces ---
NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

# --- Translation Engine ---
def get_translator():
    # Step 1: Check installed registry
    try:
        translator = argostranslate.translate.get_translation_from_codes('ko', 'en')
        if translator:
            return translator
    except Exception:
        pass
        
    log.info("Model not found in registry. Searching for cached offline model...")
    
    # Step 2: Search for cached .argosmodel locally
    cache_dirs = [
        Path.home() / ".local" / "cache" / "argos-translate" / "downloads",
        Path.home() / ".cache" / "argos-translate" / "downloads",
        Path(os.getenv("LOCALAPPDATA", "")) / "argos-translate" / "downloads" if os.name == 'nt' else None,
        Path.cwd()
    ]
    
    for d_path in filter(None, cache_dirs):
        if d_path.exists():
            models = list(d_path.rglob("translate-ko_en-*.argosmodel")) + list(d_path.rglob("*ko*en*.argosmodel"))
            if models:
                try:
                    log.info(f"Installing from cached file: {models[0]}")
                    argostranslate.package.install_from_path(models[0])
                    return argostranslate.translate.get_translation_from_codes('ko', 'en')
                except Exception as e:
                    log.warning(f"Failed to install from cache: {e}")

    # Step 3: Network download (one-time)
    log.info("No cached model found. Requires internet for one-time download...")
    try:
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()
        package_to_install = next(
            filter(lambda x: x.from_code == 'ko' and x.to_code == 'en', available_packages)
        )
        log.info("Downloading ko->en model...")
        argostranslate.package.install_from_path(package_to_install.download())
        return argostranslate.translate.get_translation_from_codes('ko', 'en')
    except Exception as e:
        log.error(f"Failed to download model offline. Please run once with internet: {e}")
        sys.exit(1)

# --- Image OCR Helpers ---
_HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')
_MIN_HANGUL_CHARS = 5
_MIN_KOREAN_RATIO = 0.40
_MIN_SOURCE_LEN = 6

def _korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    text_nospace = text.replace(" ", "")
    if not text_nospace:
        return 0.0
    hangul_count = len(_HANGUL_RE.findall(text_nospace))
    return hangul_count / len(text_nospace)

def _is_korean_text(text: str) -> bool:
    hangul_count = len(_HANGUL_RE.findall(text))
    if hangul_count < _MIN_HANGUL_CHARS:
        return False
    if len(text.strip()) < _MIN_SOURCE_LEN:
        return False
    return _korean_ratio(text) >= _MIN_KOREAN_RATIO

def extract_text_from_image(image_path: Path, lang: str = 'kor', min_height: int = 18) -> list[str]:
    try:
        img = Image.open(image_path)
    except Exception as e:
        log.warning(f"Could not open image {image_path}: {e}")
        return []

    try:
        custom_config = r'--psm 11'
        data = pytesseract.image_to_data(img, lang=lang, config=custom_config, output_type=pytesseract.Output.DICT)
        
        blocks = []
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            height = data['height'][i]
            conf = int(data['conf'][i])
            
            if conf >= 60 and height >= min_height and text:
                blocks.append(text)
                
        grouped_text = " ".join(blocks)
        
        chunks = [c.strip() for c in grouped_text.split("  ") if c.strip()]
        
        valid_korean = []
        seen = set()
        for chunk in chunks:
            if _is_korean_text(chunk) and chunk not in seen:
                valid_korean.append(chunk)
                seen.add(chunk)
                
        return valid_korean
    except Exception as e:
        log.warning(f"OCR failed on {image_path}: {e}")
        return []

# --- XML Processing ---
def translate_xml_file(xml_path: Path, translator) -> None:
    """Finds all <a:t> tags and translates their content in-place."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    changed = False

    for t_tag in root.findall('.//a:t', NS):
        text = t_tag.text
        if text and _HANGUL_RE.search(text):
            translated = translator.translate(text)
            t_tag.text = translated
            changed = True

    if changed:
        tree.write(xml_path, encoding='utf-8', xml_declaration=True)

def append_to_notes_xml(notes_xml_path: Path, new_text: str):
    """Appends a new text paragraph to the speaker notes XML."""
    tree = ET.parse(notes_xml_path)
    root = tree.getroot()
    
    spTree = root.find('.//p:spTree', NS)
    if spTree is None:
        return
        
    notes_txBody = None
    for sp in spTree.findall('./p:sp', NS):
        nvSpPr = sp.find('./p:nvSpPr', NS)
        if nvSpPr is not None:
            txBody = sp.find('./p:txBody', NS)
            if txBody is not None:
                notes_txBody = txBody
                break

    if notes_txBody is not None:
        p = ET.Element(f'{{{NS["a"]}}}p')
        r = ET.SubElement(p, f'{{{NS["a"]}}}r')
        t = ET.SubElement(r, f'{{{NS["a"]}}}t')
        t.text = new_text
        notes_txBody.append(p)
        tree.write(notes_xml_path, encoding='utf-8', xml_declaration=True)


def process_presentation(input_pptx: Path, output_pptx: Path, ocr_lang: str, min_text_height: int):
    translator = get_translator()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        
        # Step 1: Initialize Notes Slides using python-pptx
        log.info("Initializing speaker notes slides...")
        prs = Presentation(input_pptx)
        for slide in prs.slides:
            if not slide.has_notes_slide:
                _ = slide.notes_slide
        
        temp_init_pptx = temp_dir_path / "init.pptx"
        prs.save(temp_init_pptx)
        
        # Step 2: Unzip the initialized PPTX
        log.info("Unzipping presentation...")
        extract_dir = temp_dir_path / "extracted"
        with zipfile.ZipFile(temp_init_pptx, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Step 3: Translate all slide XMLs directly
        slides_dir = extract_dir / "ppt" / "slides"
        notes_dir = extract_dir / "ppt" / "notesSlides"
        media_dir = extract_dir / "ppt" / "media"
        rels_dir = slides_dir / "_rels"
        
        slide_files = list(slides_dir.glob("slide*.xml"))
        
        for slide_xml in tqdm(slide_files, desc="Translating Slides"):
            translate_xml_file(slide_xml, translator)
            
            slide_rel_path = rels_dir / f"{slide_xml.name}.rels"
            notes_xml_path = None
            image_paths = []
            
            if slide_rel_path.exists():
                rel_tree = ET.parse(slide_rel_path)
                rel_root = rel_tree.getroot()
                for rel in rel_root.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                    target = rel.get('Target')
                    if target.startswith('../notesSlides/'):
                        notes_xml_name = target.split('/')[-1]
                        notes_xml_path = notes_dir / notes_xml_name
                    elif target.startswith('../media/'):
                        img_name = target.split('/')[-1]
                        image_paths.append(media_dir / img_name)
            
            if notes_xml_path and notes_xml_path.exists():
                translate_xml_file(notes_xml_path, translator)
            
            # Step 4: Perform OCR on images and append to notes
            slide_ocr_texts = []
            for img_path in image_paths:
                if img_path.exists() and img_path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    korean_texts = extract_text_from_image(img_path, lang=ocr_lang, min_height=min_text_height)
                    for kt in korean_texts:
                        translated = translator.translate(kt)
                        slide_ocr_texts.append(f"Image Text: {kt} -> {translated}")
            
            if slide_ocr_texts and notes_xml_path and notes_xml_path.exists():
                append_to_notes_xml(notes_xml_path, "\n".join(slide_ocr_texts))

        # Step 5: Zip it back up
        log.info("Re-zipping presentation...")
        with zipfile.ZipFile(output_pptx, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for root, _, files in os.walk(extract_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(extract_dir)
                    zip_out.write(file_path, arcname)

    log.info(f"Successfully created: {output_pptx}")


def main():
    parser = argparse.ArgumentParser(description="Direct XML PPTX Translator")
    parser.add_argument("-i", "--input", required=True, help="Input PPTX file")
    parser.add_argument("-o", "--output", required=True, help="Output PPTX file")
    parser.add_argument("--lang", default="kor", help="Tesseract OCR language")
    parser.add_argument("--min-text-height", type=int, default=18)
    parser.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    setup_logging(args.verbose)
    
    in_path = Path(args.input)
    out_path = Path(args.output)
    
    if not in_path.exists():
        log.error(f"Input file not found: {in_path}")
        sys.exit(1)
        
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    process_presentation(in_path, out_path, args.lang, args.min_text_height)

if __name__ == "__main__":
    main()
