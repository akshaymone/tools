import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_MSO_GROUP   = 6
_MSO_PICTURE = 13
_MIN_TEXT_HEIGHT_PX = 18

class PPTXHandler:
    def __init__(
        self,
        skip_images: bool = False,
        confidence: int = 60,
        ocr_lang: str = "kor",
        min_text_height: int = _MIN_TEXT_HEIGHT_PX,
    ) -> None:
        self.min_text_height = min_text_height
        self.skip_images = skip_images

        if skip_images:
            self.image_handler: Optional[object] = None
        else:
            from translator.image_handler import ImageHandler
            self.image_handler = ImageHandler(
                confidence=confidence,
                ocr_lang=ocr_lang,
            )

    def extract_file(self, input_path: Path, output_path: Path) -> None:
        from pptx import Presentation

        prs = Presentation(str(input_path))
        md_lines = [f"# {input_path.name}\n"]
        
        # Setup images directory
        images_dir_name = f"{output_path.stem}_images"
        images_dir = output_path.parent / images_dir_name
        
        if not self.skip_images:
            images_dir.mkdir(parents=True, exist_ok=True)

        for idx, slide in enumerate(prs.slides, 1):
            md_lines.append(f"## Slide {idx}")
            
            texts = []
            image_texts = []
            
            context = {
                "slide_idx": idx,
                "pic_idx": 1,
                "images_dir": images_dir,
                "images_dir_name": images_dir_name
            }

            for shape in slide.shapes:
                self._process_shape(shape, texts, image_texts, context)

            if slide.has_notes_slide:
                notes = self._extract_text_frame(slide.notes_slide.notes_text_frame)
                if notes:
                    texts.append("### Speaker Notes")
                    texts.extend(notes)

            if texts:
                md_lines.extend(texts)
                
            if image_texts:
                md_lines.append("\n### Images")
                md_lines.extend(image_texts)

            md_lines.append("\n---\n")

        output_path.write_text("\n".join(md_lines), encoding="utf-8")

    def _process_shape(self, shape, texts: list, image_texts: list, context: dict) -> None:
        shape_type = shape.shape_type

        if shape_type == _MSO_GROUP:
            for child in shape.shapes:
                self._process_shape(child, texts, image_texts, context)
            return

        if shape.has_text_frame:
            extracted = self._extract_text_frame(shape.text_frame)
            if extracted:
                texts.extend(extracted)

        if shape.has_table:
            extracted = self._extract_table(shape.table)
            if extracted:
                texts.extend(extracted)

        if not self.skip_images and shape_type == _MSO_PICTURE:
            self._process_picture(shape, image_texts, context)

    def _extract_text_frame(self, text_frame) -> list[str]:
        res = []
        for para in text_frame.paragraphs:
            text = para.text.strip()
            if text:
                res.append("- " + text.replace("\n", " "))
        return res

    def _extract_table(self, table) -> list[str]:
        res = []
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                cell_texts = [p.text.strip().replace("\n", " ") for p in cell.text_frame.paragraphs if p.text.strip()]
                row_text.append(" ".join(cell_texts))
            if any(row_text):
                res.append("| " + " | ".join(row_text) + " |")
        return res

    def _process_picture(self, shape, image_texts: list, context: dict) -> None:
        try:
            image = shape.image
            ext = image.ext
        except Exception:
            return

        slide_idx = context["slide_idx"]
        pic_idx = context["pic_idx"]
        context["pic_idx"] += 1
        
        img_name = f"slide_{slide_idx}_img_{pic_idx}.{ext}"
        img_path = context["images_dir"] / img_name
        
        try:
            img_path.write_bytes(image.blob)
        except Exception as e:
            log.warning(f"Could not save image {img_name}: {e}")
            return

        rel_path = f"{context['images_dir_name']}/{img_name}"
        image_texts.append(f"\n#### Image {pic_idx}")
        image_texts.append(f"![Slide {slide_idx} Image {pic_idx}]({rel_path})")

        if self.image_handler is not None:
            texts = self.image_handler.extract_text(
                image.blob,
                min_height=self.min_text_height,
            )
            if texts:
                image_texts.append("\n**Extracted Korean Text:**")
                for t in texts:
                    image_texts.append("- " + t.replace("\n", " "))
            else:
                image_texts.append("\n*(No significant Korean text found)*")
