import os
import win32com.client
import pythoncom
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def convert_to_pdf(input_path: str) -> str:
    """
    Converts a .docx or .pptx file to PDF using local Microsoft Office installation.
    Returns the path to the newly created PDF.
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Cannot find {input_path}")
        
    ext = input_path.suffix.lower()
    if ext == ".pdf":
        return str(input_path)
        
    output_path = input_path.with_suffix(".pdf")
    
    if output_path.exists():
        logger.info(f"PDF already exists for {input_path.name}, skipping conversion.")
        return str(output_path)
        
    # Required for COM calls in background threads
    pythoncom.CoInitialize()
    
    try:
        if ext == ".docx":
            # Word formatting
            logger.debug("Dispatching Word.Application via COM. This may take a moment.")
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            try:
                logger.debug(f"Opening Word document: {input_path}. If the script hangs here indefinitely, Word might be showing a hidden popup (like a password or macro prompt). Check Task Manager and kill WINWORD.EXE.")
                doc = word.Documents.Open(str(input_path))
                logger.debug(f"Saving Word document as PDF: {output_path}")
                doc.SaveAs(str(output_path), FileFormat=17) # 17 is wdFormatPDF
                doc.Close()
                logger.debug(f"Closed Word document: {input_path}")
            finally:
                logger.debug("Quitting Word.Application.")
                word.Quit()
                
        elif ext == ".pptx":
            # PowerPoint formatting
            logger.debug("Dispatching Powerpoint.Application via COM. This may take a moment.")
            powerpoint = win32com.client.DispatchEx("Powerpoint.Application")
            try:
                logger.debug(f"Opening PowerPoint presentation: {input_path}. If the script hangs here, PowerPoint might be showing a hidden popup. Check Task Manager and kill POWERPNT.EXE.")
                presentation = powerpoint.Presentations.Open(str(input_path), WithWindow=False)
                logger.debug(f"Saving PowerPoint presentation as PDF: {output_path}")
                presentation.SaveAs(str(output_path), 32) # 32 is ppSaveAsPDF
                presentation.Close()
                logger.debug(f"Closed PowerPoint presentation: {input_path}")
            finally:
                logger.debug("Quitting Powerpoint.Application.")
                powerpoint.Quit()
        else:
            raise ValueError(f"Unsupported file format for conversion: {ext}")
            
    except Exception as e:
        logger.error(f"Failed to convert {input_path.name} to PDF: {e}")
        raise
    finally:
        pythoncom.CoUninitialize()
        
    return str(output_path)

def extract_page_images(pdf_path: str, batch_size: int = 5):
    """
    Converts a PDF file into a list of PIL Images (one per page).
    Yields batches of images to prevent OOM on large PDFs.
    """
    from pdf2image import convert_from_path, pdfinfo_from_path
    
    logger.info(f"Analyzing PDF for chunked rendering: {pdf_path}")
    try:
        info = pdfinfo_from_path(pdf_path)
        total_pages = info.get("Pages", 1)
    except Exception as e:
        logger.warning(f"Could not get pdfinfo, defaulting to chunkless extraction: {e}")
        logger.debug(f"If the PDF is very large, this step may take a while to complete silently. Using pdf2image on: {pdf_path}")
        images = convert_from_path(pdf_path)
        logger.debug(f"Successfully extracted {len(images)} pages from {pdf_path}.")
        yield 1, images
        return

    logger.debug(f"PDF {pdf_path} has {total_pages} pages. Extracting in batches of {batch_size}.")
    for start_page in range(1, total_pages + 1, batch_size):
        end_page = min(start_page + batch_size - 1, total_pages)
        logger.debug(f"Rendering pages {start_page} to {end_page} from PDF to images...")
        images = convert_from_path(pdf_path, first_page=start_page, last_page=end_page)
        logger.debug(f"Successfully extracted {len(images)} pages.")
        yield start_page, images
