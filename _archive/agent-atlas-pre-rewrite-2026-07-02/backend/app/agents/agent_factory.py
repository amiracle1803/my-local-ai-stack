import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.agent_factory")


def _extract_json(raw: str) -> str:
    """Extract the outermost JSON object from an LLM response."""
    import re
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    stripped = raw.strip()
    if stripped.startswith("{"):
        return stripped
    last_close = raw.rfind("}")
    if last_close != -1:
        depth = 0
        for i in range(last_close, -1, -1):
            if raw[i] == "}":
                depth += 1
            elif raw[i] == "{":
                depth -= 1
                if depth == 0:
                    return raw[i : last_close + 1]
    return stripped


class AgentFactoryAgent(BaseAgent):
    agent_id = "agent_factory"

    async def handle(self, message: AgentMessage) -> Any:
        # Delegate to the HTTP API layer (POST /agents/factory)
        # This agent can also synthesize agent definitions via LLM
        goal = message.payload.get("goal", "")
        if goal:
            prompt = (
                f"Design a new agent for the following purpose: {goal}\n"
                "Return ONLY raw JSON (no markdown fences) with keys: id, display_name, layer, "
                "description, tools, model_preference, memory_scopes, policies, system_prompt."
            )
            raw = await self.llm_call(prompt)
            json_str = _extract_json(raw)
            try:
                definition = json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning("[agent_factory] Could not parse JSON: %s", raw[:200])
                definition = {"raw": raw}
            return {"definition": definition}
        return {"error": "Provide a 'goal' describing the new agent's purpose"}
