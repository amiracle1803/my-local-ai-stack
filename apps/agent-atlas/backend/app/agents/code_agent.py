import os
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".pytest_cache", ".claude",
    # archived/generated/runtime content -- not source, and large enough
    # (audio output, task history) to starve out real source files from
    # the file-count budget below if not excluded
    "_archive", "task-outbox", "task-inbox", "done", "data", "_generated",
}
_MAX_FILES = 300
_DEFAULT_REPO = Path(__file__).resolve().parents[5]  # this repo itself, if no repo_path is given


def _build_repo_map(repo_path: Path, max_files: int = _MAX_FILES) -> str:
    lines: list[str] = []
    count = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        rel_root = Path(root).relative_to(repo_path)
        for f in sorted(files):
            if count >= max_files:
                lines.append("... (truncated)")
                return "\n".join(lines)
            rel = rel_root / f if str(rel_root) != "." else Path(f)
            lines.append(str(rel))
            count += 1
    return "\n".join(lines)


class CodeAgent(BaseAgent):
    agent_id = "code_agent"

    async def handle(self, message: AgentMessage) -> Any:
        task = message.payload.get("goal") or message.payload.get("task", "")
        repo_path_raw = message.payload.get("repo_path")
        repo_path = Path(repo_path_raw) if repo_path_raw else _DEFAULT_REPO

        if not repo_path.exists():
            return f"Repo path doesn't exist: {repo_path}"

        repo_map = _build_repo_map(repo_path)
        prompt = f"Repo: {repo_path}\n\nFile listing:\n{repo_map}\n\nTask:\n{task}"
        return await self.llm_call(prompt, system=self.definition.system_prompt)
