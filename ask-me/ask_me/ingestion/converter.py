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
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            try:
                doc = word.Documents.Open(str(input_path))
                doc.SaveAs(str(output_path), FileFormat=17) # 17 is wdFormatPDF
                doc.Close()
            finally:
                word.Quit()
                
        elif ext == ".pptx":
            # PowerPoint formatting
            powerpoint = win32com.client.DispatchEx("Powerpoint.Application")
            try:
                presentation = powerpoint.Presentations.Open(str(input_path), WithWindow=False)
                presentation.SaveAs(str(output_path), 32) # 32 is ppSaveAsPDF
                presentation.Close()
            finally:
                powerpoint.Quit()
        else:
            raise ValueError(f"Unsupported file format for conversion: {ext}")
            
    except Exception as e:
        logger.error(f"Failed to convert {input_path.name} to PDF: {e}")
        raise
    finally:
        pythoncom.CoUninitialize()
        
    return str(output_path)

def extract_page_images(pdf_path: str):
    """
    Converts a PDF file into a list of PIL Images (one per page).
    """
    from pdf2image import convert_from_path
    logger.info(f"Rendering pages from PDF to images: {pdf_path}")
    return convert_from_path(pdf_path)
