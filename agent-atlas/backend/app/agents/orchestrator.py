import asyncio
import json
import logging
from typing import Any, Optional

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.services import collaboration_bus as bus

logger = logging.getLogger("agent_atlas.agents.orchestrator")

# Normalize LLM-generated agent names to registered bus IDs
_AGENT_ALIASES = {
    "knowledge": "knowledge_hub",
    "research": "knowledge_hub",
    "memory": "memory_agent",
    "retrieval": "retrieval_agent",
    "obsidian": "obsidian_brain",
    "code": "code_agent",
    "coding": "code_agent",
    "action": "action_hub",
    "automation": "automation_agent",
    "creative": "creative_studio_agent",
    "creative_studio": "creative_studio_agent",
    "evaluation": "evaluator",
    "eval": "evaluator",
    "guardian": "guardian_agent",
    "deployment": "deployment_agent",
    "observability": "observability_agent",
    "local_trainer": "local_model_trainer",
}


def _normalize_agent(name: str) -> str:
    n = name.lower().strip().replace("-", "_").replace(" ", "_")
    if bus.has_handler(n):
        return n
    return _AGENT_ALIASES.get(n, "knowledge_hub")


class OrchestratorAgent(BaseAgent):
    agent_id = "orchestrator"

    _PLAN_TIMEOUT = 90  # seconds — prevents a hung plan from blocking forever

    async def handle(self, message: AgentMessage) -> Any:
        goal = message.payload.get("goal", "")
        context = message.payload.get("context", {})
        logger.info("[orchestrator] goal: %s", goal[:100])

        # n8n workflow authoring is a well-defined capability that lives
        # entirely in automation_agent -- route straight there instead of
        # letting the generic planner guess between code_agent/knowledge_hub
        # (it has no way to know "n8n" maps to a specific tool).
        if "n8n" in goal.lower():
            result = await bus.send_message(
                from_agent="orchestrator", to_agent="automation_agent",
                msg_type="subtask", payload={"goal": goal, "context": context},
                conversation_id=message.conversation_id,
            )
            text = result.get("status") if isinstance(result, dict) else None
            response = json.dumps(result, indent=2, default=str) if not text else (
                f"{text}\n\n{json.dumps(result, indent=2, default=str)}"
            )
            return {"response": response, "route": "n8n_direct"}

        if self._classify(goal) == "trivial":
            memory_ctx = await self._load_memory_context(goal)
            preamble = self._build_context_preamble({**context, "memory_context": memory_ctx} if memory_ctx else context)
            answer = await self.llm_call(f"{preamble}User: {goal}" if preamble else goal)
            return {"response": answer, "route": "direct"}

        # Enrich context with persistent memory before planning
        memory_ctx = await self._load_memory_context(goal)
        if memory_ctx:
            context = {**context, "memory_context": memory_ctx}

        # Get a structured plan from the Planner
        plan_result = await bus.send_message(
            from_agent="orchestrator",
            to_agent="planner",
            msg_type="plan_request",
            payload={"goal": goal, "context": context, "_job_id": context.get("_job_id")},
            conversation_id=message.conversation_id,
        )

        subtasks = []
        if isinstance(plan_result, dict):
            subtasks = plan_result.get("plan", {}).get("subtasks", [])

        if not subtasks:
            answer = await self.llm_call(goal)
            return {"response": answer, "route": "direct_fallback"}

        # Carry _job_id through so subtask dispatches can tag WS messages
        if "_job_id" not in context:
            context = {**context, "_job_id": message.payload.get("_job_id")}

        try:
            return await asyncio.wait_for(
                self._execute_plan(subtasks, goal, context, message.conversation_id),
                timeout=self._PLAN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("[orchestrator] Plan timed out after %ss — answering directly", self._PLAN_TIMEOUT)
            answer = await self.llm_call(goal)
            return {"response": answer, "route": "timeout_fallback"}

    # ── Plan execution ────────────────────────────────────────────────────────

    async def _execute_plan(
        self, subtasks: list, goal: str, context: dict, conversation_id: str
    ) -> dict:
        """Execute plan subtasks respecting depends_on, running independent tasks in parallel."""
        completed: dict[str, Any] = {}
        remaining = list(subtasks)
        max_rounds = min(len(subtasks) + 2, 12)

        for _ in range(max_rounds):
            if not remaining:
                break

            ready = [
                t for t in remaining
                if all(dep in completed for dep in t.get("depends_on", []))
            ]
            if not ready:
                logger.warning("[orchestrator] Dependency deadlock — unblocking first task.")
                ready = remaining[:1]

            batch = await asyncio.gather(
                *[self._run_subtask(t, goal, context, completed, conversation_id) for t in ready],
                return_exceptions=True,
            )

            for task, outcome in zip(ready, batch):
                if isinstance(outcome, Exception):
                    logger.error("[orchestrator] Subtask %s raised: %s", task["id"], outcome)
                    completed[task["id"]] = {"error": str(outcome)}
                else:
                    completed[task["id"]] = outcome

            done_ids = {t["id"] for t in ready}
            remaining = [t for t in remaining if t["id"] not in done_ids]

        final = await self._synthesize(goal, completed, context)

        # Fire-and-forget evaluation — never blocks the response to the user
        async def _eval_async():
            try:
                await bus.send_message(
                    from_agent="orchestrator",
                    to_agent="evaluator",
                    msg_type="evaluate_request",
                    payload={"goal": goal, "output": final},
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                logger.warning("[orchestrator] Evaluator background error: %s", exc)

        asyncio.create_task(_eval_async())

        return {
            "response": final,
            "route": "planned",
            "subtask_count": len(subtasks),
        }

    async def _run_subtask(
        self, subtask: dict, goal: str, context: dict, completed: dict, conversation_id: str
    ) -> Any:
        agent_id = _normalize_agent(subtask.get("agent", "knowledge_hub"))
        logger.info("[orchestrator] Dispatching subtask %s → %s", subtask.get("id"), agent_id)
        return await bus.send_message(
            from_agent="orchestrator",
            to_agent=agent_id,
            msg_type="subtask",
            payload={
                "task": subtask.get("description", ""),
                "goal": goal,
                "_job_id": context.get("_job_id"),
                "context": {
                    **context,
                    "subtask_id": subtask.get("id"),
                    "prior_results": {k: str(v)[:400] for k, v in completed.items()},
                },
            },
            conversation_id=conversation_id,
        )

    async def _synthesize(self, goal: str, results: dict, context: Optional[dict] = None) -> str:
        parts = []
        ctx = context or {}

        if ctx.get("is_followup"):
            prev_goal   = ctx.get("previous_goal", "")
            prev_result = ctx.get("previous_result", "")
            if prev_goal or prev_result:
                parts.append(
                    f"[CONVERSATION CONTEXT]\nPrevious task: {prev_goal}\n"
                    f"Previous result: {prev_result[:600]}"
                )

        parts.append(f"Current goal: {goal}\n\nAgent findings:")
        for task_id, result in results.items():
            snippet = json.dumps(result, default=str)[:700]
            parts.append(f"[{task_id}] {snippet}")

        parts.append(
            "\nUsing the agent findings above (and conversation context if provided), "
            "produce a clear, readable final answer. Do not repeat JSON — write in plain prose or markdown."
        )
        return await self.llm_call("\n\n".join(parts))

    # ── Memory context ────────────────────────────────────────────────────────

    async def _load_memory_context(self, goal: str) -> str:
        """Pull relevant Obsidian notes + recent episodes, return as a context block."""
        parts = []
        try:
            from app.services.obsidian_indexer import search_notes, get_vault_path
            if get_vault_path():
                hits = search_notes(goal, top_k=3)
                if hits:
                    snippets = "\n".join(
                        f"- [{h.get('title', 'note')}] {(h.get('snippet') or '')[:300]}"
                        for h in hits
                    )
                    parts.append(f"[Relevant Obsidian notes]\n{snippets}")
        except Exception as exc:
            logger.debug("Obsidian context load failed: %s", exc)

        try:
            from app.storage.database import get_connection
            conn = get_connection()
            try:
                rows = conn.execute(
                    "SELECT summary FROM memory_episodes ORDER BY created_at DESC LIMIT 3"
                ).fetchall()
            finally:
                conn.close()
            if rows:
                ep_text = "\n".join(f"- {r['summary']}" for r in rows if r["summary"])
                if ep_text:
                    parts.append(f"[Recent session memory]\n{ep_text}")
        except Exception as exc:
            logger.debug("Episode context load failed: %s", exc)

        if not parts:
            return ""
        return (
            "<<MEMORY CONTEXT (use this to give personalized, context-aware answers)>>\n"
            + "\n\n".join(parts)
            + "\n<<END MEMORY CONTEXT>>"
        )

    # ── Classification ────────────────────────────────────────────────────────

    def _classify(self, goal: str) -> str:
        """Route to 'trivial' (direct LLM) or 'hard' (multi-agent plan)."""
        g = goal.lower().strip()
        words = len(goal.split())

        # Very short or conversational → always trivial
        if words <= 5:
            return "trivial"

        # Pure question with no action verbs → trivial (fast path)
        is_question = g.endswith("?") or g.startswith(("what", "who", "where", "when", "how", "why", "is ", "are ", "can ", "does ", "do ", "did ", "will "))
        if is_question and words < 20:
            return "trivial"

        # Explain / describe / define are conversational, not planning
        conversational = {"explain", "describe", "define", "tell me", "what is", "what are", "give me"}
        if any(kw in g for kw in conversational) and words < 25:
            return "trivial"

        # Action-oriented heavy tasks → use planner
        planning_keywords = {
            "build", "create", "implement", "research", "analyze",
            "refactor", "automate", "schedule", "scrape", "fetch",
            "design", "develop", "make", "debug", "deploy",
            "summarize", "compare", "review", "write a script",
            "write code", "generate code", "set up", "configure",
        }
        if any(kw in g for kw in planning_keywords):
            return "hard"

        # Long free-form goals → plan
        if words >= 20:
            return "hard"

        return "trivial"
