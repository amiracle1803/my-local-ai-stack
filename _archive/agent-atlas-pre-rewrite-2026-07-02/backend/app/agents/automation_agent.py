import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.agents.automation_agent")

_N8N_WORKFLOW_SYSTEM_PROMPT = """You design n8n workflows. Given a plain-English request, output ONLY a JSON \
object (no markdown fences, no commentary) with this exact shape:

{"name": "<short workflow name>",
 "nodes": [ <n8n node objects> ],
 "connections": { <n8n connections object> }}

Rules:
- If the workflow needs to be triggered/tested programmatically (not just clicked in the n8n UI), the \
first node MUST be a Webhook trigger: {"parameters": {"path": "<url-safe-slug>", "httpMethod": "POST", \
"responseMode": "lastNode"}, "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0,0], \
"name": "Webhook"}.
- If the request wants something recurring (daily, hourly, "every morning" etc), use a Schedule Trigger \
instead: {"parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "<cron>"}]}}, \
"type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0,0], "name": "Schedule Trigger"}.
- To call the local Ollama model, use an "n8n-nodes-base.httpRequest" node (method POST, url \
"http://host.docker.internal:11434/v1/chat/completions", sendBody=true, specifyBody="json", jsonBody=<the \
JSON request body as a string>). n8n runs in Docker; "localhost" there is the container itself, not the \
host machine, which is why host.docker.internal is required.
- ONLY use these node "type" values, nothing else -- do not invent node types like "ollamaChat" or \
"n8n-nodes-base.openAi", they do not exist in this install: n8n-nodes-base.webhook, \
n8n-nodes-base.scheduleTrigger, n8n-nodes-base.httpRequest, n8n-nodes-base.set, n8n-nodes-base.if, \
n8n-nodes-base.code, n8n-nodes-base.noOp.
- Every "connections" entry MUST look exactly like: {"<SourceNodeName>": {"main": [[{"node": \
"<TargetNodeName>", "type": "main", "index": 0}]]}} -- note the double array around the target list.
- Give every node a unique "name" and reference those names (not ids) in "connections".
- Keep it to the minimum nodes needed. Position nodes left-to-right with increasing x (e.g. [0,0], [220,0], [440,0]).
"""


class AutomationAgent(BaseAgent):
    agent_id = "automation_agent"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op")

        # Subtask from orchestrator: {task: "...", goal: "..."} — no "op" key
        if op is None and ("task" in message.payload or "goal" in message.payload):
            task = message.payload.get("task", "") or message.payload.get("goal", "")
            task_lower = task.lower()
            if "n8n" in task_lower or ("workflow" in task_lower and any(
                kw in task_lower for kw in ("build", "create", "make", "set up", "setup")
            )):
                return await self._create_and_test_n8n_workflow(task)
            if any(kw in task_lower for kw in ("list", "show", "status", "check", "what jobs")):
                return self._list_jobs()
            # Map task intent to a job type
            job_type = "automation"
            for kw, jtype in (
                ("research", "research"), ("search", "research"),
                ("code", "code"), ("script", "code"), ("program", "code"),
                ("creative", "creative"), ("write", "creative"),
                ("deploy", "deploy"), ("obsidian", "obsidian"),
            ):
                if kw in task_lower:
                    job_type = jtype
                    break
            return self._schedule_job({"type": job_type, "job_payload": {"goal": task}})

        op = op or "schedule"
        if op == "schedule":
            return self._schedule_job(message.payload)
        if op == "list":
            return self._list_jobs()
        if op == "create_n8n_workflow":
            return await self._create_and_test_n8n_workflow(message.payload.get("goal", ""))
        return {"error": f"Unknown op: {op}"}

    async def _create_and_test_n8n_workflow(self, task: str) -> dict:
        """Draft an n8n workflow from natural language, create it, and (if it
        has a Webhook trigger) run it once to confirm it actually works."""
        from app.services import n8n_client

        try:
            raw = await self.llm_call(task, system=_N8N_WORKFLOW_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"Could not reach the local model to draft the workflow: {exc}"}

        spec = self._parse_workflow_json(raw)
        if spec is None:
            # one retry, telling the model exactly what went wrong
            try:
                raw = await self.llm_call(
                    f"Your last reply wasn't valid JSON matching the required shape. "
                    f"Reply with ONLY the JSON object this time.\n\nOriginal request: {task}",
                    system=_N8N_WORKFLOW_SYSTEM_PROMPT,
                )
                spec = self._parse_workflow_json(raw)
            except Exception as exc:
                return {"error": f"Model call failed on retry: {exc}"}
            if spec is None:
                return {"error": "Model did not return valid workflow JSON after 2 attempts.", "raw": raw[:1000]}

        try:
            wf = await n8n_client.create_workflow(
                spec["name"], spec["nodes"], spec["connections"], activate=True,
            )
        except n8n_client.N8nError as exc:
            # n8n's error messages are specific enough (e.g. "Unrecognized node
            # type: X") that feeding them straight back usually gets a small
            # local model to self-correct on one more try.
            try:
                raw = await self.llm_call(
                    f"n8n rejected your last workflow with this error:\n{exc}\n\n"
                    f"Your attempted JSON was:\n{json.dumps(spec)}\n\n"
                    f"Fix it and reply with ONLY the corrected JSON object.\n\nOriginal request: {task}",
                    system=_N8N_WORKFLOW_SYSTEM_PROMPT,
                )
                retry_spec = self._parse_workflow_json(raw)
            except Exception:
                retry_spec = None
            if retry_spec is None:
                return {"error": f"n8n rejected the workflow: {exc}", "attempted_spec": spec}
            try:
                wf = await n8n_client.create_workflow(
                    retry_spec["name"], retry_spec["nodes"], retry_spec["connections"], activate=True,
                )
                spec = retry_spec
            except n8n_client.N8nError as exc2:
                return {
                    "error": f"n8n rejected the workflow twice. Last error: {exc2}",
                    "first_error": str(exc), "attempted_spec": retry_spec,
                }

        result = {
            "workflow_id": wf["id"], "name": spec["name"], "active": wf.get("active", False),
        }

        webhook_path = n8n_client.find_webhook_path(wf)
        if webhook_path:
            try:
                run = await n8n_client.run_via_webhook(webhook_path)
                result["test_run"] = run
                result["status"] = "created and test-run succeeded" if run["status_code"] < 400 else \
                    f"created, but test run returned HTTP {run['status_code']}"
            except n8n_client.N8nError as exc:
                result["status"] = f"created, but the test run failed: {exc}"
        else:
            result["status"] = "created (no Webhook trigger, so it wasn't test-run -- it's either " \
                "manual-only or waiting on its Schedule Trigger)"

        return result

    @staticmethod
    def _parse_workflow_json(raw: str) -> dict | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("\n") + 1:] if "\n" in text else text
        try:
            spec = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(spec, dict) or "nodes" not in spec or "connections" not in spec:
            return None
        spec.setdefault("name", "Untitled workflow")
        return spec

    def _schedule_job(self, payload: dict) -> dict:
        job_type = payload.get("type", "automation")
        job_payload = payload.get("job_payload", {})
        job_id = new_id()
        ts = now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO jobs (id, type, status, payload_json, progress, created_at, updated_at)
                   VALUES (?, ?, 'queued', ?, 0, ?, ?)""",
                (job_id, job_type, json.dumps(job_payload), ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("[automation_agent] Scheduled job %s (type=%s)", job_id, job_type)
        return {"job_id": job_id, "status": "queued"}

    def _list_jobs(self) -> dict:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, type, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
        return {"jobs": [dict(r) for r in rows]}
