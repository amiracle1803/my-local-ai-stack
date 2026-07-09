# Olympus watchdog — restarts the kernel if /api/health stops answering.
# Run in a spare terminal:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
$kernelDir = $PSScriptRoot
$logFile = Join-Path $kernelDir 'data\watchdog.log'

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

Write-Log "watchdog started"
while ($true) {
    $ok = $false
    try {
        $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:4600/api/health' -TimeoutSec 5
        if ($resp.status -eq 'ok') { $ok = $true }
    } catch {}

    if (-not $ok) {
        Write-Log "health check FAILED - (re)starting kernel"
        Start-Process -FilePath (Join-Path $kernelDir 'run.bat') -WorkingDirectory $kernelDir -WindowStyle Minimized
        Start-Sleep -Seconds 15
    }
    Start-Sleep -Seconds 30
}
