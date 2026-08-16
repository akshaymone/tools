param(
    [string]$ImagesDir,
    [string]$LogDir,
    [string]$LangCode = "ko-KR"
)

if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

$logFile = Join-Path $LogDir "ocr_batch.log"
$jsonFile = Join-Path $LogDir "ocr_results.json"

Function Write-Log {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $msg = "[$stamp] $Message"
    Write-Host $msg
    Add-Content -Path $logFile -Value $msg
}

Write-Log "Starting OCR batch process for directory: $ImagesDir"

# Load WinRT types and Extension Methods for Async
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$lang = [Windows.Globalization.Language]::new($LangCode)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)

if ($null -eq $engine) {
    Write-Log "ERROR: Could not create OCR engine for language $LangCode. Is the language pack installed?"
    exit 1
}

$results = @{}

$images = Get-ChildItem -Path $ImagesDir -File -Include *.png,*.jpg,*.jpeg -Recurse
foreach ($img in $images) {
    try {
        Write-Log "Processing: $($img.Name)"
        $file = [Windows.Storage.StorageFile]::GetFileFromPathAsync($img.FullName).GetAwaiter().GetResult()
        $stream = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read).GetAwaiter().GetResult()
        $decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream).GetAwaiter().GetResult()
        $softwareBitmap = $decoder.GetSoftwareBitmapAsync().GetAwaiter().GetResult()
        
        $ocrResult = $engine.RecognizeAsync($softwareBitmap).GetAwaiter().GetResult()
        
        $lines = @()
        if ($null -ne $ocrResult -and $null -ne $ocrResult.Lines) {
            foreach ($line in $ocrResult.Lines) {
                $maxH = 0
                if ($null -ne $line.Words) {
                    foreach ($word in $line.Words) {
                        if ($word.BoundingRect.Height -gt $maxH) {
                            $maxH = $word.BoundingRect.Height
                        }
                    }
                }
                $lines += @{
                    text = $line.Text
                    height = [int]$maxH
                }
            }
        }
        
        $results[$img.Name] = $lines
        Write-Log "Success: $($img.Name) - extracted $($lines.Count) lines"
        
        $stream.Dispose()
    } catch {
        Write-Log "ERROR processing $($img.Name): $_"
    }
}

$results | ConvertTo-Json -Depth 5 -Compress | Set-Content -Path $jsonFile -Encoding UTF8
Write-Log "Batch complete. Results saved to $jsonFile"
