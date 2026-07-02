"""
Background watchdog that pings each configured local model provider every 60 s
and stores latency in memory + the SQLite metrics table.
"""
import asyncio
import logging
import time
from typing import Dict

import httpx

from app.config.loader import ConfigLoader
from app.utils.ids import now_iso

logger = logging.getLogger("agent_atlas.watchdog")

_status: Dict[str, dict] = {}
_task: asyncio.Task | None = None


def get_provider_status() -> Dict[str, dict]:
    return dict(_status)


async def _ping_model(name: str, config) -> dict:
    start = time.monotonic()
    try:
        endpoint = (config.endpoint or "").replace("/chat/completions", "/models")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(endpoint)
        ok = resp.status_code < 500
        latency_ms = (time.monotonic() - start) * 1000
        status = "healthy" if ok else "degraded"
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        status = "down"
        logger.debug("Provider %s unreachable: %s", name, exc)

    return {
        "name": name,
        "provider": config.provider,
        "status": status,
        "latency_ms": round(latency_ms, 1),
        "checked_at": now_iso(),
    }


async def _check_hermes() -> dict:
    """Non-network Hermes check — just file presence."""
    from app.services.hermes_detector import get_hermes_info
    return get_hermes_info()


async def _watchdog_loop(interval: float = 60.0):
    logger.info("Health watchdog started (interval=%ss)", interval)
    while True:
        for name, cfg in ConfigLoader.get_all_models().items():
            result = await _ping_model(name, cfg)
            _status[name] = result
            try:
                from app.storage.database import get_connection
                from app.utils.ids import new_id
                conn = get_connection()
                try:
                    conn.execute(
                        "INSERT INTO metrics (id, agent_id, metric, value, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (new_id(), f"provider.{name}", "latency_ms", result["latency_ms"], result["checked_at"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass

        # Hermes is a secondary agent, not a model provider — check separately
        try:
            _status["hermes_agent"] = await _check_hermes()
        except Exception as exc:
            logger.debug("Hermes check failed: %s", exc)

        await asyncio.sleep(interval)


def start_watchdog():
    global _task
    _task = asyncio.create_task(_watchdog_loop())
    logger.info("Provider health watchdog started.")


def stop_watchdog():
    global _task
    if _task:
        _task.cancel()
        _task = None
