"""
translator/pptx_handler.py

Walks every slide in a Presentation and translates:
  - Text frames (titles, body, text boxes)
  - Tables (cell by cell)
  - Group shapes (recursively unwrapped)
  - Embedded picture shapes (via ImageHandler OCR pipeline)
  - Speaker notes

Formatting contract:
  Translation is done at the paragraph level.  The translated string is
  written into the FIRST non-empty run of each paragraph; all subsequent
  runs in that paragraph are cleared.  This preserves the paragraph's
  font, size, bold, italic, colour, and alignment properties, which live
  on the run/paragraph level in python-pptx.

  For tables, the same logic applies per cell.

  Image blobs are replaced in-place by swapping the part's _blob attribute.
"""

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# MSO shape type constants (python-pptx / OOXML)
_MSO_GROUP   = 6   # MsoShapeType.GROUP
_MSO_PICTURE = 13  # MsoShapeType.PICTURE


class PPTXHandler:
    def __init__(
        self,
        engine,
        skip_images: bool = False,
        confidence: int = 60,
        ocr_lang: str = "kor",
        dry_run: bool = False,
    ) -> None:
        self.engine = engine
        self.dry_run = dry_run

        if skip_images:
            self.image_handler: Optional[object] = None
        else:
            from translator.image_handler import ImageHandler
            self.image_handler = ImageHandler(
                engine=engine,
                confidence=confidence,
                ocr_lang=ocr_lang,
            )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def translate_file(self, input_path: Path, output_path: Path) -> None:
        from pptx import Presentation

        prs = Presentation(str(input_path))
        n = len(prs.slides)

        for idx, slide in enumerate(prs.slides, 1):
            log.info(f"   Slide {idx}/{n}")
            self._process_slide(slide)

        if not self.dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            prs.save(str(output_path))

    # ------------------------------------------------------------------
    # Slide-level processing
    # ------------------------------------------------------------------

    def _process_slide(self, slide) -> None:
        for shape in slide.shapes:
            self._process_shape(shape)

        # Speaker notes
        if slide.has_notes_slide:
            notes_tf = slide.notes_slide.notes_text_frame
            self._translate_text_frame(notes_tf, label="[notes]")

    # ------------------------------------------------------------------
    # Shape dispatch
    # ------------------------------------------------------------------

    def _process_shape(self, shape) -> None:
        shape_type = shape.shape_type

        # Recursively unwrap group shapes
        if shape_type == _MSO_GROUP:
            for child in shape.shapes:
                self._process_shape(child)
            return

        # Text frames (text boxes, placeholders, auto-shapes with text)
        if shape.has_text_frame:
            self._translate_text_frame(shape.text_frame, label=shape.name)

        # Tables
        if shape.has_table:
            self._translate_table(shape.table)

        # Embedded pictures → OCR pipeline
        if self.image_handler is not None and shape_type == _MSO_PICTURE:
            self._process_picture(shape)

    # ------------------------------------------------------------------
    # Text frame / paragraph translation
    # ------------------------------------------------------------------

    def _translate_text_frame(self, text_frame, label: str = "") -> None:
        for para in text_frame.paragraphs:
            self._translate_paragraph(para, label=label)

    def _translate_paragraph(self, para, label: str = "") -> None:
        full_text = para.text.strip()
        if not full_text:
            return

        translated = self.engine.translate(full_text)
        if not translated or translated.strip() == full_text:
            return

        if self.dry_run:
            log.info(f"      [DRY] {label}: {full_text[:55]!r}")
            log.info(f"              → {translated[:55]!r}")
            return

        # Collect all runs that have content
        active_runs = [r for r in para.runs if r.text.strip()]
        if not active_runs:
            return

        # Write translated text into first run, blank out the rest
        active_runs[0].text = translated
        for run in active_runs[1:]:
            run.text = ""

        log.debug(f"      {label}: {full_text[:40]!r} → {translated[:40]!r}")

    def _translate_table(self, table) -> None:
        for row in table.rows:
            for cell in row.cells:
                self._translate_text_frame(cell.text_frame, label="[table]")

    # ------------------------------------------------------------------
    # Image / picture translation
    # ------------------------------------------------------------------

    def _process_picture(self, shape) -> None:
        """OCR the image, translate detected text, replace blob in-place."""
        try:
            image = shape.image
        except Exception as exc:
            log.warning(f"      Could not access image for shape {shape.name!r}: {exc}")
            return

        size_kb = len(image.blob) // 1024
        log.debug(f"      OCR → shape {shape.name!r} ({size_kb} KB, {image.content_type})")

        try:
            new_blob = self.image_handler.process(
                image.blob, content_type=image.content_type
            )
        except Exception as exc:
            log.warning(f"      Image OCR/translation failed [{shape.name}]: {exc}")
            return

        if new_blob is None:
            log.debug("      No Korean text found — image unchanged.")
            return

        if self.dry_run:
            log.info(f"      [DRY] Image shape {shape.name!r} would be translated.")
            return

        # Replace the image blob inside the PPTX package in-place
        try:
            rId = shape._element.blipFill.blip.rEmbed
            img_part = shape.part.related_parts[rId]
            img_part._blob = new_blob
            log.debug(f"      Image blob replaced ({len(new_blob)//1024} KB).")
        except Exception as exc:
            log.warning(f"      Failed to replace image blob [{shape.name}]: {exc}")
