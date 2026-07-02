"""
Concrete tool implementations for the Action Hub.
All file and shell operations are sandboxed to SANDBOX_DIR.
"""
import asyncio
import logging
import os
import shlex
from pathlib import Path

import httpx

from app.agents.action_hub import register_tool

logger = logging.getLogger("agent_atlas.tools")

_SANDBOX_DIR = Path(os.getenv("SANDBOX_DIR", str(Path.home() / "agent-atlas-sandbox")))

# Shell commands allowed to run (prefix match, lowercase)
_SHELL_ALLOWLIST = (
    "python", "pip", "npm", "node",
    "git status", "git log", "git diff",
    "ls", "dir", "echo", "cat", "type",
)


def _sandbox(p: str) -> Path:
    # Use relative_to() rather than startswith() to avoid the sibling-directory
    # false-positive: "/sandbox-escape" starts with "/sandbox" as a string.
    resolved = (_SANDBOX_DIR / p).resolve()
    try:
        resolved.relative_to(_SANDBOX_DIR.resolve())
    except ValueError:
        raise PermissionError(f"Path '{p}' escapes the sandbox.")
    return resolved


# ── Tools ─────────────────────────────────────────────────────────────────────

async def tool_file_read(path: str, max_bytes: int = 8192) -> dict:
    """Read a file from the sandbox directory."""
    try:
        p = _sandbox(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}

        def _read() -> tuple[str, int]:
            text = p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
            size = p.stat().st_size
            return text, size

        content, size = await asyncio.to_thread(_read)
        return {"path": str(p), "content": content, "size": size}
    except PermissionError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.error("file_read error: %s", exc)
        return {"error": str(exc)}


async def tool_file_write(path: str, content: str) -> dict:
    """Write content to a file in the sandbox directory."""
    try:
        p = _sandbox(path)

        def _write() -> int:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return len(content.encode())

        bytes_written = await asyncio.to_thread(_write)
        return {"path": str(p), "bytes_written": bytes_written}
    except PermissionError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.error("file_write error: %s", exc)
        return {"error": str(exc)}


async def tool_obsidian_append(path: str, content: str) -> dict:
    """Append a block of content to an Obsidian note."""
    try:
        from app.services.obsidian_indexer import append_to_note
        ok = append_to_note(path, content)
        return {"appended": ok, "path": path}
    except Exception as exc:
        logger.error("obsidian_append error: %s", exc)
        return {"error": str(exc)}


async def tool_shell_exec(command: str, timeout: int = 30) -> dict:
    """Run a whitelisted shell command inside the sandbox directory."""
    cmd_lower = command.strip().lower()
    if not any(cmd_lower.startswith(p) for p in _SHELL_ALLOWLIST):
        return {
            "error": f"Command not in allowlist. Allowed prefixes: {_SHELL_ALLOWLIST}",
            "command": command,
        }
    # Parse into args first so shell metacharacters (;, |, &&, $()) can't be
    # used to run extra commands — create_subprocess_exec does not invoke a shell.
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return {"error": f"Invalid command syntax: {exc}", "command": command}
    if not args:
        return {"error": "Empty command.", "command": command}
    try:
        _SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_SANDBOX_DIR),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[:4096],
            "stderr": stderr.decode(errors="replace")[:1024],
        }
    except asyncio.TimeoutError:
        return {"error": f"Command timed out after {timeout}s", "command": command}
    except Exception as exc:
        logger.error("shell_exec error: %s", exc)
        return {"error": str(exc)}


async def tool_http_get(url: str, timeout: int = 15) -> dict:
    """Fetch a URL and return the response text (first 8 KB)."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
        return {
            "status": resp.status_code,
            "content": resp.text[:8192],
            "content_type": resp.headers.get("content-type", ""),
        }
    except Exception as exc:
        logger.error("http_get error: %s", exc)
        return {"error": str(exc)}


# ── Registration ───────────────────────────────────────────────────────────────

def register_all_tools():
    """Register all tools with the Action Hub. Called once at startup."""
    _SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    register_tool("file_read", tool_file_read)
    register_tool("file_write", tool_file_write)
    register_tool("obsidian_append", tool_obsidian_append)
    register_tool("shell_exec", tool_shell_exec)
    register_tool("http_get", tool_http_get)
    logger.info("Registered 5 tools with Action Hub (sandbox: %s).", _SANDBOX_DIR)
