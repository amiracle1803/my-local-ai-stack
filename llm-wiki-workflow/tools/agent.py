#!/usr/bin/env python3
"""
agent.py - LLM-powered agent for the LLM Wiki workflow.

Complements tools/wiki.py (which handles mechanical bookkeeping) by
driving the AI parts: reading raw sources, writing wiki content, and
running AI-level lint analysis.

Commands:
    ingest <raw-path>           Process a raw file into wiki pages
    query  "<question>"         Answer a question from the wiki
    lint                        Run wiki.py lint + AI health analysis

Configuration (environment variables):
    ANTHROPIC_API_KEY   Required. Your Anthropic API key.
    WIKI_MODEL          Optional. Claude model to use (default: claude-sonnet-4-6).
    WIKI_ROOT           Optional. Override wiki project root detection.

No third-party dependencies. Python 3.8+. Uses urllib for API calls.

File output protocol:
    The agent asks the LLM to return new/updated files in a delimited format:

        ===FILE: wiki/path/to/page.md===
        [full file content]
        ===ENDFILE===

    The agent parses these blocks and writes them to disk, restricted to
    wiki/, wiki/index.md, and wiki/log.md. Raw files are never touched.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-6"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_TOKENS = 8192

FILE_BLOCK_RE = re.compile(
    r"===FILE:\s*([^\n=]+?)\s*===\n(.*?)===ENDFILE===",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_root(explicit=None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not (root / "wiki").is_dir():
            sys.exit(f"error: --root {root} has no wiki/ directory")
        return root
    here = Path.cwd().resolve()
    for cand in [here, *here.parents]:
        if (cand / "wiki").is_dir():
            return cand
    sys.exit("error: not inside a wiki project (no wiki/ directory found).")


def read_file_safe(path: Path, max_chars: int = 60_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[...truncated at {max_chars} chars...]"
        return text
    except Exception as e:
        return f"[could not read {path}: {e}]"


def call_claude(system: str, user: str, model: str, api_key: str) -> str:
    payload = json.dumps({
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["content"][0]["text"]
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        sys.exit(f"API error {e.code}: {msg}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")


def apply_file_blocks(response: str, root: Path) -> list:
    """Parse ===FILE: path=== blocks from the LLM response and write them."""
    written = []
    for m in FILE_BLOCK_RE.finditer(response):
        rel = m.group(1).strip()
        content = m.group(2)

        # Safety: only allow writes inside wiki/ (includes index.md, log.md)
        dest = (root / rel).resolve()
        wiki_root = (root / "wiki").resolve()
        if not str(dest).startswith(str(wiki_root)):
            print(f"  [SKIP] refusing to write outside wiki/: {rel}")
            continue
        if not dest.suffix == ".md":
            print(f"  [SKIP] refusing to write non-markdown file: {rel}")
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel)
        print(f"  [WRITE] {rel}")
    return written


def run_wiki_tool(*args, root: Path) -> str:
    """Run tools/wiki.py with given args, return stdout."""
    script = root / "tools" / "wiki.py"
    result = subprocess.run(
        [sys.executable, str(script), *args, "--root", str(root)],
        capture_output=True,
        text=True,
    )
    return (result.stdout + result.stderr).strip()


def build_system_prompt(root: Path) -> str:
    schema_path = root / "CLAUDE.md"
    schema = read_file_safe(schema_path) if schema_path.exists() else "(CLAUDE.md not found)"
    return f"""You are the wiki maintainer for this LLM Wiki project.

Your operating schema (CLAUDE.md):

{schema}

OUTPUT FORMAT FOR FILE WRITES:
When you need to create or update wiki files, output each file using this exact format:

===FILE: wiki/path/to/page.md===
[full file content including frontmatter]
===ENDFILE===

You may output multiple FILE blocks in one response.
CRITICAL RULES:
- Only write files under wiki/ (wiki/concepts/, wiki/entities/, wiki/sources/, wiki/comparisons/, wiki/index.md, wiki/log.md, wiki/overview.md)
- Never write to raw/ or any other directory
- Always include valid YAML frontmatter on every wiki page
- Today's date is {__import__('datetime').date.today().isoformat()}
"""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_ingest(args):
    root = find_root(args.root)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("error: ANTHROPIC_API_KEY environment variable not set.")
    model = os.environ.get("WIKI_MODEL", DEFAULT_MODEL)

    raw_path = Path(args.path)
    if not raw_path.is_absolute():
        raw_path = (root / raw_path).resolve()
    if not raw_path.exists():
        sys.exit(f"error: source file not found: {raw_path}")

    # Verify it lives under raw/
    raw_dir = (root / "raw").resolve()
    if not str(raw_path).startswith(str(raw_dir)):
        sys.exit(f"error: path must be under raw/: {args.path}")

    rel_raw = raw_path.relative_to(root).as_posix()
    print(f"Reading {rel_raw} ...")
    source_text = read_file_safe(raw_path)

    index_text = read_file_safe(root / "wiki" / "index.md")
    log_tail = _tail_log(root)

    system = build_system_prompt(root)
    user = f"""Ingest this source file following the ingest workflow in CLAUDE.md.

Source file path: {rel_raw}

Current wiki index:
{index_text}

Recent activity log:
{log_tail}

Source file content:
---
{source_text}
---

Steps to perform:
1. Read the source carefully.
2. Create a source summary page in wiki/sources/ with: concise summary, key claims/results, notable data points.
3. Identify affected concepts and entities. Create or update pages as needed in wiki/concepts/ and wiki/entities/.
4. Output an updated wiki/index.md that includes all new pages.
5. Append a new entry to wiki/log.md for this ingest.

Output all files using the ===FILE: path=== ... ===ENDFILE=== format.
After the file blocks, write a brief plain-text summary of what was created/updated.
"""

    print("Calling Claude API ...")
    response = call_claude(system, user, model, api_key)

    print("\nApplying file writes:")
    written = apply_file_blocks(response, root)

    # Rebuild index deterministically after LLM writes
    print("\nRebuilding index ...")
    print(run_wiki_tool("index", root=root))

    # Log the ingest
    run_wiki_tool("log", "ingest", rel_raw, "--note", f"agent ingest via agent.py", root=root)

    print("\n--- Summary ---")
    # Print everything after the last ===ENDFILE===
    summary_start = response.rfind("===ENDFILE===")
    if summary_start != -1:
        print(response[summary_start + len("===ENDFILE==="):].strip())
    else:
        print(f"Files written: {written}")


def cmd_query(args):
    root = find_root(args.root)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("error: ANTHROPIC_API_KEY environment variable not set.")
    model = os.environ.get("WIKI_MODEL", DEFAULT_MODEL)

    index_text = read_file_safe(root / "wiki" / "index.md")
    system = build_system_prompt(root)

    # First pass: identify relevant pages
    user_scan = f"""I need to answer this question: {args.question}

Current wiki index:
{index_text}

List the wiki page paths (e.g. wiki/concepts/x.md) most relevant to this question.
Output only a JSON array of paths, nothing else. Example: ["wiki/concepts/a.md","wiki/sources/b.md"]
"""
    print("Identifying relevant pages ...")
    pages_json = call_claude(system, user_scan, model, api_key)
    try:
        start = pages_json.index("[")
        end = pages_json.rindex("]") + 1
        page_paths = json.loads(pages_json[start:end])
    except (ValueError, json.JSONDecodeError):
        page_paths = []

    # Read those pages
    pages_content = ""
    for p in page_paths[:8]:  # cap at 8 pages to stay within context
        full = (root / p).resolve()
        if full.exists():
            pages_content += f"\n\n--- {p} ---\n{read_file_safe(full)}"

    # Second pass: synthesize answer
    save_instruction = (
        "\n\nAfter your answer, output the synthesis as a new wiki page using "
        "===FILE: wiki/comparisons/<slug>.md=== ... ===ENDFILE=== format."
        if args.save else ""
    )
    user_answer = f"""Answer this question using the wiki pages below.
{save_instruction}

Question: {args.question}

Relevant wiki pages:
{pages_content if pages_content else "(no specific pages found — use general wiki knowledge)"}
"""
    print("Synthesizing answer ...")
    response = call_claude(system, user_answer, model, api_key)
    print("\n" + response)

    if args.save:
        written = apply_file_blocks(response, root)
        if written:
            run_wiki_tool("index", root=root)
            run_wiki_tool("log", "query", args.question[:60],
                          "--note", f"saved as {written[0]}", root=root)


def cmd_lint(args):
    root = find_root(args.root)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("error: ANTHROPIC_API_KEY environment variable not set.")
    model = os.environ.get("WIKI_MODEL", DEFAULT_MODEL)

    print("Running mechanical lint (wiki.py lint) ...")
    lint_output = run_wiki_tool("lint", root=root)
    print(lint_output)

    # Sample page bodies for AI analysis (capped to save tokens)
    index_text = read_file_safe(root / "wiki" / "index.md")
    log_text = _tail_log(root, lines=30)

    system = build_system_prompt(root)
    user = f"""Perform an AI-level health check on this wiki, beyond what the mechanical linter can detect.

Mechanical lint output:
{lint_output}

Wiki index:
{index_text}

Recent log:
{log_text}

Please report:
1. CONTRADICTIONS — pages making conflicting claims (list page paths + short note on conflict)
2. MISSING PAGES — recurring concepts/entities mentioned many times but with no dedicated page (propose with one-line description)
3. NEXT QUESTIONS / SOURCES — based on gaps, suggest 3-5 specific questions to ask or source types to ingest next
4. OVERALL HEALTH — one-paragraph summary

Be concise and specific. Use actual page names from the index.
"""
    print("\n--- AI Health Analysis ---")
    response = call_claude(system, user, model, api_key)
    print(response)

    # Log the lint pass
    run_wiki_tool("log", "lint", "AI health check",
                  "--note", "ran agent.py lint", root=root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tail_log(root: Path, lines: int = 15) -> str:
    log = root / "wiki" / "log.md"
    if not log.exists():
        return "(no log yet)"
    text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="agent",
        description="LLM-powered agent for the wiki workflow (requires ANTHROPIC_API_KEY)",
    )
    p.add_argument("--root", help="wiki project root (default: auto-detect)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ingest", help="process a raw file into wiki pages")
    sp.add_argument("path", help="path to raw file (e.g. raw/articles/foo.md)")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("query", help="answer a question from the wiki")
    sp.add_argument("question", help="the question to ask")
    sp.add_argument("--save", action="store_true",
                    help="file the answer as a new wiki/comparisons/ page")
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("lint", help="mechanical + AI health check")
    sp.set_defaults(func=cmd_lint)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
