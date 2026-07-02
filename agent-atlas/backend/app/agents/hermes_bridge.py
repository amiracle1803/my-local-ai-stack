"""
Hermes Bridge Agent — delegates tasks to the Hermes agent on D: drive.

Registered in the Collaboration Bus as "hermes_bridge".
Gracefully no-ops when Hermes is not installed or unavailable.
"""

import logging

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services.hermes_detector import is_hermes_available, call_hermes

logger = logging.getLogger("agent_atlas.agents.hermes_bridge")


class HermesBridgeAgent(BaseAgent):
    # BaseAgent.__init__ reads config via this class attribute
    agent_id = "hermes_bridge"

    async def handle(self, message: AgentMessage) -> dict:
        goal = (
            message.payload.get("goal")
            or message.payload.get("query")
            or str(message.payload)
        )

        if not is_hermes_available():
            logger.info("Hermes not available — skipping delegation")
            return {
                "response": (
                    "Hermes is not currently available. "
                    "Agent Atlas handled this request with its own agents instead."
                ),
                "available": False,
                "delegated": False,
            }

        logger.info("[hermes_bridge] delegating: %s…", goal[:60])
        try:
            result = await call_hermes(goal)
            return {
                "response": result,
                "available": True,
                "delegated": True,
            }
        except Exception as exc:
            logger.warning("[hermes_bridge] delegation failed: %s", exc)
            return {
                "response": f"Hermes delegation failed: {exc}",
                "available": False,
                "delegated": False,
                "error": str(exc),
            }
