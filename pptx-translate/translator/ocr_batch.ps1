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

Function Await-WinRt {
    param($AsyncOp)
    # AsyncStatus 0 = Started
    while ($AsyncOp.Status -eq 0) {
        Start-Sleep -Milliseconds 10
    }
    # AsyncStatus 1 = Completed
    if ($AsyncOp.Status -eq 1) {
        return $AsyncOp.GetResults()
    }
    # AsyncStatus 3 = Error
    if ($AsyncOp.Status -eq 3) {
        throw "WinRT Async Operation Failed with ErrorCode: $($AsyncOp.ErrorCode)"
    }
    throw "WinRT Async Operation Cancelled or Unknown Status: $($AsyncOp.Status)"
}

Write-Log "Starting OCR batch process for directory: $ImagesDir"

# Load WinRT types
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
        
        $op1 = [Windows.Storage.StorageFile]::GetFileFromPathAsync($img.FullName)
        $file = Await-WinRt $op1
        
        $op2 = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
        $stream = Await-WinRt $op2
        
        $op3 = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
        $decoder = Await-WinRt $op3
        
        $op4 = $decoder.GetSoftwareBitmapAsync()
        $softwareBitmap = Await-WinRt $op4
        
        $op5 = $engine.RecognizeAsync($softwareBitmap)
        $ocrResult = Await-WinRt $op5
        
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
