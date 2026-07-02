import json
import logging
from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.planner")

_FALLBACK: Dict[str, Any] = {"complexity": "normal", "steps": []}


class PlannerAgent(BaseAgent):
    agent_id = "planner"

    async def handle(self, message: AgentMessage) -> Dict[str, Any]:
        goal = message.payload.get("goal", "")
        raw = await self.llm_call(goal, system=self.definition.system_prompt, temperature=0.2)
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "complexity" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        logger.warning("planner produced non-JSON output, falling back: %r", raw[:200])
        return _FALLBACK
