"""
System management endpoints: provider health status and manual DB backup trigger.
"""
import asyncio
import logging

from fastapi import APIRouter

from app.services.health_watchdog import get_provider_status
from app.services.db_backup import run_backup, get_last_backup

logger = logging.getLogger("agent_atlas.api.system")
router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health/providers")
async def provider_health():
    """Return the latest health status for all configured model providers + Hermes."""
    status = get_provider_status()
    providers = list(status.values())

    # Ensure Hermes is always in the list (even before first watchdog tick)
    if not any(p.get("name") == "hermes_agent" for p in providers):
        from app.services.hermes_detector import get_hermes_info
        providers.append(get_hermes_info())

    return {
        "providers": providers,
        "total": len(providers),
        "healthy": sum(1 for p in providers if p.get("status") == "healthy"),
    }


@router.get("/hermes/status")
async def hermes_status():
    """Return Hermes agent availability and configuration."""
    from app.services.hermes_detector import get_hermes_info, is_hermes_available, _HERMES_DIR
    info = get_hermes_info()
    return {
        **info,
        "dir": str(_HERMES_DIR),
        "note": (
            "Hermes is available as a secondary agent. "
            "Agent Atlas delegates tasks to it when requested."
        ) if is_hermes_available() else (
            "Hermes not found. Set HERMES_PATH in .env or install Hermes at "
            "D:\\hermes\\hermes-agent to enable secondary agent features."
        ),
    }


@router.post("/backup/run")
async def trigger_backup():
    """Manually trigger a DB export to data/exports/YYYY-MM-DD/."""
    try:
        result = await asyncio.to_thread(run_backup)
        return {"ok": True, **result}
    except Exception as exc:
        logger.error("Manual backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/backup/status")
async def backup_status():
    """Return the timestamp of the last completed backup."""
    return {"last_backup": get_last_backup()}
