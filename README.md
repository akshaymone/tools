# Office Translation Tools

A suite of python CLI tools designed to translate Korean Microsoft Office documents into English via direct OOXML string manipulation and native Windows OCR.

By directly manipulating the unzipped XML structures rather than relying on high-level Python libraries (like `python-pptx`, `python-docx`, or `openpyxl`), these tools guarantee that all complex, original file contents—such as charts, macros, SmartArt, and custom XML—are preserved flawlessly.

## Tools in this Repository

| Tool | Directory | Description | Image OCR Handling |
|---|---|---|---|
| **PowerPoint Translator** | `/pptx-translate` | Translates `.pptx` slides | Appends OCR text to the Speaker Notes of the respective slide. |
| **Word Translator** | `/docx-translator` | Translates `.docx` documents | Injects OCR text directly below the image in the document flow. |
| **Excel Translator** | `/xlsx-translator` | Translates `.xlsx` workbooks | Injects a yellow Text Box shape containing the OCR text directly next to the image. |

## Shared Technologies

- **Translation**: Uses a shared `llm_factory.py` to route translation tasks through either a local **Ollama** model or the **Office API**.
- **OCR**: Uses a shared `ocr_batch.ps1` PowerShell script that hooks into the native **Windows Media OCR Engine** (built into Windows 10/11), requiring no external dependencies like Tesseract.
- **Config**: Reads configuration from `~/.translator/.env` for all tools.

See the `README.md` inside each respective directory for setup instructions, usage, and CLI flags.
