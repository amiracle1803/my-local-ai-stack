import logging

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import collaboration_bus as bus

logger = logging.getLogger("agent_atlas.agents.orchestrator")


class OrchestratorAgent(BaseAgent):
    agent_id = "orchestrator"

    async def handle(self, message: AgentMessage) -> str:
        goal = message.payload.get("goal", "")
        context = message.payload.get("context", {}) or {}
        model_override = message.payload.get("model")
        if not goal.strip():
            return "I need a goal to work with -- the request was empty."

        # Ask the planner for a quick complexity read. Non-fatal if it's
        # not available or errors -- the orchestrator can still answer
        # directly, just without that signal.
        try:
            plan = await bus.send_message(
                from_agent=self.agent_id, to_agent="planner", msg_type="plan",
                payload={"goal": goal}, conversation_id=message.conversation_id,
                job_id=message.job_id,
            )
        except Exception:  # noqa: BLE001
            plan = None
            logger.debug("planner unavailable, proceeding without a plan")

        preamble = self.build_context_preamble(context)
        steps_hint = ""
        if plan and plan.get("steps"):
            steps_hint = "\n\nSuggested approach:\n" + "\n".join(f"- {s}" for s in plan["steps"])
        prompt = f"{preamble}\n\n{goal}{steps_hint}".strip()

        response = await self.llm_call(prompt, system=self.definition.system_prompt, model_override=model_override)
        response = await self._maybe_revise(goal, response, message, model_override)
        return response

    async def _maybe_revise(self, goal: str, response: str, message: AgentMessage,
                             model_override: str | None = None) -> str:
        """One evaluator pass, one revision at most -- not a loop. If the
        evaluator isn't available or errors, the first draft stands."""
        try:
            verdict = await bus.send_message(
                from_agent=self.agent_id, to_agent="evaluator", msg_type="evaluate",
                payload={"goal": goal, "response": response},
                conversation_id=message.conversation_id, job_id=message.job_id,
            )
        except Exception:  # noqa: BLE001
            return response

        if not isinstance(verdict, dict) or verdict.get("verdict") != "revise":
            return response

        feedback = verdict.get("feedback", "")
        logger.info("evaluator requested a revision: %s", feedback)
        revised_prompt = (
            f"{goal}\n\nYour previous answer:\n{response}\n\n"
            f"A reviewer flagged this problem: {feedback}\n"
            f"Write a corrected answer."
        )
        try:
            return await self.llm_call(revised_prompt, system=self.definition.system_prompt,
                                        model_override=model_override)
        except Exception:  # noqa: BLE001
            return response  # revision attempt failed -- the original draft is still valid
