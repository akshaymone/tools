import subprocess
import tempfile
import base64
import os
import logging

logger = logging.getLogger(__name__)

# A reliable PowerShell script to use Windows 10/11 native OCR offline
PS_OCR_SCRIPT = """
param([string]$ImagePath)

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null

try {
    $file = [Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath).GetAwaiter().GetResult()
    $stream = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read).GetAwaiter().GetResult()
    $decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream).GetAwaiter().GetResult()
    $bitmap = $decoder.GetSoftwareBitmapAsync().GetAwaiter().GetResult()
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()

    if ($engine -ne $null) {
        $result = $engine.RecognizeAsync($bitmap).GetAwaiter().GetResult()
        Write-Output $result.Text
    }
} catch {
    Write-Error $_.Exception.Message
}
"""

def extract_text_from_base64_image(base64_data: str) -> str:
    """
    Decodes a base64 image, writes it to a temporary file,
    and uses Windows native OCR via PowerShell to extract text.
    """
    if "," in base64_data:
        base64_data = base64_data.split(",", 1)[1]
        
    try:
        image_bytes = base64.b64decode(base64_data)
    except Exception as e:
        logger.error(f"Failed to decode base64 image for OCR: {e}")
        return ""
        
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
        temp_file.write(image_bytes)
        temp_path = temp_file.name
        
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ps1", mode="w", encoding="utf-8") as ps_file:
            ps_file.write(PS_OCR_SCRIPT)
            ps_script_path = ps_file.name
            
        try:
            cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", ps_script_path, "-ImagePath", temp_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                logger.warning(f"PowerShell OCR returned non-zero code. Error: {result.stderr}")
                
            return result.stdout.strip()
        finally:
            if os.path.exists(ps_script_path):
                os.remove(ps_script_path)
    except Exception as e:
        logger.warning(f"PowerShell OCR execution failed: {e}")
        return ""
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
