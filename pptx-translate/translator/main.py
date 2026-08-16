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


# --- XML Processing ---
def translate_xml_file(xml_path: Path, translator) -> None:
    """Finds all <a:t> tags and translates their content in-place."""
    import re
    _HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')
    
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
