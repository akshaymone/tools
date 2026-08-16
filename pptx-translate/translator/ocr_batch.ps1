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
    param($AsyncOp, $ResultType)
    if ($ResultType -is [string]) {
        $ResultType = [type]($ResultType -replace '^\[|\]$', '')
    }
    $asTask = $global:asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($AsyncOp))
    return $netTask.GetAwaiter().GetResult()
}

Write-Log "Starting OCR batch process for directory: $ImagesDir"

# Load WinRT bridging assembly
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# Find the generic AsTask extension method for IAsyncOperation<TResult>
$global:asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | 
    Where-Object { 
        $_.Name -eq 'AsTask' -and 
        $_.GetParameters().Count -eq 1 -and 
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
    })[0]

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
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
        $file = Await-WinRt $op1 [Windows.Storage.StorageFile]
        
        $op2 = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
        $stream = Await-WinRt $op2 [Windows.Storage.Streams.IRandomAccessStream]
        
        $op3 = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
        $decoder = Await-WinRt $op3 [Windows.Graphics.Imaging.BitmapDecoder]
        
        $op4 = $decoder.GetSoftwareBitmapAsync()
        $softwareBitmap = Await-WinRt $op4 [Windows.Graphics.Imaging.SoftwareBitmap]
        
        $op5 = $engine.RecognizeAsync($softwareBitmap)
        $ocrResult = Await-WinRt $op5 [Windows.Media.Ocr.OcrResult]
        
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
