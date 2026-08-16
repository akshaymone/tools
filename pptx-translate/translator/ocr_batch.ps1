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
    [WinRtWaiter]::Wait($AsyncOp)
    return $AsyncOp.GetResults()
}

Write-Log "Starting OCR batch process for directory: $ImagesDir"

# Load WinRT types and compile C# waiter
$csharpCode = @"
using System;
using System.Threading;
using System.Threading.Tasks;
using System.Runtime.InteropServices;

[ComImport]
[Guid("00000036-0000-0000-C000-000000000046")]
[InterfaceType(ComInterfaceType.InterfaceIsIInspectable)]
public interface IAsyncInfo {
    uint Id { get; }
    int Status { get; }
    int ErrorCode { get; }
    void Cancel();
    void Close();
}

public class WinRtWaiter {
    public static void Wait(object op) {
        var task = Task.Run(() => {
            var info = (IAsyncInfo)op;
            // 0 = Started, 1 = Completed, 2 = Canceled, 3 = Error
            while (info.Status == 0) {
                Thread.Sleep(10);
            }
            if (info.Status != 1) {
                throw new Exception("WinRT operation failed with status: " + info.Status);
            }
        });
        
        // GetAwaiter().GetResult() safely pumps COM STA messages, preventing deadlocks
        task.GetAwaiter().GetResult();
    }
}
"@
Add-Type -TypeDefinition $csharpCode

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
