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

from translator.image_handler import ImageHandler

# ---------------------------------------------------------------------------
# Minimal notesSlide XML template — no python-pptx involved.
# ---------------------------------------------------------------------------
_NOTES_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    <p:sp>
      <p:nvSpPr>
        <p:cNvPr id="2" name="Slide Image Placeholder 1"/>
        <p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>
        <p:nvPr><p:ph type="sldImg"/></p:nvPr>
      </p:nvSpPr>
      <p:spPr/>
    </p:sp>
    <p:sp>
      <p:nvSpPr>
        <p:cNvPr id="3" name="Notes Placeholder 2"/>
        <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
        <p:nvPr><p:ph type="body" idx="1"/></p:nvPr>
      </p:nvSpPr>
      <p:spPr/>
      <p:txBody>
        <a:bodyPr/><a:lstStyle/>
        <a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p>
      </p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:notes>"""

_NOTES_CONTENT_TYPE = (
    'application/vnd.openxmlformats-officedocument'
    '.presentationml.notesSlide+xml'
)
_NOTES_REL_TYPE = (
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide'
)
_NM_REL_TYPE = (
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster'
)
_SLIDE_REL_TYPE = (
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide'
)

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

for _prefix, _uri in {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
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


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Strip invalid XML 1.0 control chars; flatten newlines/tabs to spaces."""
    if not text:
        return text
    cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]', '', text)
    return cleaned.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')


def translate_xml_file(xml_path: Path, translator: LLMTranslator) -> None:
    """Translate all <a:t> tags that contain Hangul, in-place via regex."""
    import xml.sax.saxutils as saxutils
    _HANGUL_RE = re.compile(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]')

    content = xml_path.read_text(encoding='utf-8')

    def replacer(match):
        prefix, text, suffix = match.group(1), match.group(2), match.group(3)
        unescaped = saxutils.unescape(text)
        if unescaped and _HANGUL_RE.search(unescaped):
            translated = translator.translate(unescaped)
            return f"{prefix}{saxutils.escape(clean_text(translated))}{suffix}"
        return match.group(0)

    new_content = re.sub(r'(<a:t>|<a:t\s[^>/]*>)(.*?)(</a:t>)', replacer, content)
    if new_content != content:
        xml_path.write_text(new_content, encoding='utf-8')


def append_to_notes_xml(notes_xml_path: Path, new_texts: list) -> None:
    """Append OCR text lines as <a:p> paragraphs into the body placeholder txBody."""
    import xml.sax.saxutils as saxutils

    content = notes_xml_path.read_text(encoding='utf-8')
    body_ph_match = re.search(r'<p:ph\s[^>]*type=["\']body["\']', content)
    if body_ph_match:
        tag_close = content.find('>', body_ph_match.start())
        search_from = tag_close if tag_close != -1 else body_ph_match.end()
    else:
        search_from = 0

    tx_body_end_idx = content.find('</p:txBody>', search_from)
    if tx_body_end_idx == -1:
        log.warning(f"Could not find </p:txBody> in {notes_xml_path.name}")
        return

    new_xml = ''.join(
        f'<a:p><a:r><a:t>{saxutils.escape(clean_text(line))}</a:t></a:r></a:p>'
        for line in new_texts
    )
    notes_xml_path.write_text(
        content[:tx_body_end_idx] + new_xml + content[tx_body_end_idx:],
        encoding='utf-8',
    )


# ---------------------------------------------------------------------------
# Notes slide creation helpers
# ---------------------------------------------------------------------------
def _parse_rels(rels_path: Path) -> list[dict]:
    try:
        tree = ET.parse(rels_path)
        ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
        return [
            {'Id': r.get('Id'), 'Type': r.get('Type'), 'Target': r.get('Target')}
            for r in tree.getroot().findall(f'{{{ns}}}Relationship')
        ]
    except Exception:
        return []


def _next_free_rid(rels: list[dict]) -> str:
    used = set()
    for r in rels:
        m = re.match(r'rId(\d+)', r.get('Id', ''))
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f'rId{n}'


def _find_notes_master(extract_dir: Path) -> str | None:
    if (extract_dir / 'ppt' / 'notesMasters' / 'notesMaster1.xml').exists():
        return '../notesMasters/notesMaster1.xml'
    return None


def ensure_notes_slides(extract_dir: Path) -> None:
    """Create minimal notesSlide XML+rels for slides that lack them."""
    slides_dir     = extract_dir / 'ppt' / 'slides'
    notes_dir      = extract_dir / 'ppt' / 'notesSlides'
    rels_dir       = slides_dir / '_rels'
    notes_rels_dir = notes_dir / '_rels'
    ct_path        = extract_dir / '[Content_Types].xml'

    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_rels_dir.mkdir(parents=True, exist_ok=True)

    notes_master_target = _find_notes_master(extract_dir)
    ct_content = ct_path.read_text(encoding='utf-8')

    notes_index = 1
    for existing in notes_dir.glob('notesSlide*.xml'):
        m = re.match(r'notesSlide(\d+)\.xml', existing.name)
        if m:
            notes_index = max(notes_index, int(m.group(1)) + 1)

    created = 0
    skipped = 0
    for slide_xml in sorted(slides_dir.glob('slide*.xml')):
        slide_rel_path = rels_dir / f'{slide_xml.name}.rels'
        rels = _parse_rels(slide_rel_path) if slide_rel_path.exists() else []

        if any(_NOTES_REL_TYPE in r.get('Type', '') for r in rels):
            skipped += 1
            continue

        notes_name = f'notesSlide{notes_index}.xml'
        (notes_dir / notes_name).write_text(_NOTES_XML_TEMPLATE, encoding='utf-8')

        rels_lines = []
        rid = 1
        if notes_master_target:
            rels_lines.append(f'  <Relationship Id="rId{rid}" Type="{_NM_REL_TYPE}" Target="{notes_master_target}"/>')
            rid += 1
        rels_lines.append(f'  <Relationship Id="rId{rid}" Type="{_SLIDE_REL_TYPE}" Target="../slides/{slide_xml.name}"/>')
        notes_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            + '\n'.join(rels_lines) + '\n</Relationships>'
        )
        (notes_rels_dir / f'{notes_name}.rels').write_text(notes_rels_xml, encoding='utf-8')

        new_rid = _next_free_rid(rels)
        new_rel = f'  <Relationship Id="{new_rid}" Type="{_NOTES_REL_TYPE}" Target="../notesSlides/{notes_name}"/>\n'
        if slide_rel_path.exists():
            txt = slide_rel_path.read_text(encoding='utf-8')
            txt = txt.replace('</Relationships>', new_rel + '</Relationships>')
            slide_rel_path.write_text(txt, encoding='utf-8')
        else:
            rels_dir.mkdir(parents=True, exist_ok=True)
            slide_rel_path.write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                f'{new_rel}</Relationships>',
                encoding='utf-8',
            )

        part_name = f'/ppt/notesSlides/{notes_name}'
        if part_name not in ct_content:
            ct_content = ct_content.replace(
                '</Types>',
                f'  <Override PartName="{part_name}" ContentType="{_NOTES_CONTENT_TYPE}"/>\n</Types>',
            )

        notes_index += 1
        created += 1

    ct_path.write_text(ct_content, encoding='utf-8')
    log.info(f"Notes slides: {skipped} already existed, {created} created.")
    if notes_master_target:
        log.info(f"  notesMaster reference: {notes_master_target}")
    else:
        log.info("  No notesMaster found in presentation.")


# ---------------------------------------------------------------------------
# ZIP packaging
# ---------------------------------------------------------------------------
def _rezip(extract_dir: Path, output_pptx: Path) -> None:
    """Re-pack extracted dir. [Content_Types].xml MUST be first (OOXML §10.1.2)."""
    ct_file = extract_dir / '[Content_Types].xml'
    all_others = sorted(p for p in extract_dir.rglob('*') if p.is_file() and p != ct_file)
    with zipfile.ZipFile(output_pptx, 'w', zipfile.ZIP_DEFLATED) as zout:
        zout.write(ct_file, '[Content_Types].xml')
        for fp in all_others:
            zout.write(fp, fp.relative_to(extract_dir).as_posix())


# ---------------------------------------------------------------------------
# Main processing pipeline
# ---------------------------------------------------------------------------
def process_presentation(
    input_pptx: Path,
    output_pptx: Path,
    ocr_lang: str,
    min_text_height: int,
    provider: str = None,
    passthrough: bool = False,
    skip_translate: bool = False,
    skip_notes: bool = False,
    save_stages: bool = False,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_dir = Path(temp_dir) / 'extracted'

        log.info("Unzipping presentation...")
        with zipfile.ZipFile(input_pptx, 'r') as zin:
            zin.extractall(extract_dir)

        if passthrough:
            log.info("[PASSTHROUGH] No modifications — rezip only.")
            _rezip(extract_dir, output_pptx)
            log.info(f"[PASSTHROUGH] Written: {output_pptx}")
            return

        translator = None if skip_translate else LLMTranslator(provider=provider)

        def _save_stage(name: str):
            if save_stages:
                p = output_pptx.parent / f"{output_pptx.stem}_stage_{name}.pptx"
                _rezip(extract_dir, p)
                log.info(f"[STAGE] {name} -> {p}")

        # Step 2: Notes slides
        if skip_notes:
            log.info("[SKIP-NOTES] Skipping notes slide creation.")
        else:
            log.info("Ensuring notes slides exist...")
            ensure_notes_slides(extract_dir)
        _save_stage("after_notes")

        slides_dir = extract_dir / 'ppt' / 'slides'
        notes_dir  = extract_dir / 'ppt' / 'notesSlides'
        media_dir  = extract_dir / 'ppt' / 'media'
        rels_dir   = slides_dir / '_rels'

        # Step 3: Batch OCR
        ocr_results: dict[str, list[str]] = {}
        if media_dir.exists():
            log.info("Running batch OCR on presentation media...")
            ocr_lang_code = ocr_lang if ocr_lang != 'kor' else 'ko-KR'
            image_handler = ImageHandler(ocr_lang=ocr_lang_code, min_text_height=min_text_height)
            # IMPORTANT: log_dir must be OUTSIDE extract_dir — files inside
            # extract_dir get packed into the ZIP and corrupt the PPTX.
            ocr_log_dir = Path(temp_dir) / 'ocr_logs'
            ocr_results = image_handler.process_batch(media_dir, log_dir=ocr_log_dir)
            if ocr_log_dir.exists():
                dest = output_pptx.parent / f'{output_pptx.stem}_ocr_logs'
                log.info(f"Saving OCR logs to {dest}")
                shutil.copytree(str(ocr_log_dir), str(dest), dirs_exist_ok=True)

        # Step 4: Translate + inject OCR
        if skip_translate:
            log.info("[SKIP-TRANSLATE] Skipping all LLM translation calls.")

        for slide_xml in tqdm(list(slides_dir.glob('slide*.xml')), desc="Processing Slides"):
            if not skip_translate:
                translate_xml_file(slide_xml, translator)

            slide_rel_path = rels_dir / f'{slide_xml.name}.rels'
            notes_xml_path = None
            image_paths: list[Path] = []

            if slide_rel_path.exists():
                for rel in _parse_rels(slide_rel_path):
                    target = rel.get('Target', '')
                    if target.startswith('../notesSlides/'):
                        notes_xml_path = notes_dir / target.split('/')[-1]
                    elif target.startswith('../media/'):
                        image_paths.append(media_dir / target.split('/')[-1])

            if notes_xml_path and notes_xml_path.exists() and not skip_translate:
                translate_xml_file(notes_xml_path, translator)

            slide_ocr_texts = []
            for img_path in image_paths:
                if img_path.exists() and img_path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    for kt in ocr_results.get(img_path.name, []):
                        if skip_translate:
                            slide_ocr_texts.append(f"Image Text (untranslated): {kt}")
                        else:
                            translated = translator.translate(kt)
                            log.info(f"[OCR] {img_path.name}: {kt!r} -> {translated!r}")
                            slide_ocr_texts.append(f"Image Text: {kt} -> {translated}")

            if slide_ocr_texts and notes_xml_path and notes_xml_path.exists():
                append_to_notes_xml(notes_xml_path, slide_ocr_texts)

        _save_stage("after_translate")

        # Step 5: XML validation
        log.info("Validating XML files before zip...")
        for xml_check in extract_dir.rglob('*.xml'):
            try:
                ET.parse(xml_check)
            except ET.ParseError as exc:
                log.warning(f"[XML INVALID] {xml_check.relative_to(extract_dir).as_posix()} — {exc}")

        # Step 6: Re-zip
        log.info("Re-zipping presentation...")
        _rezip(extract_dir, output_pptx)

    log.info(f"Successfully created: {output_pptx}")


def main():
    parser = argparse.ArgumentParser(description="Direct XML PPTX Translator")
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
        help="Run everything EXCEPT LLM translation calls. Clean=LLM is culprit; corrupt=notes/OCR is culprit."
    )
    parser.add_argument(
        "--skip-notes", action="store_true",
        help="Skip ensure_notes_slides(). Combine with --skip-translate to isolate notes creation."
    )
    parser.add_argument(
        "--save-stages", action="store_true",
        help="Save stage_after_notes.pptx and stage_after_translate.pptx checkpoints for inspection."
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    in_path  = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        log.error(f"Input file not found: {in_path}")
        sys.exit(1)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    process_presentation(
        in_path, out_path, args.lang, args.min_text_height,
        args.provider,
        passthrough=args.passthrough,
        skip_translate=args.skip_translate,
        skip_notes=args.skip_notes,
        save_stages=args.save_stages,
    )

if __name__ == "__main__":
    main()
