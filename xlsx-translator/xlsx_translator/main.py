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

from xlsx_translator.image_handler import ImageHandler

from dotenv import load_dotenv
load_dotenv(Path.home() / ".translator" / ".env")
from xlsx_translator.llm_factory import get_llm
from langchain_core.messages import SystemMessage, HumanMessage


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

for _prefix, _uri in {
    'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
}.items():
    ET.register_namespace(_prefix, _uri)


class LLMTranslator:
    def __init__(self, provider: str = None):
        self.llm = get_llm(provider=provider)
        self.system_message = SystemMessage(
            content="You are a professional translator. Translate the given Korean text into English. "
                    "Return ONLY the English translation, with no explanation, no quotation marks, and no conversational text."
        )

    def translate_batch(self, texts: list[str], document_context: str = "") -> list[str]:
        if not texts:
            return []
        
        clean_texts = [t.replace('\n', ' ').replace('\r', '') for t in texts]
        
        prompt_lines = []
        for i, text in enumerate(clean_texts):
            prompt_lines.append(f'<t id="{i}">{text}</t>')
        prompt = "\n".join(prompt_lines)
        
        system_content = (
            "You are a professional Korean to English translator for Excel spreadsheets.\n"
            "You will receive several texts wrapped in <t id=\"...\"> tags.\n"
            "Translate each text to English. Return ONLY the translated texts wrapped in the EXACT same <t id=\"...\"> tags.\n"
            "Do not add any other text, explanations, or markdown.\n"
            "Keep technical terms, brand names, and English words as-is.\n"
            "IMPORTANT: For mixed Korean-English strings (including filenames, paths, and identifiers), "
            "you MUST translate the Korean portions to English while keeping the English portions, "
            "underscores, file extensions, and structure intact. "
            "For example: '플랫폼_공통_BPM.pdf' → 'Platform_Common_BPM.pdf'.\n"
            "You MUST return a <t> tag for EVERY id you received. Do NOT skip any."
        )
        if document_context:
            system_content += (
                f"\n\n--- REFERENCE CONTEXT ---\n{document_context[:2000]}\n"
                "----------------------------------------------\n"
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
                    log.warning(f"LLM response missing translation for id={i}, keeping original: {texts[i][:80]}")
                    translated.append(texts[i])
            
            return translated
        except Exception as e:
            log.warning(f"Batch translation failed: {e}")
            return texts


def clean_text(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]', '', text)
    return cleaned.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')

def translate_xml_file(xml_path: Path, translator: LLMTranslator, log_file, sheet_name_map: dict = None) -> None:
    import xml.sax.saxutils as saxutils
    _HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')

    content = xml_path.read_text(encoding='utf-8')

    texts_to_translate = []
    # Match <t>, <x:t>, <a:t>
    t_pattern = re.compile(r'(<(?:x:|a:)?t(?:>|\s[^>]*>))(.*?)(</(?:x:|a:)?t>)', flags=re.DOTALL)
    
    for match in t_pattern.finditer(content):
        full_text = saxutils.unescape(match.group(2))
        if _HANGUL_RE.search(full_text):
            texts_to_translate.append(full_text)
            log_file.write(f"Found Korean text: {full_text}\n")
            
    if not texts_to_translate and not (sheet_name_map and xml_path.parent.name == 'worksheets'):
        return
        
    document_context = "\n".join(texts_to_translate)
    if hasattr(log_file, 'stats'):
        log_file.stats['total_texts_found'] += len(texts_to_translate)

    BATCH_SIZE = 50
    translated_texts = []
    
    if texts_to_translate:
        batches = [texts_to_translate[i:i + BATCH_SIZE] for i in range(0, len(texts_to_translate), BATCH_SIZE)]
        import concurrent.futures
        
        def _translate_batch(batch):
            return translator.translate_batch(batch, document_context=document_context)
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for translated_batch in executor.map(_translate_batch, batches):
                translated_texts.extend(translated_batch)
        
        for orig, trans in zip(texts_to_translate, translated_texts):
            log_file.write(f"Mapping: {orig} -> {trans}\n")
            if orig != trans and hasattr(log_file, 'stats'):
                log_file.stats['total_translated'] += 1
                
        translated_iter = iter(translated_texts)
        
        def t_replacer(match):
            prefix, inner, suffix = match.group(1), match.group(2), match.group(3)
            full_text = saxutils.unescape(inner)
            if _HANGUL_RE.search(full_text):
                trans_text = next(translated_iter)
                # Must ensure xml:space="preserve" is present if there are spaces, but usually okay
                return f"{prefix}{saxutils.escape(clean_text(trans_text))}{suffix}"
            return match.group(0)

        new_content = t_pattern.sub(t_replacer, content)
    else:
        new_content = content
        
    if sheet_name_map and xml_path.parent.name == 'worksheets':
        f_pattern = re.compile(r'(<f[^>]*>)(.*?)(</f>)', flags=re.DOTALL)
        def f_replacer(match):
            prefix, inner, suffix = match.group(1), match.group(2), match.group(3)
            inner_unescaped = saxutils.unescape(inner)
            changed = False
            for orig, trans in sheet_name_map.items():
                if orig in inner_unescaped:
                    inner_unescaped = inner_unescaped.replace(orig, trans)
                    changed = True
            if changed:
                return f"{prefix}{saxutils.escape(inner_unescaped)}{suffix}"
            return match.group(0)
            
        new_content = f_pattern.sub(f_replacer, new_content)

    if new_content != content:
        xml_path.write_text(new_content, encoding='utf-8')

def col_to_letter(col_idx: int) -> str:
    letter = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        letter = chr(65 + remainder) + letter
    return letter

def inject_ocr_text_as_textbox(extract_dir: Path, ocr_results: dict, translator: LLMTranslator, log_file, skip_translate: bool):
    import xml.sax.saxutils as saxutils
    ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    
    for img_filename, texts in ocr_results.items():
        if not texts:
            continue
            
        target_rid = None
        target_rels_path = None
        for rels_path in extract_dir.glob("xl/drawings/_rels/*.xml.rels"):
            try:
                tree = ET.parse(rels_path)
                for r in tree.getroot().findall(f'{{{ns}}}Relationship'):
                    if r.get('Target', '').endswith(img_filename):
                        target_rid = r.get('Id')
                        target_rels_path = rels_path
                        break
            except Exception:
                pass
            if target_rid:
                break
                
        if not target_rid:
            continue
            
        drawing_name = target_rels_path.name.replace('.rels', '')
        drawing_path = extract_dir / "xl/drawings" / drawing_name
        if not drawing_path.exists():
            continue
            
        content = drawing_path.read_text(encoding='utf-8')
        
        # Translate
        if skip_translate:
            translated_texts = [f"Image Text: {t}" for t in texts]
        else:
            ocr_ctx = "\n".join(texts)
            translated = translator.translate_batch(texts, document_context=ocr_ctx)
            translated_texts = []
            for kt, trans in zip(texts, translated):
                if kt == trans:
                    translated_texts.append(f"Image Text: {kt}")
                else:
                    translated_texts.append(f"Image Text: {kt} -> {trans}")
                    
        combined_text = "\n".join(translated_texts)
        safe_text = saxutils.escape(clean_text(combined_text))
        
        # Find where this image is in the drawing
        anchors = re.split(r'(<(?:xdr:)?(?:two|one)CellAnchor(?:>|\s[^>]*>))', content)
        new_content = ""
        injected = False
        
        for i in range(len(anchors)):
            new_content += anchors[i]
            if f'embed="{target_rid}"' in anchors[i] and not injected:
                col_m = re.search(r'<(?:xdr:)?col>(\d+)</(?:xdr:)?col>', anchors[i])
                row_m = re.search(r'<(?:xdr:)?row>(\d+)</(?:xdr:)?row>', anchors[i])
                if col_m and row_m:
                    col = int(col_m.group(1))
                    row = int(row_m.group(1))
                    
                    # Find max id to avoid conflict
                    ids = [int(x) for x in re.findall(r'id="(\d+)"', content)]
                    next_id = max(ids) + 1 if ids else 9999
                    
                    # Inject a text box below the image
                    box_xml = f"""<xdr:twoCellAnchor><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row+3}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to><xdr:col>{col+3}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row+5}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to><xdr:sp><xdr:nvSpPr><xdr:cNvPr id="{next_id}" name="OCR Translation"/><xdr:cNvSpPr txBox="1"/></xdr:nvSpPr><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="FFFFCC"/></a:solidFill></xdr:spPr><xdr:txBody><a:bodyPr wrap="square" rtlCol="0"><a:spAutoFit/></a:bodyPr><a:lstStyle/><a:p><a:r><a:t xml:space="preserve">{safe_text}</a:t></a:r></a:p></xdr:txBody></xdr:sp><xdr:clientData/></xdr:twoCellAnchor>"""
                    new_content += box_xml
                    injected = True
                    log.info(f"Injected OCR text box for {img_filename} at row {row+3}, col {col} in {drawing_name}")

        if injected:
            drawing_path.write_text(new_content, encoding='utf-8')

def _rezip(extract_dir: Path, output_xlsx: Path) -> None:
    ct_file = extract_dir / '[Content_Types].xml'
    all_others = sorted(p for p in extract_dir.rglob('*') if p.is_file() and p != ct_file)
    with zipfile.ZipFile(output_xlsx, 'w', zipfile.ZIP_DEFLATED) as zout:
        if ct_file.exists():
            zout.write(ct_file, '[Content_Types].xml')
        for fp in all_others:
            zout.write(fp, fp.relative_to(extract_dir).as_posix())

def process_document(
    input_xlsx: Path,
    output_xlsx: Path,
    ocr_lang: str,
    min_text_height: int,
    provider: str = None,
    passthrough: bool = False,
    skip_translate: bool = False,
    save_stages: bool = False,
) -> None:
    log_dir = output_xlsx.parent / f'{output_xlsx.stem}_logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    with tempfile.TemporaryDirectory() as temp_dir, open(log_dir / 'translation_debug.log', 'w', encoding='utf-8') as log_file:
        log_file.write("=== Translation Debug Log ===\n")
        log_file.stats = {'total_files': 0, 'total_texts_found': 0, 'total_translated': 0, 'total_failed': 0}
        
        extract_dir = Path(temp_dir) / 'extracted'

        log.info("Unzipping workbook...")
        with zipfile.ZipFile(input_xlsx, 'r') as zin:
            zin.extractall(extract_dir)

        if passthrough:
            log.info("[PASSTHROUGH] No modifications — rezip only.")
            _rezip(extract_dir, output_xlsx)
            log.info(f"[PASSTHROUGH] Written: {output_xlsx}")
            return

        translator = None if skip_translate else LLMTranslator(provider=provider)

        xl_dir = extract_dir / 'xl'
        media_dir = xl_dir / 'media'

        # Batch OCR
        ocr_results: dict[str, list[str]] = {}
        if media_dir.exists():
            log.info("Running batch OCR on workbook media...")
            ocr_lang_code = ocr_lang if ocr_lang != 'kor' else 'ko-KR'
            image_handler = ImageHandler(ocr_lang=ocr_lang_code, min_text_height=min_text_height)
            ocr_log_dir = Path(temp_dir) / 'ocr_logs'
            ocr_results = image_handler.process_batch(media_dir, log_dir=ocr_log_dir)
            if ocr_log_dir.exists():
                dest = output_xlsx.parent / f'{output_xlsx.stem}_ocr_logs'
                log.info(f"Saving OCR logs to {dest}")
                shutil.copytree(str(ocr_log_dir), str(dest), dirs_exist_ok=True)
                
            if ocr_results:
                inject_ocr_text_as_textbox(extract_dir, ocr_results, translator, log_file, skip_translate)

        if skip_translate:
            log.info("[SKIP-TRANSLATE] Skipping all LLM translation calls.")

        sheet_name_map = {}
        workbook_path = xl_dir / 'workbook.xml'
        if workbook_path.exists() and not skip_translate:
            log.info("Translating workbook sheet names...")
            import xml.sax.saxutils as saxutils
            content = workbook_path.read_text(encoding='utf-8')
            sheet_pattern = re.compile(r'(<sheet\s+[^>]*name=")([^"]+)(")', flags=re.IGNORECASE)
            
            sheet_names = []
            _HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')
            for match in sheet_pattern.finditer(content):
                name = saxutils.unescape(match.group(2))
                if _HANGUL_RE.search(name):
                    sheet_names.append(name)
                    
            if sheet_names:
                translated_names = translator.translate_batch(sheet_names, document_context="\n".join(sheet_names))
                for orig, trans in zip(sheet_names, translated_names):
                    sheet_name_map[orig] = trans
                    
                def sheet_replacer(match):
                    prefix = match.group(1)
                    name = saxutils.unescape(match.group(2))
                    suffix = match.group(3)
                    if name in sheet_name_map:
                        trans_name = clean_text(sheet_name_map[name])
                        trans_name = trans_name[:31]
                        trans_name = re.sub(r'[\\/?*\[\]]', '', trans_name)
                        sheet_name_map[name] = trans_name  # Update map to actual used name
                        return f"{prefix}{saxutils.escape(trans_name)}{suffix}"
                    return match.group(0)
                    
                new_content = sheet_pattern.sub(sheet_replacer, content)
                workbook_path.write_text(new_content, encoding='utf-8')
                
        app_path = extract_dir / 'docProps' / 'app.xml'
        if app_path.exists() and sheet_name_map and not skip_translate:
            import xml.sax.saxutils as saxutils
            content = app_path.read_text(encoding='utf-8')
            for orig, trans in sheet_name_map.items():
                content = content.replace(f"<vt:lpstr>{saxutils.escape(orig)}</vt:lpstr>", f"<vt:lpstr>{saxutils.escape(trans)}</vt:lpstr>")
            app_path.write_text(content, encoding='utf-8')

        xml_targets = []
        if (xl_dir / 'sharedStrings.xml').exists():
            xml_targets.append(xl_dir / 'sharedStrings.xml')
            
        for p in (xl_dir / 'worksheets').glob('*.xml'):
            if p.name.startswith('sheet'):
                xml_targets.append(p)
                
        for p in (xl_dir / 'charts').glob('*.xml'):
            if p.name.startswith('chart'):
                xml_targets.append(p)
                
        for p in (xl_dir / 'drawings').glob('*.xml'):
            if p.name.startswith('drawing'):
                xml_targets.append(p)

        for xml_file in tqdm(xml_targets, desc="Processing XML Files"):
            log_file.stats['total_files'] += 1
            log_file.write(f"\n=== Processing {xml_file.name} ===\n")
            if not skip_translate:
                translate_xml_file(xml_file, translator, log_file, sheet_name_map=sheet_name_map)

        if save_stages:
            p = output_xlsx.parent / f"{output_xlsx.stem}_stage_after_translate.xlsx"
            _rezip(extract_dir, p)
            log.info(f"[STAGE] after_translate -> {p}")
        
        log_file.write("\n=== Summary Stats ===\n")
        for k, v in log_file.stats.items():
            log_file.write(f"{k}: {v}\n")

        log.info("Validating XML files before zip...")
        for xml_check in extract_dir.rglob('*.xml'):
            try:
                ET.parse(xml_check)
            except ET.ParseError as exc:
                log.warning(f"[XML INVALID] {xml_check.relative_to(extract_dir).as_posix()} — {exc}")

        log.info("Re-zipping workbook...")
        _rezip(extract_dir, output_xlsx)

    log.info(f"Successfully created: {output_xlsx}")

def main():
    parser = argparse.ArgumentParser(description="Direct XML XLSX Translator")
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
        help="Save stage_after_translate.xlsx checkpoint for inspection."
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
