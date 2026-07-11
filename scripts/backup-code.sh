#!/bin/bash
set -u

# Code backup protocol (established 2026-07-09 after olympus/ was lost in a
# Windows reinstall - it had never been pushed anywhere).
#
# Does three things:
#   1. Commits everything and pushes to GitHub
#   2. Zips the tracked source (git archive - respects .gitignore) into the
#      Obsidian vault on the SSD
#   3. Copies that zip to the SSD backup folder (skipped if the mount is missing -
#      that drive drops offline sometimes)
#
# Run after completing any piece of code:
#   bash scripts/backup-code.sh
#   bash scripts/backup-code.sh "custom commit message"

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"

# Timestamp in YYYY-MM-dd_HHMM format
stamp=$(date +%Y-%m-%d_%H%M)
name="my-local-ai-stack-$stamp.zip"
vault_dir="/run/media/amirel/Amir1tb SSD/Obsidian Vault/Projects/Code Backups"
backup_dir="/run/media/amirel/Amir1tb SSD/Backups/code-snapshots"
ssd_mount="/run/media/amirel/Amir1tb SSD"

# Message argument (default: "backup: <date>")
msg="${1:-backup: $stamp}"

# 1. git commit + push
git add -A
if ! git diff --cached --quiet; then
    git commit -m "$msg"
    if [ $? -ne 0 ]; then
        echo "[X] git commit failed"
        exit 1
    fi
fi

git push origin master
if [ $? -ne 0 ]; then
    echo "[skip] git push failed - check network/credentials. Snapshots still proceed."
fi

# 2. zip tracked source into the vault
mkdir -p "$vault_dir"
zip="$vault_dir/$name"
git archive --format=zip -o "$zip" HEAD
if [ -f "$zip" ]; then
    echo "[ok] vault snapshot: $zip"
else
    echo "[X] vault snapshot FAILED: $zip was not created"
    exit 1
fi

# 3. copy to backup (best effort)
if [ -d "$ssd_mount" ] && [ -f "$zip" ]; then
    mkdir -p "$backup_dir"
    cp "$zip" "$backup_dir/"
    echo "[ok] backup snapshot:    $backup_dir/$name"
else
    if [ ! -d "$ssd_mount" ]; then
        echo "[skip] SSD mount not found. Re-run when it's back."
    fi
fi

# keep only the 10 newest snapshots in each location
for dir in "$vault_dir" "$backup_dir"; do
    if [ -d "$dir" ]; then
        ls -1 "$dir"/my-local-ai-stack-*.zip 2>/dev/null | sort -r | tail -n +11 | xargs -r rm -f
    fi
done

echo "[ok] backup protocol complete"
