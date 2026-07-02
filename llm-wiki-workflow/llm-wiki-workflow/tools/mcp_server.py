#!/usr/bin/env python3
"""
mcp_server.py — MCP (Model Context Protocol) server for the LLM Wiki.

Exposes wiki tools to Claude Code, Claude Desktop, Cursor, and any other
MCP-compatible client. Runs as a stdio process — no HTTP server needed.

Claude Code picks this up automatically from .mcp.json in the project root.

Manual test:
    python tools/mcp_server.py  (then type JSON-RPC messages, Ctrl+C to stop)

Requires: pip install mcp  (or: pip install -r requirements.txt)

Exposed tools:
    wiki_search      — keyword search across all wiki pages
    wiki_list_pages  — return wiki/index.md (the master catalog)
    wiki_get_page    — read a specific wiki page
    wiki_get_raw     — read a raw source file
    wiki_new_page    — create a page with correct frontmatter
    wiki_index       — rebuild wiki/index.md
    wiki_lint        — full wiki health check
    wiki_log         — append entry to wiki/log.md
    wiki_stats       — page counts, raw source counts, last log entries
    wiki_list_raw    — list all files in raw/
    wiki_ingest      — LLM-powered ingest via agent.py (needs ANTHROPIC_API_KEY)
    wiki_query       — LLM-powered query via agent.py (needs ANTHROPIC_API_KEY)
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "error: mcp package not installed.\n"
        "  pip install mcp\n"
        "or:\n"
        "  pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

mcp = FastMCP(
    "LLM Wiki",
    instructions=(
        "Tools for maintaining a Karpathy-style LLM wiki. "
        "The wiki lives at wiki/ and raw sources at raw/. "
        "Use wiki_search or wiki_list_pages to navigate, "
        "wiki_get_page to read, wiki_new_page to create, "
        "wiki_ingest for LLM-powered source ingestion, "
        "and wiki_lint for a full health check."
    ),
)

WIKI_PY = ROOT / "tools" / "wiki.py"
AGENT_PY = ROOT / "tools" / "agent.py"


def _run_wiki(*args) -> str:
    result = subprocess.run(
        [sys.executable, str(WIKI_PY)] + list(args),
        capture_output=True, text=True, cwd=str(ROOT),
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    if err and not out:
        return f"[stderr] {err}"
    if err:
        return f"{out}\n[stderr] {err}"
    return out or "(no output)"


def _run_agent(*args) -> str:
    result = subprocess.run(
        [sys.executable, str(AGENT_PY)] + list(args),
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


# ── Read tools ────────────────────────────────────────────────────────────────

@mcp.tool()
def wiki_search(query: str) -> str:
    """Search the wiki for pages matching a keyword or topic.

    Args:
        query: Keyword or phrase to search for across all wiki pages.
    """
    return _run_wiki("search", query)


@mcp.tool()
def wiki_list_pages() -> str:
    """List all wiki pages with titles and one-line summaries.

    Returns the content of wiki/index.md — the auto-generated master catalog.
    Run wiki_index() first if the catalog seems out of date.
    """
    index = ROOT / "wiki" / "index.md"
    if not index.exists():
        return "wiki/index.md not found. Run wiki_index() to generate it."
    return index.read_text(encoding="utf-8")


@mcp.tool()
def wiki_get_page(path: str) -> str:
    """Read the full content of a wiki page.

    Args:
        path: Wiki-relative path, e.g. 'concepts/llm-wiki-workflow.md'
              or full repo path 'wiki/concepts/llm-wiki-workflow.md'.
    """
    p = path.lstrip("/")
    if not p.startswith("wiki/"):
        p = f"wiki/{p}"
    full = ROOT / p
    if not full.exists():
        return (
            f"Page not found: {path}\n"
            "Run wiki_list_pages() to see available pages."
        )
    return full.read_text(encoding="utf-8")


@mcp.tool()
def wiki_get_raw(path: str) -> str:
    """Read the content of a raw source file (immutable — never modify these).

    Args:
        path: Path under raw/, e.g. 'raw/articles/my-article.md'
    """
    p = path.lstrip("/")
    if not p.startswith("raw/"):
        p = f"raw/{p}"
    full = ROOT / p
    if not full.exists():
        raw_dir = ROOT / "raw"
        files = sorted(
            str(f.relative_to(ROOT))
            for f in raw_dir.rglob("*")
            if f.is_file() and f.name != ".gitkeep"
        )
        available = "\n".join(files[:30]) if files else "(no files in raw/)"
        return f"Raw file not found: {path}\n\nAvailable raw files:\n{available}"
    content = full.read_text(encoding="utf-8", errors="replace")
    if len(content) > 15000:
        content = content[:15000] + f"\n\n...[truncated — full size {len(content)} chars]"
    return content


@mcp.tool()
def wiki_list_raw() -> str:
    """List all files in raw/ organized by subdirectory.

    These are your immutable source documents — drop files here to ingest them.
    """
    raw_dir = ROOT / "raw"
    if not raw_dir.exists():
        return "raw/ directory not found."
    lines = ["Raw sources (add files here, then call wiki_ingest):"]
    for subdir in sorted(raw_dir.iterdir()):
        if not subdir.is_dir():
            continue
        files = sorted(f.name for f in subdir.iterdir() if f.is_file() and f.name != ".gitkeep")
        if files:
            lines.append(f"\nraw/{subdir.name}/")
            for f in files:
                lines.append(f"  {f}")
        else:
            lines.append(f"\nraw/{subdir.name}/  (empty)")
    if len(lines) == 1:
        lines.append("  (all subdirectories are empty)")
    return "\n".join(lines)


@mcp.tool()
def wiki_stats() -> str:
    """Return a summary of wiki statistics.

    Shows page counts by type, raw source counts, and last log entries.
    """
    lines = []
    wiki_dir = ROOT / "wiki"
    by_type: dict[str, int] = {}
    total = 0
    structural = {"index.md", "log.md", "overview.md"}
    for md in wiki_dir.rglob("*.md"):
        if md.name in structural and md.parent == wiki_dir:
            continue
        total += 1
        try:
            for line in md.read_text(encoding="utf-8").splitlines()[1:20]:
                if line.startswith("type:"):
                    t = line.split(":", 1)[1].strip()
                    by_type[t] = by_type.get(t, 0) + 1
                    break
        except Exception:
            pass

    lines.append(f"Wiki pages: {total} total")
    for t, n in sorted(by_type.items()):
        lines.append(f"  {t}: {n}")

    raw_dir = ROOT / "raw"
    raw_count = sum(1 for f in raw_dir.rglob("*") if f.is_file() and f.name != ".gitkeep")
    lines.append(f"\nRaw sources: {raw_count} files")
    for subdir in sorted(raw_dir.iterdir()):
        if subdir.is_dir():
            n = sum(1 for f in subdir.rglob("*") if f.is_file() and f.name != ".gitkeep")
            if n:
                lines.append(f"  raw/{subdir.name}/: {n}")

    log = ROOT / "wiki" / "log.md"
    if log.exists():
        log_lines = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        last = log_lines[-6:] if len(log_lines) > 6 else log_lines[1:]
        if last:
            lines.append("\nLast log entries:")
            for l in last:
                lines.append(f"  {l}")

    return "\n".join(lines)


# ── Write / maintenance tools ─────────────────────────────────────────────────

@mcp.tool()
def wiki_new_page(kind: str, slug: str, title: str) -> str:
    """Create a new wiki page with correct YAML frontmatter.

    Args:
        kind: Page type — one of: concept, entity, source, comparison
        slug: URL-friendly identifier, e.g. 'attention-mechanism'
        title: Human-readable title, e.g. 'Attention Mechanism'
    """
    valid = ("concept", "entity", "source", "comparison")
    if kind not in valid:
        return f"Invalid kind '{kind}'. Must be one of: {', '.join(valid)}"
    return _run_wiki("new", kind, slug, "--title", title)


@mcp.tool()
def wiki_index() -> str:
    """Rebuild wiki/index.md from all page frontmatter.

    Run this after creating or editing pages to keep the catalog current.
    This is also run automatically after wiki_ingest().
    """
    return _run_wiki("index")


@mcp.tool()
def wiki_lint() -> str:
    """Run a full health check on the wiki.

    Checks:
    - YAML frontmatter schema on every page
    - Broken [[wikilinks]] and related: references
    - Sources: paths that don't exist under raw/
    - Orphan pages (no inbound links)
    - Stale pages (not updated in 90+ days)
    - Nearly-empty page bodies

    Returns [ERROR] and [WARN] prefixed lines.
    """
    return _run_wiki("lint")


@mcp.tool()
def wiki_log(action: str, title: str, note: str = "") -> str:
    """Append a timestamped entry to wiki/log.md.

    Args:
        action: One of: ingest, query, lint, note
        title: Short title for the log entry
        note: Optional detail (may be empty)
    """
    args = ["log", action, title]
    if note:
        args += ["--note", note]
    return _run_wiki(*args)


# ── LLM-powered tools (require ANTHROPIC_API_KEY) ─────────────────────────────

@mcp.tool()
def wiki_ingest(raw_path: str) -> str:
    """Ingest a raw source file into the wiki using Claude.

    Reads the file, creates a source summary, updates all affected concept
    and entity pages, rebuilds the index, and logs the action.

    Requires: ANTHROPIC_API_KEY environment variable.

    Args:
        raw_path: Path to the raw file, e.g. 'raw/articles/my-article.md'
    """
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return (
            "ANTHROPIC_API_KEY not set.\n"
            "Set it in your environment or .env file, then retry.\n\n"
            "Alternatively, perform the ingest manually by:\n"
            "1. Reading the raw file with wiki_get_raw()\n"
            "2. Creating pages with wiki_new_page() and editing them\n"
            "3. Running wiki_index() and wiki_log()"
        )
    return _run_agent("ingest", raw_path)


@mcp.tool()
def wiki_query(question: str, save: bool = False) -> str:
    """Answer a question by reading the wiki, optionally saving the answer as a page.

    Reads wiki/index.md, identifies relevant pages, reads them, and synthesizes
    an answer. If save=True, files the answer as a new wiki/comparisons/ page.

    Requires: ANTHROPIC_API_KEY environment variable.

    Args:
        question: The question to answer from the wiki.
        save: If True, save the synthesized answer as a new wiki page.
    """
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return (
            "ANTHROPIC_API_KEY not set.\n"
            "Set it in your environment or .env file, then retry.\n\n"
            "Alternatively, use wiki_list_pages() and wiki_get_page() "
            "to read relevant pages and answer the question yourself."
        )
    args = ["query", question]
    if save:
        args.append("--save")
    return _run_agent(*args)


# ── Agent Atlas bridge tools ───────────────────────────────────────────────────

import json as _json
import os as _os
import urllib.request as _urlreq
import urllib.error as _urlerr

_ATLAS_URL = _os.environ.get("ATLAS_URL", "http://localhost:8000").rstrip("/")
BRIDGE_PY = ROOT / "tools" / "atlas_bridge.py"


def _atlas_get(path: str) -> tuple[bool, object]:
    try:
        with _urlreq.urlopen(f"{_ATLAS_URL}{path}", timeout=5) as r:
            return True, _json.loads(r.read())
    except _urlerr.URLError:
        return False, None
    except Exception as e:
        return False, str(e)


def _run_bridge(*args) -> str:
    result = subprocess.run(
        [sys.executable, str(BRIDGE_PY)] + list(args),
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


@mcp.tool()
def atlas_status() -> str:
    """Check whether Agent Atlas is running and return a system snapshot.

    Returns the API health, version, list of 18 agents, and recent job counts.
    Agent Atlas must be running on localhost:8000 (start via start.bat).
    """
    ok, data = _atlas_get("/api/health")
    if not ok:
        return (
            "Agent Atlas is OFFLINE (localhost:8000 not responding).\n\n"
            "Start it with:  start.bat\n"
            "Or navigate to the Agent Atlas folder and run its start.bat.\n\n"
            "CLI check:  atlas-bridge status"
        )
    lines = ["Agent Atlas is ONLINE"]
    if isinstance(data, dict):
        for k, v in data.items():
            lines.append(f"  {k}: {v}")
    ok2, agents = _atlas_get("/api/agents/")
    if ok2:
        agent_list = agents if isinstance(agents, list) else agents.get("agents", [])
        lines.append(f"\nAgents registered: {len(agent_list)}")
        for a in agent_list[:6]:
            lines.append(f"  [{a.get('layer','?')}] {a.get('id','?')} — {a.get('display_name','')}")
        if len(agent_list) > 6:
            lines.append(f"  ... and {len(agent_list) - 6} more")
    ok3, jobs = _atlas_get("/api/jobs/")
    if ok3:
        jlist = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
        running = sum(1 for j in jlist if j.get("status") == "running")
        queued  = sum(1 for j in jlist if j.get("status") == "queued")
        lines.append(f"\nJobs: {len(jlist)} total, {running} running, {queued} queued")
    return "\n".join(lines)


@mcp.tool()
def atlas_run(goal: str, run_mode: str = "sync", risk_level: str = "low") -> str:
    """Submit a task to Agent Atlas for execution.

    The Orchestrator agent receives the goal and delegates to specialist agents.

    Args:
        goal: Natural-language description of the task, e.g. 'Summarize my sessions from last week'
        run_mode: 'sync' (wait for result) or 'background' (return job_id immediately)
        risk_level: 'low', 'medium', or 'high' — checked by the Guardian policy engine
    """
    payload = _json.dumps({
        "goal": goal,
        "run_mode": run_mode,
        "risk_level": risk_level,
        "context": {},
    }).encode()
    req = _urlreq.Request(
        f"{_ATLAS_URL}/api/run", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with _urlreq.urlopen(req, timeout=90) as r:
            result = _json.loads(r.read())
        if "job_id" in result:
            return f"Job submitted: {result['job_id']}\n\n{result.get('response', '(queued for background processing)')}"
        return _json.dumps(result, indent=2)
    except _urlerr.URLError:
        return (
            "Agent Atlas is OFFLINE — cannot submit task.\n"
            "Start it via start.bat, then retry."
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def atlas_jobs(limit: int = 20) -> str:
    """List recent Agent Atlas jobs with status, type, and timing.

    Args:
        limit: Maximum number of jobs to return (default 20)
    """
    ok, data = _atlas_get(f"/api/jobs/?limit={limit}")
    if not ok:
        return "Agent Atlas is OFFLINE."
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    if not jobs:
        return "No jobs found."
    lines = [f"Recent jobs ({len(jobs)} returned):"]
    STATUS_ICONS = {"done": "[DONE]", "running": "[RUN ]", "failed": "[FAIL]",
                    "queued": "[WAIT]", "paused": "[PAUS]"}
    for j in jobs:
        icon = STATUS_ICONS.get(j.get("status", "?"), "[?]")
        jid  = (j.get("id") or "")[:12]
        ts   = (j.get("created_at") or "")[:16]
        title = j.get("title") or j.get("type", "?")
        lines.append(f"  {icon}  {jid}  {ts}  {title}")
    return "\n".join(lines)


@mcp.tool()
def atlas_search(query: str) -> str:
    """Search Obsidian via Agent Atlas's Retrieval Agent.

    Searches the shared Obsidian vault (including Atlas/Knowledge/ wiki pages).

    Args:
        query: Natural-language search query
    """
    payload = _json.dumps({"query": query, "top_k": 10}).encode()
    req = _urlreq.Request(
        f"{_ATLAS_URL}/api/obsidian/search", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with _urlreq.urlopen(req, timeout=15) as r:
            results = _json.loads(r.read())
        if isinstance(results, list):
            if not results:
                return f"No results found for: {query}"
            lines = [f"Search results for '{query}':"]
            for i, r in enumerate(results[:10], 1):
                title = r.get("title") or r.get("path", "?")
                score = r.get("score", "")
                snippet = (r.get("snippet") or r.get("content", ""))[:120]
                lines.append(f"\n{i}. {title}" + (f" (score: {score:.2f})" if score else ""))
                if snippet:
                    lines.append(f"   {snippet}...")
            return "\n".join(lines)
        return _json.dumps(results, indent=2)
    except _urlerr.URLError:
        return (
            "Agent Atlas is OFFLINE — cannot search.\n"
            "Alternative: use wiki_search() to search the local wiki only."
        )
    except Exception as e:
        return f"Search error: {e}\n\nAlternative: wiki_search('{query}') for local wiki search."


if __name__ == "__main__":
    mcp.run(transport="stdio")
