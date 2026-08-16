param(
    [string]$ImagesDir,
    [string]$LogDir,
    [string]$LangCode = "ko-KR"
)

$SCRIPT_VERSION = "v8"

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

Write-Log "ocr_batch.ps1 $SCRIPT_VERSION starting. Dir: $ImagesDir Lang: $LangCode"

# Load WinRT bridging assembly
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# Load all needed WinRT types
[Windows.Media.Ocr.OcrEngine,                    Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult,                    Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,         Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap,        Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile,                    Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream,    Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language,                 Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

# Pre-build specific strongly-typed AsTask methods upfront.
# This avoids passing [Type] objects through function parameters, which
# PowerShell 5.1 stringifies into "[TypeName]" breaking MakeGenericMethod.
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

$awaitStorageFile = $asTaskGeneric.MakeGenericMethod([Windows.Storage.StorageFile])
$awaitStream      = $asTaskGeneric.MakeGenericMethod([Windows.Storage.Streams.IRandomAccessStream])
$awaitDecoder     = $asTaskGeneric.MakeGenericMethod([Windows.Graphics.Imaging.BitmapDecoder])
$awaitBitmap      = $asTaskGeneric.MakeGenericMethod([Windows.Graphics.Imaging.SoftwareBitmap])
$awaitOcrResult   = $asTaskGeneric.MakeGenericMethod([Windows.Media.Ocr.OcrResult])

Write-Log "WinRT AsTask methods initialized OK"

$lang = [Windows.Globalization.Language]::new($LangCode)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)

if ($null -eq $engine) {
    Write-Log "ERROR: Could not create OCR engine for language $LangCode. Is the language pack installed?"
    exit 1
}

Write-Log "OCR engine created OK for $LangCode"

$results = @{}

$images = Get-ChildItem -Path $ImagesDir -File -Include *.png,*.jpg,*.jpeg -Recurse
Write-Log "Found $($images.Count) image(s) to process"

foreach ($img in $images) {
    try {
        Write-Log "Processing: $($img.Name)"

        $op1  = [Windows.Storage.StorageFile]::GetFileFromPathAsync($img.FullName)
        $file = $awaitStorageFile.Invoke($null, @($op1)).GetAwaiter().GetResult()

        $op2    = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
        $stream = $awaitStream.Invoke($null, @($op2)).GetAwaiter().GetResult()

        $op3     = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
        $decoder = $awaitDecoder.Invoke($null, @($op3)).GetAwaiter().GetResult()

        $op4            = $decoder.GetSoftwareBitmapAsync()
        $softwareBitmap = $awaitBitmap.Invoke($null, @($op4)).GetAwaiter().GetResult()

        $op5       = $engine.RecognizeAsync($softwareBitmap)
        $ocrResult = $awaitOcrResult.Invoke($null, @($op5)).GetAwaiter().GetResult()

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
                    text   = $line.Text
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
