from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import n8n_client


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

        if t in ("draft_workflow", "run"):
            goal = p.get("goal") or p.get("description", "")
            existing = await n8n_client.list_workflows()
            existing_names = ", ".join(w["name"] for w in existing) or "none yet"
            plan = await self.llm_call(
                f"Describe, in plain English steps (not JSON), an n8n workflow that would: {goal}\n\n"
                f"Existing workflows in this n8n instance for context: {existing_names}",
                system=self.definition.system_prompt,
            )
            return {"goal": goal, "plan": plan, "note": "Draft plan only -- creating/activating "
                    "workflows from a plan needs a follow-up create_workflow call with real node JSON."}

        return {"error": f"unknown automation message type '{t}'"}
