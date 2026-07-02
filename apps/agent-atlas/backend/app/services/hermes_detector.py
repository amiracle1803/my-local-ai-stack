"""
Hermes Agent detector and subprocess bridge.

Hermes (D:\\hermes\\hermes-agent) is treated as a SECONDARY agent:
  - Agent Atlas always works without it.
  - When is_hermes_available() is True, certain tasks can be delegated.
  - Detection is cheap: just checks that the Python exe + cli.py both exist.

Configure with HERMES_PATH in .env (defaults to D:\\hermes\\hermes-agent).
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from app.utils.ids import now_iso

logger = logging.getLogger("agent_atlas.hermes")

_HERMES_DIR = Path(os.getenv("HERMES_PATH", r"D:\hermes\hermes-agent"))
_HERMES_PYTHON = _HERMES_DIR / "venv" / "Scripts" / "python.exe"
_HERMES_CLI = _HERMES_DIR / "cli.py"

# Availability cache: (available, timestamp)
_cache: tuple[bool, float] | None = None
_CACHE_TTL = 30.0  # re-check every 30 s


def is_hermes_available() -> bool:
    """Fast synchronous check — file existence only, no subprocess."""
    global _cache
    now = time.monotonic()
    if _cache and (now - _cache[1]) < _CACHE_TTL:
        return _cache[0]

    available = _HERMES_PYTHON.exists() and _HERMES_CLI.exists()
    _cache = (available, now)
    if available:
        logger.debug("Hermes detected at %s", _HERMES_DIR)
    return available


def get_hermes_info() -> dict:
    """Return metadata dict for the health/settings API."""
    available = is_hermes_available()
    return {
        "name": "hermes_agent",
        "provider": "hermes",
        "status": "healthy" if available else "down",
        "latency_ms": 0,
        "path": str(_HERMES_DIR),
        "python": str(_HERMES_PYTHON),
        "available": available,
        "role": "secondary",
        "checked_at": now_iso(),
    }


async def call_hermes(goal: str, timeout: int = 120) -> str:
    """
    Invoke Hermes in single-query mode: python cli.py -q '<goal>'

    Returns the stdout text. Raises RuntimeError on failure or timeout.
    """
    if not is_hermes_available():
        raise RuntimeError(
            f"Hermes not available at {_HERMES_DIR}. "
            "Set HERMES_PATH in .env if it is installed elsewhere."
        )

    env = {**os.environ, "HERMES_QUIET": "1", "NO_COLOR": "1"}

    try:
        proc = await asyncio.create_subprocess_exec(
            str(_HERMES_PYTHON),
            str(_HERMES_CLI),
            "-q", goal,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_HERMES_DIR),
            env=env,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"Hermes timed out after {timeout}s on goal: {goal[:80]}")
    except Exception as exc:
        raise RuntimeError(f"Failed to launch Hermes: {exc}")

    output = stdout_b.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 and not output:
        err = stderr_b.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Hermes exited {proc.returncode}: {err}")

    return output or "(Hermes returned no output)"
