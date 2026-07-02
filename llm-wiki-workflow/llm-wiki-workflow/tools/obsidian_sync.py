#!/usr/bin/env python3
"""
obsidian_sync.py — Sync the LLM Wiki to an Obsidian vault.

Copies wiki pages into a subfolder of your Obsidian vault so you can browse
the wiki using Obsidian's graph view, backlinks panel, and quick-switcher.

Destination layout inside the vault:
    <vault>/LLM-Wiki/_Index.md
    <vault>/LLM-Wiki/_Log.md
    <vault>/LLM-Wiki/_Overview.md
    <vault>/LLM-Wiki/Concepts/
    <vault>/LLM-Wiki/Entities/
    <vault>/LLM-Wiki/Sources/
    <vault>/LLM-Wiki/Comparisons/

Obsidian [[wikilinks]] are preserved as-is — they resolve natively in Obsidian
because the target files end up in the same vault.

Usage:
    python tools/obsidian_sync.py --vault "C:/Users/you/Documents/Obsidian Vault"
    python tools/obsidian_sync.py --watch        # re-sync every 5 seconds on change
    python tools/obsidian_sync.py --list-vaults  # auto-detect common vault locations

Set OBSIDIAN_VAULT_PATH in your environment (or .env) to avoid passing --vault every time.

No third-party dependencies required.
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Sync into Atlas/Knowledge/ so Agent Atlas's Obsidian Brain agent indexes it.
# Agent Atlas already writes to Atlas/Sessions/, Atlas/Projects/, Atlas/Profile/.
# This wiki lives alongside those as Atlas/Knowledge/.
SYNC_SUBFOLDER = "Atlas/Knowledge"

STRUCTURAL_MAP = {
    "index.md":    "_Index.md",
    "log.md":      "_Log.md",
    "overview.md": "_Overview.md",
}

FOLDER_MAP = {
    "concepts":    "concepts",
    "entities":    "entities",
    "sources":     "sources",
    "comparisons": "comparisons",
}

# Common Obsidian vault locations to auto-detect
COMMON_VAULT_PATHS = [
    Path.home() / "Documents" / "Obsidian Vault",
    Path.home() / "Obsidian",
    Path("C:/Users") / os.environ.get("USERNAME", "") / "Documents" / "Obsidian Vault",
]


def find_vault(explicit: str) -> Path:
    vault_str = explicit or os.environ.get("OBSIDIAN_VAULT_PATH", "")
    if vault_str:
        vault = Path(vault_str).expanduser().resolve()
        if not vault.exists():
            print(f"error: vault path does not exist: {vault}", file=sys.stderr)
            sys.exit(1)
        return vault
    # Auto-detect
    for candidate in COMMON_VAULT_PATHS:
        if candidate.exists() and candidate.is_dir():
            return candidate
    print(
        "error: could not find Obsidian vault.\n"
        "  Set OBSIDIAN_VAULT_PATH in your environment, or pass --vault PATH.\n"
        "  Run with --list-vaults to see detected locations.",
        file=sys.stderr,
    )
    sys.exit(1)


def list_vaults():
    print("Searching for Obsidian vaults...")
    for candidate in COMMON_VAULT_PATHS:
        status = "✓ found" if candidate.exists() else "✗ not found"
        print(f"  {status}: {candidate}")
    env_val = os.environ.get("OBSIDIAN_VAULT_PATH", "")
    if env_val:
        print(f"\n  OBSIDIAN_VAULT_PATH={env_val}")
    else:
        print("\n  OBSIDIAN_VAULT_PATH not set in environment.")


def sync_wiki(vault: Path, verbose: bool = True) -> int:
    """Copy wiki pages into the vault subfolder. Returns count of synced files."""
    wiki_dir = ROOT / "wiki"
    dest_root = vault / SYNC_SUBFOLDER
    dest_root.mkdir(exist_ok=True)
    synced = 0

    # Structural files: index.md → _Index.md etc.
    for src_name, dest_name in STRUCTURAL_MAP.items():
        src = wiki_dir / src_name
        if src.exists():
            dest = dest_root / dest_name
            shutil.copy2(src, dest)
            if verbose:
                print(f"  synced {src_name} -> {SYNC_SUBFOLDER}/{dest_name}")
            synced += 1

    # Content subfolders
    for src_folder, dest_folder in FOLDER_MAP.items():
        src_dir = wiki_dir / src_folder
        if not src_dir.exists():
            continue
        dest_dir = dest_root / dest_folder
        dest_dir.mkdir(exist_ok=True)
        for md in sorted(src_dir.rglob("*.md")):
            rel = md.relative_to(src_dir)
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(md, dest)
            if verbose:
                print(f"  synced wiki/{src_folder}/{rel} -> {SYNC_SUBFOLDER}/{dest_folder}/{rel}")
            synced += 1

    return synced


def _wiki_mtimes() -> dict[str, float]:
    wiki_dir = ROOT / "wiki"
    return {
        str(f.relative_to(wiki_dir)): f.stat().st_mtime
        for f in wiki_dir.rglob("*.md")
        if f.is_file()
    }


def main():
    parser = argparse.ArgumentParser(description="Sync LLM Wiki to Obsidian vault")
    parser.add_argument("--vault", default="", help="Path to Obsidian vault directory")
    parser.add_argument("--watch", action="store_true",
                        help="Keep running, re-sync whenever wiki files change")
    parser.add_argument("--interval", type=int, default=5,
                        help="Watch polling interval in seconds (default: 5)")
    parser.add_argument("--list-vaults", action="store_true",
                        help="Show auto-detected vault locations and exit")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress per-file output")
    args = parser.parse_args()

    if args.list_vaults:
        list_vaults()
        return

    vault = find_vault(args.vault)
    print(f"Syncing to: {vault / SYNC_SUBFOLDER}")

    n = sync_wiki(vault, verbose=not args.quiet)
    print(f"Done: {n} file(s) synced.")

    if args.watch:
        print(f"\nWatching for changes every {args.interval}s... Ctrl+C to stop.")
        last_mtimes = _wiki_mtimes()
        try:
            while True:
                time.sleep(args.interval)
                current = _wiki_mtimes()
                all_keys = set(current) | set(last_mtimes)
                if any(current.get(k) != last_mtimes.get(k) for k in all_keys):
                    ts = time.strftime("%H:%M:%S")
                    print(f"\n[{ts}] Changes detected, syncing…")
                    n = sync_wiki(vault, verbose=not args.quiet)
                    print(f"Synced {n} file(s).")
                    last_mtimes = current
        except KeyboardInterrupt:
            print("\nWatcher stopped.")


if __name__ == "__main__":
    main()
