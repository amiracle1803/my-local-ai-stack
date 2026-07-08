import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.code_agent")

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".pytest_cache", ".claude",
    # archived/generated/runtime content -- not source, and large enough
    # (audio output, task history) to starve out real source files from
    # the file-count budget below if not excluded
    "_archive", "task-outbox", "task-inbox", "done", "data", "_generated",
}
_MAX_FILES = 300
_MAX_READ_FILES = 12
_MAX_READ_BYTES = 40_000
_MAX_WRITE_FILES = 20
_MAX_WRITE_BYTES = 200_000
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


def _strip_json_fences(raw: str) -> str:
    """Local models routinely wrap JSON in ```json ... ``` despite being
    told not to. Strip a single leading/trailing fence if present; leaves
    already-bare JSON untouched."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _safe_resolve(repo_path: Path, rel_path: str) -> Path:
    """The one hard boundary kept even in unsupervised write mode: this
    agent can write anywhere *inside* the repo it's pointed at, never
    outside it. Raises ValueError if rel_path (or a ../ in it) would
    resolve outside repo_path."""
    candidate = (repo_path / rel_path).resolve()
    repo_resolved = repo_path.resolve()
    try:
        candidate.relative_to(repo_resolved)
    except ValueError:
        raise ValueError(f"'{rel_path}' resolves outside the target repo -- refusing to write it")
    return candidate


class CodeAgent(BaseAgent):
    agent_id = "code_agent"

    async def handle(self, message: AgentMessage) -> Any:
        task = message.payload.get("goal") or message.payload.get("task", "")
        repo_path_raw = message.payload.get("repo_path")
        repo_path = Path(repo_path_raw) if repo_path_raw else _DEFAULT_REPO

        if not repo_path.exists():
            return f"Repo path doesn't exist: {repo_path}"

        if message.type == "write":
            return await self._write(task, repo_path)

        repo_map = _build_repo_map(repo_path)
        prompt = f"Repo: {repo_path}\n\nFile listing:\n{repo_map}\n\nTask:\n{task}"
        return await self.llm_call(prompt, system=self.definition.system_prompt)

    async def _write(self, task: str, repo_path: Path) -> Dict[str, Any]:
        """Reads whatever files it says it needs, then writes files
        directly -- no approval step. Two guardrails, neither of them a
        review gate: writes can't resolve outside repo_path (see
        _safe_resolve), and this path only runs for an explicit "write"
        message -- a plain goal/ping on this agent never writes anything,
        so an ambiguous chat question can't accidentally trigger one."""
        repo_map = _build_repo_map(repo_path)

        select_raw = await self.llm_call(
            f"Repo root: {repo_path}\n\nFile listing (paths already relative to the repo root):\n{repo_map}\n\n"
            f"Task:\n{task}\n\n"
            f'Which existing files (if any) do you need to read before you can do this? '
            f'Respond with ONLY a JSON array of paths exactly as they appear in the file listing '
            f'above, e.g. ["app/main.py"]. Empty array [] if you\'re only creating new files.',
            system=self.definition.system_prompt, temperature=0.1,
        )
        try:
            requested = json.loads(_strip_json_fences(select_raw))
            requested = [p for p in requested if isinstance(p, str)][:_MAX_READ_FILES]
        except (json.JSONDecodeError, TypeError):
            requested = []

        context_blocks = []
        for rel in requested:
            try:
                full = _safe_resolve(repo_path, rel)
                if full.is_file():
                    text = full.read_text(encoding="utf-8", errors="replace")[:_MAX_READ_BYTES]
                    context_blocks.append(f"--- {rel} ---\n{text}")
            except (ValueError, OSError) as exc:
                logger.debug("skipping unreadable requested file %r: %s", rel, exc)
        context_text = "\n\n".join(context_blocks) or "(no existing files read)"

        write_prompt = (
            f"Repo root: {repo_path}\n\nTask:\n{task}\n\n"
            f"Current content of the files you asked for:\n{context_text}\n\n"
            f'Respond with ONLY a JSON array of files to write, each shaped like '
            f'{{"path": "relative/path.py", "content": "full new file content"}}. '
            f'"path" is relative to the repo root shown above -- do not prefix it with "repo/" or '
            f"the repo's own folder name. Each entry's content is the COMPLETE file, not a diff -- "
            f"it replaces the file's content entirely (or creates it, if new). "
            f"Output raw JSON only: no prose, no markdown code fences."
        )
        writes = None
        write_raw = ""
        for attempt in range(2):
            write_raw = await self.llm_call(
                write_prompt, system=self.definition.system_prompt, temperature=0.1, timeout=150.0,
            )
            try:
                candidate = json.loads(_strip_json_fences(write_raw))
                if isinstance(candidate, list):
                    writes = candidate
                    break
            except (json.JSONDecodeError, TypeError):
                pass
            write_prompt = (
                write_prompt + f"\n\nYour previous attempt wasn't valid JSON: {write_raw[:200]!r}. "
                f"Respond again with ONLY the JSON array, nothing else -- no markdown fences."
            )

        if writes is None:
            logger.warning("code_agent write: no valid write list after 2 attempts: %r", write_raw[:300])
            return {"error": "Couldn't turn that into a valid set of file writes after two attempts.",
                    "raw_model_output": write_raw[:500]}

        written: List[str] = []
        errors: List[str] = []
        for entry in writes[:_MAX_WRITE_FILES]:
            if not isinstance(entry, dict) or "path" not in entry or "content" not in entry:
                errors.append(f"skipped malformed entry: {str(entry)[:100]}")
                continue
            try:
                full = _safe_resolve(repo_path, entry["path"])
                content = str(entry["content"])[:_MAX_WRITE_BYTES]
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
                written.append(entry["path"])
            except (ValueError, OSError) as exc:
                errors.append(f"{entry.get('path', '?')}: {exc}")

        logger.info("code_agent write: wrote %d file(s), %d error(s)", len(written), len(errors))
        return {"written": written, "errors": errors, "files_read_first": requested}
