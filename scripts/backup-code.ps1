# Code backup protocol (established 2026-07-09 after olympus/ was lost in a
# Windows reinstall - it had never been pushed anywhere).
#
# NOTE: keep this file pure ASCII. PowerShell 5.1 reads BOM-less files as
# ANSI, and UTF-8 punctuation (em-dashes etc.) decodes into curly quotes
# that silently corrupt string parsing.
#
# Does three things:
#   1. Commits everything and pushes to GitHub
#   2. Zips the tracked source (git archive - respects .gitignore) into the
#      Obsidian vault on C:
#   3. Copies that zip to the E: backup folder (skipped if E: is missing -
#      that drive drops offline sometimes)
#
# Run after completing any piece of code:
#   powershell -ExecutionPolicy Bypass -File scripts\backup-code.ps1

$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

# Resolve git explicitly - PowerShell's PATH may not have it (scheduled tasks).
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $gitExe = 'C:\Program Files\Git\cmd\git.exe'
    if (-not (Test-Path $gitExe)) { Write-Error "git not found"; exit 1 }
    Set-Alias -Name git -Value $gitExe -Scope Script
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$name = "my-local-ai-stack-$stamp.zip"
$vaultDir = 'C:\Users\amire\Documents\Obsidian Vault\Projects\Code Backups'
$eDir = 'E:\Backups\code-snapshots'

# 1. git commit + push
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Snapshot $stamp (backup-code protocol)"
}
git push origin master
if ($LASTEXITCODE -ne 0) { Write-Warning "git push failed - check network/credentials. Snapshots still proceed." }

# 2. zip tracked source into the vault on C:
New-Item -ItemType Directory -Force $vaultDir | Out-Null
$zip = Join-Path $vaultDir $name
git archive --format=zip -o "$zip" HEAD
if (Test-Path $zip) { Write-Host "[ok] vault snapshot: $zip" }
else { Write-Warning "vault snapshot FAILED: $zip was not created" }

# 3. copy to E: backup (best effort)
if ((Test-Path 'E:\') -and (Test-Path $zip)) {
    New-Item -ItemType Directory -Force $eDir | Out-Null
    Copy-Item $zip $eDir
    Write-Host "[ok] E: snapshot:    $eDir\$name"
} else {
    Write-Warning "E: snapshot skipped (drive offline or zip missing). Re-run when it's back."
}

# keep only the 10 newest snapshots in each location
foreach ($d in @($vaultDir, $eDir)) {
    if (Test-Path $d) {
        Get-ChildItem $d -Filter 'my-local-ai-stack-*.zip' | Sort-Object Name -Descending |
            Select-Object -Skip 10 | Remove-Item -Force -Confirm:$false
    }
}
Write-Output "[ok] backup protocol complete"
