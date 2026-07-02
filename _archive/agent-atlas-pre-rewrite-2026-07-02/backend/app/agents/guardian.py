import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services.policy_engine import evaluate, load_policies

logger = logging.getLogger("agent_atlas.agents.guardian")


class GuardianAgent(BaseAgent):
    agent_id = "guardian_agent"

    def __init__(self):
        super().__init__()
        # Policies are loaded by main.py before register_all_agents() runs.
        # A second load_policies() here would re-read the file unnecessarily.

    async def handle(self, message: AgentMessage) -> Any:
        tool = message.payload.get("tool", "")
        action = message.payload.get("action", tool)
        agent = message.payload.get("agent", message.from_agent)
        args = message.payload.get("args", {})

        result = evaluate(tool=action, agent=agent, args=args)
        logger.info(
            "[guardian] %s '%s' (agent=%s) → %s (%s)",
            result["decision"].upper(), action, agent, result["allowed"], result["reason"],
        )
        return result
