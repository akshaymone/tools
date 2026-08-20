import re
import logging
from typing import List, Dict, Any, Tuple
from .ocr import extract_text_from_base64_image

logger = logging.getLogger(__name__)

def split_markdown_by_headers(markdown_text: str) -> List[str]:
    """
    Splits a markdown document into logical sections based on ATX headers.
    Because we use BGE-M3 (8192 context), we don't need strict 512-token chunking.
    """
    sections = re.split(r'(?=\n#{1,3}\s)', markdown_text)
    return [s.strip() for s in sections if s.strip()]

def extract_images_from_section(section_text: str) -> Tuple[str, List[Dict[str, str]]]:
    """
    Finds markdown images containing base64 data: ![alt](data:image/...;base64,...)
    Extracts them, returns the cleaned text and a list of image dicts.
    """
    images = []
    img_pattern = re.compile(r'!\[([^\]]*)\]\((data:image/[^;]+;base64,[^\)]+)\)')
    
    def replacer(match):
        alt_text = match.group(1)
        base64_data = match.group(2)
        images.append({
            "alt": alt_text,
            "base64": base64_data
        })
        return f"[Image extracted: {alt_text}]"

    cleaned_text = re.sub(img_pattern, replacer, section_text)
    return cleaned_text, images

def process_document_markdown(markdown_text: str, doc_id: str) -> List[Dict[str, Any]]:
    """
    Processes the raw markdown from the extraction API.
    Splits it, handles OCR fallback for images, and prepares Qdrant payloads.
    """
    logger.info(f"Starting chunking and OCR processing for doc_id: {doc_id}")
    sections = split_markdown_by_headers(markdown_text)
    logger.info(f"Document split into {len(sections)} sections based on headers.")
    
    processed_sections = []
    
    for i, section in enumerate(sections):
        logger.debug(f"Processing section {i+1}/{len(sections)}...")
        cleaned_text, images = extract_images_from_section(section)
        
        # Check if the section text implies a flowchart (basic heuristic)
        is_flowchart = "flowchart" in cleaned_text.lower() or "diagram" in cleaned_text.lower()
        has_table = "|" in cleaned_text and "-|-" in cleaned_text
        
        section_payload = {
            "doc_id": doc_id,
            "section_id": f"{doc_id}_sec_{i}",
            "text": cleaned_text,
            "has_table": has_table,
            "visuals": []
        }
        
        # Process extracted images
        for img_idx, img in enumerate(images):
            logger.info(f"Found image in section {i+1}. Attempting OCR fallback...")
            ocr_text = extract_text_from_base64_image(img["base64"])
            
            if len(ocr_text.strip()) > 20:
                logger.info(f"OCR extracted dense text ({len(ocr_text)} chars). Injecting into text payload.")
                # If image contains dense text, inject it back into the section text so BGE embeds it!
                section_payload["text"] += f"\n\n[Extracted text from image]:\n{ocr_text}"
            
            section_payload["visuals"].append({
                "image_id": f"{doc_id}_sec_{i}_img_{img_idx}",
                "base64": img["base64"],
                "alt": img["alt"],
                "is_flowchart": is_flowchart
            })
            
        processed_sections.append(section_payload)
        
    logger.info(f"Completed processing {len(processed_sections)} sections for {doc_id}.")
    return processed_sections
