import argparse
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pptx import Presentation
from tqdm import tqdm

from translator.image_handler import ImageHandler

try:
    from dotenv import load_dotenv
    load_dotenv()
    
    from agents.llm.factory import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError as e:
    print(f"Error importing from agents package: {e}")
    print("Make sure you have installed the agents package dependencies.")
    sys.exit(1)


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

# --- Translation Engine (LLM) ---
class LLMTranslator:
    def __init__(self, provider: str = None):
        self.llm = get_llm(provider=provider)
        self.system_message = SystemMessage(
            content="You are a professional translator. Translate the given Korean text into English. "
                    "Return ONLY the English translation, with no explanation, no quotation marks, and no conversational text."
        )
        
    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        messages = [
            self.system_message,
            HumanMessage(content=text)
        ]
        try:
            response = self.llm.invoke(messages)
            return response.content.strip()
        except Exception as e:
            log.warning(f"LLM translation failed for text '{text[:20]}...': {e}")
            return text

def get_translator(provider: str = None):
    return LLMTranslator(provider=provider)


def clean_text(text: str) -> str:
    if not text:
        return text
    # Keep only valid XML 1.0 characters
    import re
    cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]', '', text)
    # PowerPoint <a:t> tags do NOT allow newlines, carriage returns or tabs.
    # They must be replaced with spaces.
    return cleaned.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')

def translate_xml_file(xml_path: Path, translator) -> None:
    """Finds all <a:t> tags and translates their content in-place."""
    import re
    import xml.sax.saxutils as saxutils
    
    _HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')
    
    content = xml_path.read_text(encoding='utf-8')
    
    def replacer(match):
        prefix = match.group(1)
        text = match.group(2)
        suffix = match.group(3)
        
        unescaped = saxutils.unescape(text)
        if unescaped and _HANGUL_RE.search(unescaped):
            translated = translator.translate(unescaped)
            cleaned = clean_text(translated)
            escaped = saxutils.escape(cleaned)
            return f"{prefix}{escaped}{suffix}"
        return match.group(0)
        
    new_content = re.sub(r'(<a:t[^>]*>)(.*?)(</a:t>)', replacer, content)
    
    if new_content != content:
        xml_path.write_text(new_content, encoding='utf-8')

def append_to_notes_xml(notes_xml_path: Path, new_texts: list):
    """Appends new text paragraphs to the speaker notes XML."""
    import re
    import xml.sax.saxutils as saxutils

    content = notes_xml_path.read_text(encoding='utf-8')

    # Find the body placeholder <p:ph type="body".../>
    # We need the </p:txBody> that closes the *same* <p:sp> element.
    # Strategy: find the closing tag of the <p:ph .../> element, then search
    # forward for </p:txBody> from there — this always lands inside the
    # correct shape's txBody and never in the title shape above it.
    body_ph_match = re.search(r'<p:ph\s[^>]*type=["\']body["\']', content)
    if body_ph_match:
        # The placeholder tag may be self-closing (/>) or have a child element.
        # Either way, find the close of the tag token first.
        tag_close = content.find('>', body_ph_match.start())
        search_from = tag_close if tag_close != -1 else body_ph_match.end()
    else:
        # Fallback: use the last </p:txBody> in the document (notes body is last)
        search_from = 0

    tx_body_end_idx = content.find('</p:txBody>', search_from)
    if tx_body_end_idx == -1:
        log.warning(f"Could not find </p:txBody> in {notes_xml_path.name}, skipping notes append.")
        return

    new_xml = ""
    for text_line in new_texts:
        clean_line = clean_text(text_line)
        escaped_line = saxutils.escape(clean_line)
        new_xml += f'<a:p><a:r><a:t>{escaped_line}</a:t></a:r></a:p>'

    new_content = content[:tx_body_end_idx] + new_xml + content[tx_body_end_idx:]
    notes_xml_path.write_text(new_content, encoding='utf-8')


def process_presentation(input_pptx: Path, output_pptx: Path, ocr_lang: str, min_text_height: int, provider: str = None):
    translator = get_translator(provider)
    
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
        
        # Run Batch OCR on extracted media first
        ocr_results = {}
        if media_dir.exists():
            log.info("Running batch OCR on presentation media...")
            ocr_lang_code = ocr_lang if ocr_lang != "kor" else "ko-KR"
            image_handler = ImageHandler(ocr_lang=ocr_lang_code, min_text_height=min_text_height)
            ocr_results = image_handler.process_batch(media_dir)
            
            # Copy OCR logs to output directory for debugging
            ocr_log_dir = media_dir.parent / f"{media_dir.name}_logs"
            if ocr_log_dir.exists():
                dest_dir = output_pptx.parent / f"{output_pptx.stem}_ocr_logs"
                log.info(f"Saving OCR logs to {dest_dir} for debugging")
                import shutil
                shutil.copytree(ocr_log_dir, dest_dir, dirs_exist_ok=True)
        
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
                    korean_texts = ocr_results.get(img_path.name, [])
                    if korean_texts:
                        log.info(f"Found {len(korean_texts)} OCR text blocks in {img_path.name}")
                    for kt in korean_texts:
                        translated = translator.translate(kt)
                        log.info(f"[OCR] {img_path.name} | Original: {kt} | Translated: {translated}")
                        slide_ocr_texts.append(f"Image Text: {kt} -> {translated}")
            
            if slide_ocr_texts and notes_xml_path and notes_xml_path.exists():
                append_to_notes_xml(notes_xml_path, slide_ocr_texts)

        # Step 5 (pre-check): Validate all XMLs before zipping to catch corruption early
        log.info("Validating XML files before zip...")
        import xml.etree.ElementTree as _ET
        for xml_check in extract_dir.rglob("*.xml"):
            try:
                _ET.parse(xml_check)
            except _ET.ParseError as exc:
                log.warning(f"[XML INVALID] {xml_check.relative_to(extract_dir).as_posix()} — {exc}")

        # Step 5: Zip it back up
        log.info("Re-zipping presentation...")
        with zipfile.ZipFile(output_pptx, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for root, _, files in os.walk(extract_dir):
                for file in sorted(files):  # sorted for reproducibility
                    file_path = Path(root) / file
                    # PPTX is a ZIP — ZIP spec requires forward-slash separators.
                    # Path.relative_to() on Windows returns backslashes which
                    # break PowerPoint's part-resolution and trigger the repair prompt.
                    arcname = file_path.relative_to(extract_dir).as_posix()
                    zip_out.write(file_path, arcname)

    log.info(f"Successfully created: {output_pptx}")


def main():
    parser = argparse.ArgumentParser(description="Direct XML PPTX Translator")
    parser.add_argument("-i", "--input", required=True, help="Input PPTX file")
    parser.add_argument("-o", "--output", required=True, help="Output PPTX file")
    parser.add_argument("--lang", default="kor", help="Tesseract OCR language")
    parser.add_argument("--min-text-height", type=int, default=18)
    parser.add_argument("--provider", default=None, help="LLM provider (e.g. ollama, office)")
    parser.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    setup_logging(args.verbose)
    
    in_path = Path(args.input)
    out_path = Path(args.output)
    
    if not in_path.exists():
        log.error(f"Input file not found: {in_path}")
        sys.exit(1)
        
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    process_presentation(in_path, out_path, args.lang, args.min_text_height, args.provider)

if __name__ == "__main__":
    main()
