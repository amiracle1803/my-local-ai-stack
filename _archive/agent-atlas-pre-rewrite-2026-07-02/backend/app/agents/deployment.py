import asyncio
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.config.loader import ConfigLoader
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.deployment")


class DeploymentAgent(BaseAgent):
    agent_id = "deployment_agent"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op", "status")
        if op == "status":
            return await self._status()
        if op == "reload_config":
            ConfigLoader.load()
            return {"status": "config reloaded"}
        return {"error": f"Unknown op: {op}"}

    async def _status(self) -> dict:
        git_rev = await self._git_rev()
        return {
            "git_rev": git_rev,
            "models_loaded": len(ConfigLoader.get_all_models()),
            "agents_loaded": len(ConfigLoader.get_all_agents()),
        }

    @staticmethod
    async def _git_rev() -> str:
        """Return short git SHA without blocking the event loop."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--short", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return stdout.decode().strip() if proc.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
