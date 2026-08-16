#!/usr/bin/env python3
"""
server.py — LLM Wiki JSON API + React SPA host.
  Dev:  API at :7337 — Vite dev server at :7338 proxies /api here.
  Prod: API + built React app served at :7337 (run `npm run build` in frontend/).

Requires: pip install fastapi uvicorn
"""

import argparse
import html
import json
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ATLAS_URL = "http://localhost:8000"
ROOT = Path(__file__).parent.parent

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("error: fastapi/uvicorn not installed.\n  pip install fastapi uvicorn", file=sys.stderr)
    sys.exit(1)

WIKI_PY  = ROOT / "tools" / "wiki.py"
AGENT_PY = ROOT / "tools" / "agent.py"
STATIC   = ROOT / "static"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(script: Path, *args) -> str:
    r = subprocess.run(
        [sys.executable, str(script)] + list(args),
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return (r.stdout + r.stderr).strip()


def _atlas_get(path: str, timeout: int = 4) -> dict | list:
    try:
        with urllib.request.urlopen(f"{ATLAS_URL}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _atlas_post(path: str, body: dict, timeout: int = 90) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{ATLAS_URL}{path}", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        return {"error": f"Atlas offline: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def _atlas_status() -> dict:
    try:
        with urllib.request.urlopen(f"{ATLAS_URL}/api/health", timeout=2) as r:
            d = json.loads(r.read())
            return {"online": True, **d}
    except Exception:
        return {"online": False}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Handles simple YAML lists."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text

    fm: dict = {}
    current_key = None
    for line in lines[1:end]:
        if re.match(r"^  - ", line):  # list item
            if current_key:
                fm.setdefault(current_key, [])
                if isinstance(fm[current_key], list):
                    fm[current_key].append(line.strip()[2:].strip())
        elif ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"\'')
            if v == "":  # key starts a list
                current_key = k
                fm[k] = []
            else:
                current_key = None
                fm[k] = v

    body = "\n".join(lines[end + 1:])
    return fm, body


_STRUCTURAL = {"index.md", "log.md", "overview.md"}


def _all_wiki_pages() -> list[dict]:
    wiki_dir = ROOT / "wiki"
    pages = []
    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name in _STRUCTURAL and md.parent == wiki_dir:
            continue
        rel = str(md.relative_to(wiki_dir)).replace("\\", "/")
        path = rel[:-3] if rel.endswith(".md") else rel  # strip .md
        fm = {}
        try:
            fm, _ = _parse_frontmatter(md.read_text(encoding="utf-8"))
        except Exception:
            pass
        pages.append({
            "path":       f"wiki/{path}",
            "title":      fm.get("title", md.stem.replace("-", " ").title()),
            "type":       fm.get("type", ""),
            "updated":    fm.get("updated", ""),
            "confidence": fm.get("confidence", ""),
        })
    return pages


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="LLM Wiki API", docs_url="/api/docs", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7338", "http://127.0.0.1:7338", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Wiki API ───────────────────────────────────────────────────────────────────

@app.get("/api/pages")
async def api_pages():
    pages = _all_wiki_pages()
    return JSONResponse({"pages": pages, "count": len(pages)})


@app.get("/api/page/{slug:path}")
async def api_page(slug: str):
    # slug may be like "wiki/concepts/foo" or "concepts/foo"
    rel = slug.removeprefix("wiki/")
    candidates = [
        ROOT / "wiki" / rel,
        ROOT / "wiki" / (rel + ".md"),
    ]
    found = next((c for c in candidates if c.exists() and c.is_file()), None)
    if not found:
        raise HTTPException(404, f"Page not found: {slug}")
    text = found.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    return JSONResponse({"frontmatter": fm, "content": body})


@app.get("/api/overview")
async def api_overview():
    p = ROOT / "wiki" / "overview.md"
    if not p.exists():
        return JSONResponse({"error": "overview.md not found", "content": ""})
    text = p.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    return JSONResponse({"frontmatter": fm, "content": body})


@app.get("/api/log")
async def api_log():
    p = ROOT / "wiki" / "log.md"
    if not p.exists():
        return JSONResponse({"content": "_No log entries yet._"})
    return JSONResponse({"content": p.read_text(encoding="utf-8")})


@app.get("/api/search")
async def api_search(q: str = ""):
    if not q.strip():
        return JSONResponse({"results": [], "query": q})
    needle = q.lower()
    results = []
    wiki_dir = ROOT / "wiki"
    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name in _STRUCTURAL and md.parent == wiki_dir:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
            if needle not in text.lower() and needle not in md.stem.lower():
                continue
            rel  = str(md.relative_to(wiki_dir)).replace("\\", "/")
            path = "wiki/" + (rel[:-3] if rel.endswith(".md") else rel)
            fm, body = _parse_frontmatter(text)
            title = fm.get("title", md.stem.replace("-", " ").title())
            ptype = fm.get("type", "")
            body_lower = body.lower()
            idx     = body_lower.find(needle)
            snippet = ""
            if idx >= 0:
                s   = max(0, idx - 40)
                raw = body[s: idx + 80].replace("\n", " ").strip()
                # escape HTML to prevent XSS when rendering snippet
                raw = html.escape(raw)
                # highlight the match
                hi  = re.sub(f"({re.escape(q)})", r"<mark>\1</mark>", raw, flags=re.IGNORECASE)
                snippet = ("…" if s else "") + hi + "…"
            results.append({"path": path, "title": title, "type": ptype,
                            "updated": fm.get("updated", ""), "snippet": snippet})
        except Exception:
            pass
    return JSONResponse({"results": results, "query": q, "count": len(results)})


# ── Raw sources API ────────────────────────────────────────────────────────────

@app.get("/api/raw")
async def api_raw():
    raw_dir = ROOT / "raw"
    groups: dict = {}
    for sub in sorted(raw_dir.iterdir()):
        if not sub.is_dir():
            continue
        files = sorted(
            f for f in sub.iterdir() if f.is_file() and f.name != ".gitkeep"
        )
        groups[sub.name] = [
            {
                "name": f.name,
                "path": str(f.relative_to(ROOT)).replace("\\", "/"),
                "size": _human(f.stat().st_size),
            }
            for f in files
        ]
    return JSONResponse({"groups": groups})


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@app.get("/api/raw/file")
async def api_raw_file(path: str = ""):
    if not path:
        raise HTTPException(400, "path required")
    full = (ROOT / path).resolve()
    raw_root = (ROOT / "raw").resolve()
    if not str(full).startswith(str(raw_root)) or not full.exists():
        raise HTTPException(404, "File not found or outside raw/")
    text = full.read_text(encoding="utf-8", errors="replace")
    if len(text) > 30_000:
        text = text[:30_000] + "\n\n…[truncated]"
    return JSONResponse({"path": path, "content": text})


# ── Atlas API (bridge) ─────────────────────────────────────────────────────────

@app.get("/api/atlas/status")
async def api_atlas_status():
    return JSONResponse(_atlas_status())


@app.get("/api/atlas/jobs")
async def api_atlas_jobs():
    raw  = _atlas_get("/api/jobs/?limit=30")
    jobs = raw if isinstance(raw, list) else raw.get("jobs", [])
    return JSONResponse({"jobs": jobs})


@app.get("/api/atlas/agents")
async def api_atlas_agents():
    raw    = _atlas_get("/api/agents/")
    agents = raw if isinstance(raw, list) else raw.get("agents", [])
    layers: dict = {}
    for a in agents:
        lyr = a.get("layer", "unknown")
        layers.setdefault(lyr, []).append(a)
    return JSONResponse({"agents": agents, "layers": layers, "count": len(agents)})


@app.post("/api/atlas/run")
async def api_atlas_run(req: Request):
    body = await req.json()
    result = _atlas_post("/api/run", {
        "goal":       body.get("goal", ""),
        "run_mode":   body.get("run_mode", "auto"),
        "risk_level": body.get("risk_level", "low"),
        "context":    {},
    })
    return JSONResponse(result)


# ── Wiki tools API ─────────────────────────────────────────────────────────────

@app.post("/api/tool/{name}")
async def api_tool(name: str, req: Request):
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass

    if name == "index":
        return JSONResponse({"output": _run(WIKI_PY, "index")})

    if name == "lint":
        return JSONResponse({"output": _run(WIKI_PY, "lint")})

    if name == "search":
        term = body.get("term", "")
        if not term:
            return JSONResponse({"output": "No term provided."}, status_code=400)
        return JSONResponse({"output": _run(WIKI_PY, "search", term)})

    if name == "log":
        action = body.get("action", "")
        title  = body.get("title", "")
        note   = body.get("note", "")
        if not action or not title:
            return JSONResponse({"output": "action and title required."}, status_code=400)
        args = ["log", action, title]
        if note:
            args += ["--note", note]
        return JSONResponse({"output": _run(WIKI_PY, *args)})

    if name == "ingest":
        path = body.get("path", "")
        if not path:
            return JSONResponse({"output": "No path provided."}, status_code=400)
        return JSONResponse({"output": _run(AGENT_PY, "ingest", path)})

    if name == "query":
        question = body.get("question", "")
        if not question:
            return JSONResponse({"output": "No question provided."}, status_code=400)
        return JSONResponse({"output": _run(AGENT_PY, "query", question)})

    return JSONResponse({"output": f"Unknown tool: {name}"}, status_code=400)


# ── SPA static serving (production) ───────────────────────────────────────────
# Serves real files from static/ first, then falls back to index.html for SPA routes.

_SPA_INDEX = STATIC / "index.html"


@app.get("/{catchall:path}", include_in_schema=False)
async def spa_catchall(catchall: str):
    if STATIC.exists():
        candidate = (STATIC / catchall).resolve()
        # Ensure the path stays inside static/ (no path traversal)
        try:
            candidate.relative_to(STATIC.resolve())
        except ValueError:
            raise HTTPException(403)
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        if _SPA_INDEX.exists():
            return FileResponse(str(_SPA_INDEX))
    return JSONResponse(
        {"error": "React frontend not built yet. Run: cd frontend && npm run build"},
        status_code=503,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LLM Wiki API server")
    parser.add_argument("--port", type=int, default=7337)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    mode = "production (serving static/)" if _SPA_INDEX.exists() else "dev (API only — run Vite at :7338)"
    print(f"LLM Wiki API  → http://{args.host}:{args.port}  [{mode}]")
    if not _SPA_INDEX.exists():
        print("  React UI     → http://localhost:7338  (npm run dev in frontend/)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
