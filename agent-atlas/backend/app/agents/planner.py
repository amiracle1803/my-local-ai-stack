import json
import logging
import re
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.planner")

AGENT_ROSTER = """
Available agents:
- knowledge_hub       : research, synthesis, cross-source information retrieval (combines retrieval_agent + obsidian_brain automatically)
- retrieval_agent     : semantic + keyword search in the local vector knowledge base
- memory_agent        : save/recall user profile facts and past session episodes
- obsidian_brain      : read, search, and append to the user's Obsidian vault
- code_agent          : write, debug, explain, refactor, or review code (any language)
- creative_studio_agent: write documents, summaries, reports, emails, plans, or any structured text
- automation_agent    : schedule background jobs or check job/task status
- evaluator           : score, rate, or critique completed work — always use as the LAST step when quality matters
""".strip()

PLAN_PROMPT = """{context_preamble}You are the Planner for Agent Atlas, a local multi-agent AI system.

{roster}

Break the following goal into 2–5 focused subtasks. Rules:
- Assign each subtask to exactly one agent from the list above.
- If a later subtask needs the output of an earlier one, set depends_on to include the earlier id.
- Keep descriptions concrete — tell the agent what to actually do, not just what category it is.
- Do NOT create more subtasks than necessary; 2–3 is usually enough.
- When the goal is a follow-up or builds on prior conversation, start with knowledge_hub to pull relevant prior context.

Goal: {goal}
Extra context: {context_json}

Return ONLY raw JSON (no markdown fences, no explanation):
{{"subtasks": [{{"id": "1", "description": "...", "agent": "...", "depends_on": []}}]}}"""


def _extract_json(raw: str) -> str:
    # 1. Markdown code fence
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 2. Response starts directly with { — use as-is
    stripped = raw.strip()
    if stripped.startswith("{"):
        return stripped

    # 3. Balanced-brace scan: find the outermost {...} block starting from the
    #    last '}' and walking backwards to its matching '{'.  This correctly
    #    skips any LLM preamble that contains stray curly braces.
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


class PlannerAgent(BaseAgent):
    agent_id = "planner"

    async def handle(self, message: AgentMessage) -> Any:
        goal    = message.payload.get("goal", "")
        context = message.payload.get("context", {})
        logger.info("[planner] Planning goal: %s", goal[:80])

        context_preamble = self._build_context_preamble(context)

        # Truncate context for JSON embedding — keep only non-redundant keys
        ctx_for_json = {
            k: v for k, v in context.items()
            if k not in ("memory_context", "conversation_history", "prior_results")
        }

        prompt = PLAN_PROMPT.format(
            context_preamble=context_preamble,
            roster=AGENT_ROSTER,
            goal=goal,
            context_json=json.dumps(ctx_for_json)[:800],
        )
        raw = await self.llm_call(prompt)

        json_str = _extract_json(raw)
        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("[planner] JSON parse failed, falling back to single task")
            plan = {
                "subtasks": [
                    {"id": "1", "description": goal, "agent": "knowledge_hub", "depends_on": []}
                ]
            }

        return {"plan": plan, "goal": goal}
