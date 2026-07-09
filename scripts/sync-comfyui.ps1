# Weekly ComfyUI mirror: C:\AI\ComfyUI (primary) -> E:\AI\ComfyUI (backup).
# /MIR makes E: an exact copy of C: (adds new files, removes deleted ones).
# Registered as scheduled task "SyncComfyUI" (weekly); run manually anytime:
#   powershell -ExecutionPolicy Bypass -File scripts\sync-comfyui.ps1
# ASCII only - PS 5.1 reads BOM-less files as ANSI.

$src = 'C:\AI\ComfyUI'
$dst = 'E:\AI\ComfyUI'
$log = "$env:LOCALAPPDATA\comfyui-sync.log"

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm')] sync starting" | Add-Content $log

if (-not (Test-Path $src)) {
    "[$(Get-Date -Format 'HH:mm')] ABORT: source $src missing" | Add-Content $log
    exit 1
}
if (-not (Test-Path 'E:\')) {
    "[$(Get-Date -Format 'HH:mm')] SKIP: E: drive offline (it drops sometimes) - will sync next run" | Add-Content $log
    exit 0
}

# exclude churn that doesn't need mirroring
robocopy $src $dst /MIR /COPY:DAT /R:1 /W:1 /MT:8 /NFL /NDL /NP `
    /XD "$src\temp" "$src\output" "$src\user\default\workflows\.tmp" `
    /XF "comfyui_out.log" "comfyui_err.log" | Out-Null
$code = $LASTEXITCODE

if ($code -lt 8) {
    "[$(Get-Date -Format 'HH:mm')] sync OK (robocopy code $code)" | Add-Content $log
    exit 0
} else {
    "[$(Get-Date -Format 'HH:mm')] sync FAILED (robocopy code $code)" | Add-Content $log
    exit 1
}
