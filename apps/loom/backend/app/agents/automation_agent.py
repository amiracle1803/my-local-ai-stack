import json
import logging
from typing import Any, Dict

import httpx

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import n8n_client

logger = logging.getLogger("agent_atlas.agents.automation_agent")

_WORKFLOW_JSON_INSTRUCTIONS = """Respond with ONLY a JSON object (no prose, no markdown fences) shaped like:
{
  "name": "short workflow name",
  "nodes": [
    {"id": "1", "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 1,
     "position": [250, 300], "parameters": {"path": "some-path", "httpMethod": "POST"}},
    {"id": "2", "name": "...", "type": "n8n-nodes-base....", "typeVersion": 1,
     "position": [450, 300], "parameters": {...}}
  ],
  "connections": {
    "Webhook": {"main": [[{"node": "<next node name>", "type": "main", "index": 0}]]}
  }
}
Use real n8n node types (n8n-nodes-base.webhook, n8n-nodes-base.httpRequest, n8n-nodes-base.set,
n8n-nodes-base.if, n8n-nodes-base.noOp, etc). The first node should be a Webhook trigger so the
workflow can be tested over HTTP once activated."""


class AutomationAgent(BaseAgent):
    agent_id = "automation_agent"

    async def handle(self, message: AgentMessage) -> Any:
        t = message.type
        p = message.payload

        if t == "list_workflows":
            workflows = await n8n_client.list_workflows()
            return [{"id": w["id"], "name": w["name"], "active": w["active"]} for w in workflows]

        if t == "get_workflow":
            return await n8n_client.get_workflow(p["workflow_id"])

        if t == "draft_workflow":
            goal = p.get("goal") or p.get("description", "")
            existing = await n8n_client.list_workflows()
            existing_names = ", ".join(w["name"] for w in existing) or "none yet"
            plan = await self.llm_call(
                f"Describe, in plain English steps (not JSON), an n8n workflow that would: {goal}\n\n"
                f"Existing workflows in this n8n instance for context: {existing_names}",
                system=self.definition.system_prompt,
            )
            return {"goal": goal, "plan": plan, "note": "Draft plan only -- send a 'create_workflow' "
                    "message (or just ask for it directly) to actually create it, inactive, in n8n."}

        if t in ("create_workflow", "run"):
            goal = p.get("goal") or p.get("description", "")
            return await self._create_workflow(goal)

        return {"error": f"unknown automation message type '{t}'"}

    async def _create_workflow(self, goal: str) -> Dict[str, Any]:
        """Turns a goal into real n8n node/connection JSON and creates it.
        Never activates or runs it -- see n8n_client's module docstring for
        why (this n8n instance has a live email-triage workflow; guessing
        at trigger semantics to auto-run something new risked real side
        effects). You review and flip it active yourself in the n8n UI.

        Local reasoning models don't always land valid JSON on the first
        try for a schema this specific -- one retry with the parse error
        fed back (same "one correction pass" pattern as the orchestrator's
        evaluator loop) recovers most of those without looping forever."""
        prompt = f"Design an n8n workflow that would: {goal}\n\n{_WORKFLOW_JSON_INSTRUCTIONS}"
        spec: Dict[str, Any] | None = None
        raw = ""
        for attempt in range(2):
            raw = await self.llm_call(
                prompt, system=self.definition.system_prompt, temperature=0.2,
                timeout=150.0,  # ornith_local reasons at length; 60s cut it off every time
            )
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict) and all(k in candidate for k in ("name", "nodes", "connections")):
                    spec = candidate
                    break
            except (json.JSONDecodeError, TypeError):
                pass
            prompt = (f"Design an n8n workflow that would: {goal}\n\n{_WORKFLOW_JSON_INSTRUCTIONS}\n\n"
                      f"Your previous attempt wasn't usable ({raw[:200]!r}). "
                      f"Respond again with ONLY the JSON object, nothing else.")

        if spec is None:
            logger.warning("create_workflow: no valid workflow JSON after 2 attempts: %r", raw[:300])
            return {"error": "Couldn't turn that into a valid n8n workflow after two attempts. "
                              "Try asking for a plan first to see the approach in plain English.",
                    "raw_model_output": raw[:500]}
        name, nodes, connections = spec["name"], spec["nodes"], spec["connections"]

        try:
            created = await n8n_client.create_workflow(name, nodes, connections)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            logger.warning("n8n rejected the generated workflow %r: %s", name, detail)
            return {"error": f"n8n rejected the generated workflow ({exc.response.status_code}): {detail}",
                    "attempted_name": name}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"couldn't reach n8n: {exc}", "attempted_name": name}

        return {
            "workflow_id": created.get("id"),
            "name": created.get("name", name),
            "active": created.get("active", False),
            "note": "Created inactive in n8n -- open it in the n8n UI to review the nodes, "
                    "then activate it yourself when you're happy with it.",
        }
