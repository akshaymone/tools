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

from tqdm import tqdm

from docx_translator.image_handler import ImageHandler

try:
    from dotenv import load_dotenv
    load_dotenv()
    from agents.llm.factory import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError as e:
    print(f"Error importing from agents package: {e}")
    print("Make sure you have installed the agents package dependencies.")
    sys.exit(1)


def setup_logging(verbose: bool, log_dir: Path = None):
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler()]
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / 'translator.log', encoding='utf-8'))
        
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        handlers=handlers,
        force=True
    )

log = logging.getLogger(__name__)

# Register DOCX namespaces just in case ET is used for validation
for _prefix, _uri in {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
}.items():
    ET.register_namespace(_prefix, _uri)


# ---------------------------------------------------------------------------
# LLM Translation Engine
# ---------------------------------------------------------------------------
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
        try:
            response = self.llm.invoke([self.system_message, HumanMessage(content=text)])
            return response.content.strip()
        except Exception as e:
            log.warning(f"LLM translation failed for '{text[:30]}': {e}")
            return text

    def translate_batch(self, texts: list[str], document_context: str = "") -> list[str]:
        if not texts:
            return []
        
        # Clean newlines from input texts to avoid confusing the LLM
        clean_texts = [t.replace('\n', ' ').replace('\r', '') for t in texts]
        
        prompt_lines = []
        for i, text in enumerate(clean_texts):
            prompt_lines.append(f'<t id="{i}">{text}</t>')
        prompt = "\n".join(prompt_lines)
        
        system_content = (
            "You are a professional Korean to English translator for technical documents.\n"
            "You will receive several texts wrapped in <t id=\"...\"> tags.\n"
            "Translate each text to English. Return ONLY the translated texts wrapped in the EXACT same <t id=\"...\"> tags.\n"
            "Do not add any other text, explanations, or markdown.\n"
            "Keep technical terms, brand names, and English words as-is."
        )
        if document_context:
            system_content += (
                f"\n\n--- REFERENCE CONTEXT (Full Document Text) ---\n{document_context}\n"
                "----------------------------------------------\n"
                "Use the reference context above to understand the full grammar and meaning of the fragments before you translate them."
            )
            
        system_msg = SystemMessage(content=system_content)
        
        try:
            response = self.llm.invoke([system_msg, HumanMessage(content=prompt)])
            response_text = response.content.strip()
            
            translated = []
            for i in range(len(texts)):
                pattern = re.compile(rf'<t\s+id=["\']?{i}["\']?>(.*?)</t>', re.DOTALL | re.IGNORECASE)
                m = pattern.search(response_text)
                if m:
                    translated.append(m.group(1).strip())
                else:
                    # Fallback if tag is missing, just append the original text
                    translated.append(texts[i])
            
            return translated
        except Exception as e:
            log.warning(f"Batch translation failed: {e}")
            return texts


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Strip invalid XML 1.0 control chars; flatten newlines/tabs to spaces."""
    if not text:
        return text
    cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]', '', text)
    return cleaned.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')


def translate_xml_file(xml_path: Path, translator: LLMTranslator, log_file) -> None:
    """Translate <w:p> tags by aggregating contained <w:t> text to preserve context."""
    import xml.sax.saxutils as saxutils
    _HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')

    content = xml_path.read_text(encoding='utf-8')

    # Pass 1: Find all paragraphs and extract text
    texts_to_translate = []
    # Match <w:p> or <w:p ...>
    para_matches = list(re.finditer(r'(<w:p(?:>|\s[^>]*>))(.*?)(</w:p>)', content, flags=re.DOTALL))
    
    for match in para_matches:
        inner_xml = match.group(2)
        # Match <w:t> or <w:t ...>
        t_matches = re.finditer(r'(<w:t(?:>|\s[^>]*>))(.*?)(</w:t>)', inner_xml, flags=re.DOTALL)
        full_text = "".join(saxutils.unescape(t.group(2)) for t in t_matches)
        if _HANGUL_RE.search(full_text):
            texts_to_translate.append(full_text)
            log_file.write(f"Found Korean text: {full_text}\n")
            
    if not texts_to_translate:
        return
        
    document_context = "\n".join(texts_to_translate)
        
    if hasattr(log_file, 'stats'):
        log_file.stats['total_texts_found'] += len(texts_to_translate)

    BATCH_SIZE = 200
    translated_texts = []
    
    for i in range(0, len(texts_to_translate), BATCH_SIZE):
        batch = texts_to_translate[i:i + BATCH_SIZE]
        
        prompt_lines = [f"{j+1}. {text}" for j, text in enumerate(batch)]
        prompt = "\n".join(prompt_lines)
        log_file.write(f"--- BATCH PROMPT (Chunk {i//BATCH_SIZE + 1}) ---\n" + prompt + "\n--------------------\n")
        
        translated_batch = translator.translate_batch(batch, document_context=document_context)
        
        log_file.write(f"--- BATCH RESPONSE (Chunk {i//BATCH_SIZE + 1}) ---\n")
        for j, t in enumerate(translated_batch):
            log_file.write(f"{j+1}. {t}\n")
        log_file.write("----------------------\n")
        
        translated_texts.extend(translated_batch)
    
    for orig, trans in zip(texts_to_translate, translated_texts):
        log_file.write(f"Mapping: {orig} -> {trans}\n")
        if orig == trans:
            log_file.write(f"Warning: Text untranslated: {orig}\n")
            if hasattr(log_file, 'stats'):
                log_file.stats['total_failed'] += 1
        else:
            if hasattr(log_file, 'stats'):
                log_file.stats['total_translated'] += 1
            
    # Pass 2: Re-inject translated texts back into the first <w:t> of each translated paragraph
    translated_iter = iter(translated_texts)
    
    def para_replacer(para_match):
        prefix_p, inner_xml, suffix_p = para_match.group(1), para_match.group(2), para_match.group(3)
        
        t_matches = list(re.finditer(r'(<w:t(?:>|\s[^>]*>))(.*?)(</w:t>)', inner_xml, flags=re.DOTALL))
        full_text = "".join(saxutils.unescape(t.group(2)) for t in t_matches)
        
        if _HANGUL_RE.search(full_text):
            trans_text = next(translated_iter)
            first = True
            def t_replacer(t_match):
                nonlocal first
                prefix_t, _, suffix_t = t_match.group(1), t_match.group(2), t_match.group(3)
                if first:
                    first = False
                    # Make sure xml:space="preserve" is there if needed, but keeping the original tag is usually fine
                    return f"{prefix_t}{saxutils.escape(clean_text(trans_text))}{suffix_t}"
                return f"{prefix_t}{suffix_t}" # Leave subsequent runs empty
                
            new_inner = re.sub(r'(<w:t(?:>|\s[^>]*>))(.*?)(</w:t>)', t_replacer, inner_xml, flags=re.DOTALL)
            return f"{prefix_p}{new_inner}{suffix_p}"
            
        return para_match.group(0)

    new_content = re.sub(r'(<w:p(?:>|\s[^>]*>))(.*?)(</w:p>)', para_replacer, content, flags=re.DOTALL)
    if new_content != content:
        xml_path.write_text(new_content, encoding='utf-8')


def inject_ocr_text(doc_xml_path: Path, rels_path: Path, ocr_results: dict[str, list[str]], translator: LLMTranslator, log_file, skip_translate: bool) -> None:
    """Injects OCR translations directly below the corresponding images in document.xml."""
    import xml.sax.saxutils as saxutils
    
    if not rels_path.exists():
        return
        
    # Map image filename (e.g., 'image1.png') to rId
    filename_to_rid = {}
    try:
        tree = ET.parse(rels_path)
        ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
        for r in tree.getroot().findall(f'{{{ns}}}Relationship'):
            target = r.get('Target', '')
            if target.startswith('media/'):
                filename = target.split('/')[-1]
                filename_to_rid[filename] = r.get('Id')
    except Exception as e:
        log.warning(f"Failed to parse rels file {rels_path}: {e}")
        return

    content = doc_xml_path.read_text(encoding='utf-8')
    
    # Process each image that has OCR results
    for img_filename, texts in ocr_results.items():
        rid = filename_to_rid.get(img_filename)
        if not rid:
            continue
            
        if not texts:
            continue
            
        log_file.write(f"\n--- Processing OCR for {img_filename} ({rid}) ---\n")
        
        if skip_translate:
            translated_texts = [f"Image Text (untranslated): {t}" for t in texts]
        else:
            ocr_document_context = "\n".join(texts)
            translated = translator.translate_batch(texts, document_context=ocr_document_context)
            translated_texts = []
            for kt, trans in zip(texts, translated):
                if kt == trans:
                    translated_texts.append(f"Image Text: {kt} -> [Korean] {kt}")
                    log_file.write(f"Warning: OCR Text untranslated: {kt}\n")
                else:
                    translated_texts.append(f"Image Text: {kt} -> {trans}")
                    log.info(f"[OCR] {img_filename}: {kt!r} -> {trans!r}")

        # Now find where this rId is used in the document
        blip_pattern = re.compile(rf'<a:blip[^>]*r:embed=["\']{rid}["\'][^>]*>')
        blip_match = blip_pattern.search(content)
        if not blip_match:
            continue
            
        # Find the end of the enclosing paragraph
        wp_end = content.find('</w:p>', blip_match.end())
        if wp_end == -1:
            continue
            
        insert_pos = wp_end + len('</w:p>')
        
        # Construct the new paragraphs to inject
        # Wrap the OCR text in an italicised run for clarity:
        injection = ""
        for line in translated_texts:
            safe_text = saxutils.escape(clean_text(line))
            injection += f'<w:p><w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">{safe_text}</w:t></w:r></w:p>'
            
        # Splice it in
        content = content[:insert_pos] + injection + content[insert_pos:]
        
    doc_xml_path.write_text(content, encoding='utf-8')


# ---------------------------------------------------------------------------
# ZIP packaging
# ---------------------------------------------------------------------------
def _rezip(extract_dir: Path, output_docx: Path) -> None:
    """Re-pack extracted dir. [Content_Types].xml MUST be first (OOXML §10.1.2)."""
    ct_file = extract_dir / '[Content_Types].xml'
    all_others = sorted(p for p in extract_dir.rglob('*') if p.is_file() and p != ct_file)
    with zipfile.ZipFile(output_docx, 'w', zipfile.ZIP_DEFLATED) as zout:
        if ct_file.exists():
            zout.write(ct_file, '[Content_Types].xml')
        for fp in all_others:
            zout.write(fp, fp.relative_to(extract_dir).as_posix())


# ---------------------------------------------------------------------------
# Main processing pipeline
# ---------------------------------------------------------------------------
def process_document(
    input_docx: Path,
    output_docx: Path,
    ocr_lang: str,
    min_text_height: int,
    provider: str = None,
    passthrough: bool = False,
    skip_translate: bool = False,
    save_stages: bool = False,
) -> None:
    log_dir = output_docx.parent / f'{output_docx.stem}_logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    with tempfile.TemporaryDirectory() as temp_dir, open(log_dir / 'translation_debug.log', 'w', encoding='utf-8') as log_file:
        log_file.write("=== Translation Debug Log ===\n")
        log_file.stats = {'total_files': 0, 'total_texts_found': 0, 'total_translated': 0, 'total_failed': 0}
        
        extract_dir = Path(temp_dir) / 'extracted'

        log.info("Unzipping document...")
        with zipfile.ZipFile(input_docx, 'r') as zin:
            zin.extractall(extract_dir)

        if passthrough:
            log.info("[PASSTHROUGH] No modifications — rezip only.")
            _rezip(extract_dir, output_docx)
            log.info(f"[PASSTHROUGH] Written: {output_docx}")
            return

        translator = None if skip_translate else LLMTranslator(provider=provider)

        word_dir = extract_dir / 'word'
        media_dir = word_dir / 'media'
        rels_dir = word_dir / '_rels'

        # Batch OCR
        ocr_results: dict[str, list[str]] = {}
        if media_dir.exists():
            log.info("Running batch OCR on document media...")
            ocr_lang_code = ocr_lang if ocr_lang != 'kor' else 'ko-KR'
            image_handler = ImageHandler(ocr_lang=ocr_lang_code, min_text_height=min_text_height)
            ocr_log_dir = Path(temp_dir) / 'ocr_logs'
            ocr_results = image_handler.process_batch(media_dir, log_dir=ocr_log_dir)
            if ocr_log_dir.exists():
                dest = output_docx.parent / f'{output_docx.stem}_ocr_logs'
                log.info(f"Saving OCR logs to {dest}")
                shutil.copytree(str(ocr_log_dir), str(dest), dirs_exist_ok=True)

        # Translate Text
        if skip_translate:
            log.info("[SKIP-TRANSLATE] Skipping all LLM translation calls.")

        # Core word files containing text
        xml_targets = []
        for p in word_dir.glob('*.xml'):
            # Only translate document, headers, footers, footnotes, endnotes
            if p.name.startswith(('document', 'header', 'footer', 'footnotes', 'endnotes')):
                xml_targets.append(p)

        for xml_file in tqdm(xml_targets, desc="Processing XML Files"):
            log_file.stats['total_files'] += 1
            log_file.write(f"\n=== Processing {xml_file.name} ===\n")
            
            if not skip_translate:
                translate_xml_file(xml_file, translator, log_file)
                
            # If it's the main document, inject OCR text
            if xml_file.name == 'document.xml' and ocr_results:
                doc_rels_path = rels_dir / 'document.xml.rels'
                inject_ocr_text(xml_file, doc_rels_path, ocr_results, translator, log_file, skip_translate)

        if save_stages:
            p = output_docx.parent / f"{output_docx.stem}_stage_after_translate.docx"
            _rezip(extract_dir, p)
            log.info(f"[STAGE] after_translate -> {p}")
        
        log_file.write("\n=== Summary Stats ===\n")
        for k, v in log_file.stats.items():
            log_file.write(f"{k}: {v}\n")

        # XML validation
        log.info("Validating XML files before zip...")
        for xml_check in extract_dir.rglob('*.xml'):
            try:
                ET.parse(xml_check)
            except ET.ParseError as exc:
                log.warning(f"[XML INVALID] {xml_check.relative_to(extract_dir).as_posix()} — {exc}")

        # Re-zip
        log.info("Re-zipping document...")
        _rezip(extract_dir, output_docx)

    log.info(f"Successfully created: {output_docx}")


def main():
    parser = argparse.ArgumentParser(description="Direct XML DOCX Translator")
    parser.add_argument("-i", "--input",  required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--lang",            default="kor")
    parser.add_argument("--min-text-height", type=int, default=5)
    parser.add_argument("--provider",        default=None)
    parser.add_argument("--verbose",         action="store_true")
    parser.add_argument(
        "--passthrough", action="store_true",
        help="Unzip+rezip only — no changes. Clean=zip ok; corrupt=zip bug."
    )
    parser.add_argument(
        "--skip-translate", action="store_true",
        help="Run everything EXCEPT LLM translation calls. Clean=LLM is culprit; corrupt=OCR is culprit."
    )
    parser.add_argument(
        "--save-stages", action="store_true",
        help="Save stage_after_translate.docx checkpoint for inspection."
    )

    args = parser.parse_args()

    in_path  = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        log.error(f"Input file not found: {in_path}")
        sys.exit(1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    log_dir = out_path.parent / f'{out_path.stem}_logs'
    setup_logging(args.verbose, log_dir)

    process_document(
        in_path, out_path, args.lang, args.min_text_height,
        args.provider,
        passthrough=args.passthrough,
        skip_translate=args.skip_translate,
        save_stages=args.save_stages,
    )

if __name__ == "__main__":
    main()
