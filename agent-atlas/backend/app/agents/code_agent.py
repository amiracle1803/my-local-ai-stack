import logging
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.code_agent")

CODE_PROMPT = """{preamble}You are an expert software engineer.

Task: {task}

Repo map (top-level):
{repo_map}

Produce the implementation. Write clean, well-structured code. Include brief explanations only where the logic is non-obvious."""


class CodeAgent(BaseAgent):
    agent_id = "code_agent"

    async def handle(self, message: AgentMessage) -> Any:
        task = (
            message.payload.get("task")
            or message.payload.get("goal")
            or message.payload.get("description")
            or ""
        )
        context   = message.payload.get("context", {})
        repo_path = message.payload.get("repo_path") or context.get("repo_path", ".")
        logger.info("[code_agent] Task: %s", task[:80])

        preamble  = self._build_context_preamble(context)
        repo_map  = self._build_repo_map(repo_path, depth=2)

        result = await self.llm_call(
            CODE_PROMPT.format(
                preamble=preamble,
                task=task,
                repo_map=repo_map[:2000],
            )
        )
        return {"code": result, "task": task}

    def _build_repo_map(self, repo_path: str, depth: int = 2) -> str:
        p = Path(repo_path)
        if not p.exists():
            return "(repo path not found)"
        lines = []
        for f in sorted(p.rglob("*")):
            rel = f.relative_to(p)
            parts = rel.parts
            if len(parts) <= depth and not any(
                part.startswith(".") or part in ("node_modules", "__pycache__", ".git", ".venv")
                for part in parts
            ):
                lines.append(str(rel))
        return "\n".join(lines[:120])
