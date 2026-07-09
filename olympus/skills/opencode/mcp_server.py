"""OpenCode MCP — intelligence-layer tools on port 4720.

Rebuilt 2026-07-09. Exposes web fetch, file read, and code search as MCP tools
(FastMCP over SSE) plus a plain /health endpoint for start.bat's check.

Run (from repo root):
    .venv\\Scripts\\python.exe -m uvicorn olympus.skills.opencode.mcp_server:app --host 127.0.0.1 --port 4720
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import trafilatura
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

REPO_ROOT = Path(__file__).resolve().parents[3]

mcp = FastMCP("opencode")


@mcp.tool()
def web_fetch(url: str) -> str:
    """Fetch a web page and return its main content as Markdown."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return f"ERROR: could not fetch {url}"
    text = trafilatura.extract(downloaded, output_format="markdown")
    return text or f"ERROR: no extractable content at {url}"


@mcp.tool()
def read_file(path: str, max_bytes: int = 100_000) -> str:
    """Read a text file from disk (absolute path or relative to the repo root)."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.is_file():
        return f"ERROR: not a file: {p}"
    return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]


@mcp.tool()
def code_search(pattern: str, directory: str = ".", glob: str = "*") -> str:
    """Search files for a pattern (uses git grep when available, else Python)."""
    root = Path(directory)
    if not root.is_absolute():
        root = REPO_ROOT / root
    try:
        out = subprocess.run(
            ["git", "grep", "-n", "-I", "--untracked", pattern, "--", glob],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        if out.stdout:
            return out.stdout[:100_000]
    except (OSError, subprocess.TimeoutExpired):
        pass
    hits: list[str] = []
    for f in root.rglob(glob):
        if not f.is_file() or f.stat().st_size > 2_000_000:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if pattern in line:
                    hits.append(f"{f.relative_to(root)}:{i}:{line.strip()}")
                    if len(hits) >= 200:
                        return "\n".join(hits)
        except OSError:
            continue
    return "\n".join(hits) if hits else f"no matches for {pattern!r}"


async def health(_request):
    return JSONResponse({"status": "ok", "service": "opencode-mcp"})


# Plain Starlette wrapper so /health exists alongside the MCP SSE transport.
app = Starlette(routes=[
    Route("/health", health),
    Mount("/", app=mcp.sse_app()),
])
