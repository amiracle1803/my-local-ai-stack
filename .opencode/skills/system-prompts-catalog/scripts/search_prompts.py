#!/usr/bin/env python3
"""Search the system prompts catalog with context and ranking.

Usage:
    python search_prompts.py "prompt injection" --context 3
    python search_prompts.py --provider anthropic --topic safety
    python search_prompts.py --list-providers
"""
import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4] / "tools-external" / "skills-audit" / "system_prompts_leaks"


def search(query: str, context: int = 2, max_results: int = 20) -> list[dict]:
    """Search all .md files for a query string, return matches with context."""
    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for md_file in REPO.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        try:
            lines = md_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines):
            if pattern.search(line):
                start = max(0, i - context)
                end = min(len(lines), i + context + 1)
                snippet = "\n".join(lines[start:end])
                rel_path = md_file.relative_to(REPO)
                provider = rel_path.parts[0] if len(rel_path.parts) > 1 else "root"
                results.append({
                    "file": str(rel_path),
                    "provider": provider,
                    "line": i + 1,
                    "match": line.strip(),
                    "snippet": snippet,
                })
                if len(results) >= max_results:
                    return results

    return results


def list_providers() -> dict[str, int]:
    """List all providers and their prompt counts."""
    counts = {}
    for md_file in REPO.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        rel = md_file.relative_to(REPO)
        provider = rel.parts[0] if len(rel.parts) > 1 else "root"
        counts[provider] = counts.get(provider, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def filter_by_provider(provider: str) -> list[str]:
    """List all files for a given provider (case-insensitive match)."""
    # Case-insensitive lookup
    provider_dir = REPO / provider
    if not provider_dir.exists():
        for d in REPO.iterdir():
            if d.is_dir() and d.name.lower() == provider.lower():
                provider_dir = d
                break
    if not provider_dir.exists():
        return []
    return [str(f.relative_to(REPO)) for f in provider_dir.rglob("*.md") if f.name != "README.md"]


def main():
    parser = argparse.ArgumentParser(description="Search system prompts catalog")
    parser.add_argument("query", nargs="?", help="Search string")
    parser.add_argument("--context", "-c", type=int, default=2, help="Lines of context (default: 2)")
    parser.add_argument("--max-results", "-n", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--provider", "-p", help="Filter by provider name")
    parser.add_argument("--topic", "-t", help="Filter by topic keyword in filename")
    parser.add_argument("--list-providers", "-l", action="store_true", help="List all providers")
    args = parser.parse_args()

    if args.list_providers:
        providers = list_providers()
        print(f"{'Provider':<20} {'Prompts':>8}")
        print("-" * 30)
        for p, c in providers.items():
            print(f"{p:<20} {c:>8}")
        return

    if args.provider:
        files = filter_by_provider(args.provider)
        print(f"\nFiles for {args.provider} ({len(files)} prompts):\n")
        for f in files:
            print(f"  {f}")
        return

    if not args.query:
        parser.print_help()
        return

    results = search(args.query, args.context, args.max_results)

    if not results:
        print(f"No matches for '{args.query}'")
        return

    print(f"\n{len(results)} matches for '{args.query}':\n")
    for r in results:
        print(f"  {r['file']}:{r['line']}")
        print(f"  {r['snippet']}")
        print()


if __name__ == "__main__":
    main()
