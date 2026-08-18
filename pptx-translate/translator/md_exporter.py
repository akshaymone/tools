import logging
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

def export_markdown(extract_dir: Path, output_md: Path) -> None:
    """Exports the extracted PPTX XML structure to a Markdown file."""
    ns = {
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    }

    images_dir_name = f"{output_md.stem}_images"
    images_dir = output_md.parent / images_dir_name

    md_lines = [f"# {output_md.stem}\n"]

    # 1. Read presentation.xml to get slide order
    pres_path = extract_dir / 'ppt' / 'presentation.xml'
    pres_rels_path = extract_dir / 'ppt' / '_rels' / 'presentation.xml.rels'

    if not pres_path.exists() or not pres_rels_path.exists():
        log.warning("Could not find presentation.xml or its .rels. Exporting slides in alphabetical order.")
        slide_files = sorted((extract_dir / 'ppt' / 'slides').glob('slide*.xml'))
    else:
        # Map rId -> target (e.g. "slides/slide1.xml")
        rels_tree = ET.parse(pres_rels_path)
        rel_map = {}
        for rel in rels_tree.getroot().findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
            rel_map[rel.get('Id')] = rel.get('Target')
        
        pres_tree = ET.parse(pres_path)
        slide_files = []
        for sldId in pres_tree.getroot().findall('.//p:sldIdLst/p:sldId', ns):
            target = rel_map.get(sldId.get(f"{{{ns['r']}}}id"))
            if target:
                slide_files.append(extract_dir / 'ppt' / target)

    # Helper to parse text bodies
    def _parse_text(root_elem) -> list[str]:
        paras = []
        for p_elem in root_elem.findall('.//a:p', ns):
            para_text = ""
            for r_elem in p_elem.findall('.//a:r', ns):
                t_elem = r_elem.find('./a:t', ns)
                if t_elem is None or not t_elem.text:
                    continue
                text = t_elem.text
                rPr = r_elem.find('./a:rPr', ns)
                if rPr is not None:
                    if rPr.get('b') == '1':
                        text = f"**{text}**"
                    if rPr.get('i') == '1':
                        text = f"*{text}*"
                para_text += text
            
            # Check for list properties (bullet points)
            pPr = p_elem.find('./a:pPr', ns)
            if pPr is not None:
                lvl = int(pPr.get('lvl', '0'))
                buChar = pPr.find('./a:buChar', ns)
                buAutoNum = pPr.find('./a:buAutoNum', ns)
                if buChar is not None or buAutoNum is not None:
                    indent = "  " * lvl
                    if not para_text.startswith("- "):
                        para_text = f"{indent}- {para_text}"
            
            if para_text.strip() or para_text.strip() == "-":
                # Only keep actual text or bullets that have text
                if para_text.strip() != "-":
                    paras.append(para_text)
        return paras

    pic_idx = 1
    for slide_idx, slide_xml in enumerate(slide_files, 1):
        if not slide_xml.exists():
            continue
            
        md_lines.append(f"## Slide {slide_idx}\n")
        
        try:
            tree = ET.parse(slide_xml)
            root = tree.getroot()
        except Exception as e:
            log.warning(f"Failed to parse {slide_xml.name}: {e}")
            continue

        # Extract text
        slide_texts = _parse_text(root)
        if slide_texts:
            md_lines.extend(slide_texts)
            md_lines.append("\n")

        # Extract images
        slide_rel_path = slide_xml.parent / '_rels' / f"{slide_xml.name}.rels"
        if slide_rel_path.exists():
            rels_tree = ET.parse(slide_rel_path)
            for rel in rels_tree.getroot().findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                target = rel.get('Target')
                if target and target.startswith('../media/'):
                    img_name = target.split('/')[-1]
                    src_img = extract_dir / 'ppt' / 'media' / img_name
                    if src_img.exists():
                        images_dir.mkdir(parents=True, exist_ok=True)
                        dest_img = images_dir / f"slide_{slide_idx}_{img_name}"
                        shutil.copy2(src_img, dest_img)
                        md_lines.append(f"![Image {pic_idx}]({images_dir_name}/{dest_img.name})\n")
                        pic_idx += 1

        # Extract notes
        notes_target = None
        if slide_rel_path.exists():
            rels_tree = ET.parse(slide_rel_path)
            for rel in rels_tree.getroot().findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                if 'notesSlide' in rel.get('Type', ''):
                    notes_target = rel.get('Target')
                    break
        
        if notes_target:
            notes_xml = extract_dir / 'ppt' / 'notesSlides' / notes_target.split('/')[-1]
            if notes_xml.exists():
                try:
                    notes_tree = ET.parse(notes_xml)
                    notes_root = notes_tree.getroot()
                    notes_texts = _parse_text(notes_root)
                    if notes_texts:
                        md_lines.append("### Speaker Notes")
                        md_lines.extend(notes_texts)
                        md_lines.append("\n")
                except Exception as e:
                    log.warning(f"Failed to parse notes {notes_xml.name}: {e}")

        md_lines.append("---\n")

    output_md.write_text("\n".join(md_lines), encoding='utf-8')
    log.info(f"Markdown exported to {output_md}")
