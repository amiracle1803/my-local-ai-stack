import json
import logging
from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.evaluator")

_FALLBACK: Dict[str, Any] = {"verdict": "approve", "feedback": ""}


class EvaluatorAgent(BaseAgent):
    agent_id = "evaluator"

    async def handle(self, message: AgentMessage) -> Dict[str, Any]:
        goal = message.payload.get("goal", "")
        response = message.payload.get("response", "")
        prompt = f"GOAL:\n{goal}\n\nDRAFT RESPONSE:\n{response}"
        raw = await self.llm_call(prompt, system=self.definition.system_prompt, temperature=0.2)
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("verdict") in ("approve", "revise"):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        logger.warning("evaluator produced unparseable output, defaulting to approve: %r", raw[:200])
        return _FALLBACK
