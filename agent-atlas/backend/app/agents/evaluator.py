import json
import logging
import re
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.evaluator")

EVAL_PROMPT = """You are an evaluator. Rate the following output for the given goal.
Return ONLY raw JSON with no explanation or markdown fences:
{{"score": 0-10, "pass": true/false, "feedback": "..."}}
Goal: {goal}
Output: {output}"""


def _extract_json(raw: str) -> str:
    """Extract the outermost JSON object from an LLM response."""
    # 1. Markdown code fence
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    stripped = raw.strip()
    # 2. Response starts directly with {
    if stripped.startswith("{"):
        return stripped
    # 3. Balanced-brace scan from the last '}'
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


class EvaluatorAgent(BaseAgent):
    agent_id = "evaluator"

    async def handle(self, message: AgentMessage) -> Any:
        goal = message.payload.get("goal", "")
        output = message.payload.get("output", "")
        logger.info("[evaluator] Evaluating output for: %s", goal[:60])

        prompt = EVAL_PROMPT.format(goal=goal, output=str(output)[:2000])
        raw = await self.llm_call(prompt)
        json_str = _extract_json(raw)
        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("[evaluator] Could not parse JSON from response: %s", raw[:200])
            result = {"score": 5, "pass": True, "feedback": raw}
        return result
