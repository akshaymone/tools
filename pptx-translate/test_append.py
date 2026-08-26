import sys
from pathlib import Path
from lxml import etree
import xml.etree.ElementTree as ET

from translator.main import append_to_notes_xml

notes_path = Path('extracted_test_output/ppt/notesSlides/notesSlide1.xml')

# Make a backup
import shutil
shutil.copy(notes_path, 'extracted_test_output/ppt/notesSlides/notesSlide1.xml.bak')

# Append text
new_texts = ["Line 1 translated", "Line 2 translated"]
append_to_notes_xml(notes_path, new_texts)
print("Appended texts")
