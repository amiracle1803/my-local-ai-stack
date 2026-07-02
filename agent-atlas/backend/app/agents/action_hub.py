import json
import logging
from typing import Any, Callable, Dict


def _extract_json(raw: str) -> str:
    """Extract the outermost JSON object from an LLM response."""
    import re
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

from app.agents.base import BaseAgent
from app.models.message import AgentMessage

logger = logging.getLogger("agent_atlas.agents.action_hub")

# Tool registry: tool_name → async callable
_tools: Dict[str, Callable] = {}

_TOOL_DESCRIPTIONS = {
    "file_read":       "Read a file from the sandbox (args: path, max_bytes?)",
    "file_write":      "Write content to a sandbox file (args: path, content)",
    "shell_exec":      "Run a whitelisted shell command (args: command, timeout?)",
    "http_get":        "Fetch a URL and return response text (args: url, timeout?)",
    "obsidian_append": "Append content to an Obsidian note (args: path, content)",
}


def register_tool(name: str, fn: Callable):
    _tools[name] = fn


class ActionHubAgent(BaseAgent):
    agent_id = "action_hub"

    async def handle(self, message: AgentMessage) -> Any:
        tool_name = message.payload.get("tool")

        # ── Direct tool call: {tool: "...", args: {...}} ──────────────────────
        if tool_name:
            args = message.payload.get("args", {})
            if tool_name not in _tools:
                return {"error": f"Unknown tool '{tool_name}'. Available: {list(_tools.keys())}"}
            logger.info("[action_hub] Direct call: tool='%s'", tool_name)
            try:
                result = await _tools[tool_name](**args)
                return {"tool": tool_name, "result": result, "status": "ok"}
            except Exception as exc:
                logger.error("[action_hub] Tool '%s' failed: %s", tool_name, exc)
                return {"tool": tool_name, "error": str(exc), "status": "error"}

        # ── Subtask from orchestrator: {task: "...", goal: "..."} ─────────────
        task = message.payload.get("task", "") or message.payload.get("goal", "")
        if not task:
            return {"error": "No tool or task specified in payload"}

        available = list(_tools.keys())
        if not available:
            return {"error": "No tools registered with Action Hub"}

        tool_list = "\n".join(
            f"- {name}: {_TOOL_DESCRIPTIONS.get(name, '(no description)')}"
            for name in available
        )
        prompt = (
            f"You are an action dispatcher. Select the best tool for this task.\n\n"
            f"Available tools:\n{tool_list}\n\n"
            f"Task: {task}\n\n"
            f"Respond with JSON only (no markdown fences):\n"
            f'{{ "tool": "<tool_name>", "args": {{...}}, "reasoning": "..." }}'
        )

        try:
            raw = await self.llm_call(prompt)
            json_str = _extract_json(raw)
            if not json_str.startswith("{"):
                return {"error": "LLM did not return valid JSON", "raw": raw[:300]}
            selection = json.loads(json_str)
            chosen = selection.get("tool", "")
            chosen_args = selection.get("args", {})
            if chosen not in _tools:
                return {"error": f"LLM chose unknown tool '{chosen}'. Available: {available}"}
            logger.info("[action_hub] LLM selected '%s' for: %s", chosen, task[:80])
            result = await _tools[chosen](**chosen_args)
            return {
                "tool": chosen,
                "result": result,
                "status": "ok",
                "reasoning": selection.get("reasoning", ""),
            }
        except json.JSONDecodeError as exc:
            return {"error": f"JSON parse error: {exc}"}
        except Exception as exc:
            logger.error("[action_hub] LLM tool selection failed: %s", exc)
            return {"error": str(exc), "status": "error"}
