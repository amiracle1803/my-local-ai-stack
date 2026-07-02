"""
MCP (Model Context Protocol) server — exposes Agent Atlas tools to any MCP client.

Supported clients:
  • Claude Desktop  — configured in %APPDATA%\\Claude\\claude_desktop_config.json
  • Claude Code     — .mcp.json in project root (auto-loaded)
  • Roo Code        — MCP Servers panel → add http://127.0.0.1:8000/mcp/sse
  • Cursor          — Settings → MCP → add http://127.0.0.1:8000/mcp/sse

All clients connect to:  http://127.0.0.1:8000/mcp/sse

Multi-account email (.env pattern):
  EMAIL_1_NAME=Personal
  EMAIL_1_ADDRESS=you@gmail.com
  EMAIL_1_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
  EMAIL_1_IMAP_HOST=imap.gmail.com
  EMAIL_1_SMTP_HOST=smtp.gmail.com
  EMAIL_1_SMTP_PORT=587

  EMAIL_2_NAME=Work
  EMAIL_2_ADDRESS=work@company.com
  ...  (repeat for as many accounts as you need)
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("agent_atlas.mcp")

mcp_server = FastMCP(
    "Agent Atlas",
    instructions=(
        "Local-first multi-agent system. "
        "Orchestrate AI agents, search your knowledge base, "
        "query Obsidian notes, send/read email from multiple accounts, "
        "search the web, and run autonomous background jobs."
    ),
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _text(result: object) -> str:
    if isinstance(result, dict):
        return result.get("response") or json.dumps(result, indent=2)
    return str(result) if result is not None else "(no response)"


# ── email account loader ──────────────────────────────────────────────────────

@dataclass
class EmailAccount:
    number: int
    name: str
    address: str
    app_password: str
    imap_host: str
    smtp_host: str
    smtp_port: int


def _load_email_accounts() -> list[EmailAccount]:
    """Read all EMAIL_N_* blocks from the environment."""
    accounts: list[EmailAccount] = []
    n = 1
    while True:
        address = os.getenv(f"EMAIL_{n}_ADDRESS", "").strip()
        if not address:
            break
        accounts.append(EmailAccount(
            number=n,
            name=os.getenv(f"EMAIL_{n}_NAME", f"Account {n}").strip(),
            address=address,
            app_password=os.getenv(f"EMAIL_{n}_APP_PASSWORD", "").strip(),
            imap_host=os.getenv(f"EMAIL_{n}_IMAP_HOST", "imap.gmail.com").strip(),
            smtp_host=os.getenv(f"EMAIL_{n}_SMTP_HOST", "smtp.gmail.com").strip(),
            smtp_port=int(os.getenv(f"EMAIL_{n}_SMTP_PORT", "587")),
        ))
        n += 1
    return accounts


def _resolve_account(account: str | int | None) -> EmailAccount | None:
    """
    Find an email account by number (1, 2, …) or name (case-insensitive).
    Defaults to account 1 when None.
    """
    accounts = _load_email_accounts()
    if not accounts:
        return None
    if account is None:
        return accounts[0]
    # numeric
    if isinstance(account, int) or (isinstance(account, str) and account.isdigit()):
        idx = int(account) - 1
        return accounts[idx] if 0 <= idx < len(accounts) else None
    # name
    needle = str(account).lower()
    for acc in accounts:
        if acc.name.lower() == needle or acc.address.lower() == needle:
            return acc
    return None


def _no_accounts_msg() -> str:
    return (
        "No email accounts configured. Add to .env:\n\n"
        "  EMAIL_1_NAME=Personal\n"
        "  EMAIL_1_ADDRESS=you@gmail.com\n"
        "  EMAIL_1_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx\n"
        "  EMAIL_1_IMAP_HOST=imap.gmail.com\n"
        "  EMAIL_1_SMTP_HOST=smtp.gmail.com\n"
        "  EMAIL_1_SMTP_PORT=587\n\n"
        "Gmail App Passwords: myaccount.google.com/apppasswords"
    )


# ── tools ─────────────────────────────────────────────────────────────────────

@mcp_server.tool()
async def ask_atlas(goal: str, context: Optional[str] = None) -> str:
    """Send any goal to Agent Atlas and receive a full multi-agent response.

    The system classifies the request, optionally runs a planner, fans out to
    knowledge / code / automation agents in parallel, evaluates the result, and
    returns a synthesized answer.

    Args:
        goal: What you want to accomplish or know.
        context: Optional background information to include.
    """
    from app.services.collaboration_bus import send_message
    from app.utils.ids import new_id

    try:
        result = await send_message(
            from_agent="mcp_client",
            to_agent="orchestrator",
            msg_type="user_goal",
            payload={
                "goal": goal,
                "context": {"extra": context or ""},
                "permissions": [],
            },
            conversation_id=new_id(),
            user_visible=True,
        )
        return _text(result)
    except Exception as exc:
        logger.warning("ask_atlas error: %s", exc)
        return f"Error: {exc}"


@mcp_server.tool()
async def search_knowledge(query: str) -> str:
    """Search the local knowledge base (vector store + Obsidian vault).

    Queries the embedding store and your Obsidian notes in parallel and returns
    the most relevant snippets. Works fully offline.

    Args:
        query: Topic or question to search for.
    """
    from app.services.collaboration_bus import send_message
    from app.utils.ids import new_id

    try:
        result = await send_message(
            from_agent="mcp_client",
            to_agent="knowledge_hub",
            msg_type="research_request",
            payload={"goal": query, "context": {}},
            conversation_id=new_id(),
        )
        return _text(result)
    except Exception as exc:
        logger.warning("search_knowledge error: %s", exc)
        return f"Error: {exc}"


@mcp_server.tool()
async def search_obsidian(query: str) -> str:
    """Search your Obsidian vault for matching notes.

    Returns note titles, tags, and relevant excerpts from the vault configured
    via OBSIDIAN_VAULT_PATH.

    Args:
        query: Keywords or topic to find.
    """
    from app.services.collaboration_bus import send_message
    from app.utils.ids import new_id

    try:
        result = await send_message(
            from_agent="mcp_client",
            to_agent="obsidian_brain",
            msg_type="search_notes",
            payload={"query": query},
            conversation_id=new_id(),
        )
        return _text(result)
    except Exception as exc:
        logger.warning("search_obsidian error: %s", exc)
        return f"Error: {exc}"


@mcp_server.tool()
async def create_background_job(goal: str, context: Optional[str] = None) -> str:
    """Queue an autonomous task in Agent Atlas's background runtime.

    The job runs independently in the background even after this conversation
    ends. Returns a job ID so you can track it with check_job().

    Args:
        goal: What the background job should accomplish.
        context: Optional extra context for the job.
    """
    from app.storage.database import get_connection
    from app.utils.ids import new_id, now_iso

    job_id = new_id()
    now = now_iso()
    payload = {"goal": goal, "context": context or ""}

    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO jobs (id, type, status, payload_json, progress, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, "orchestrator_task", "queued", json.dumps(payload), 0.0, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return (
            f"Background job created.\n"
            f"Job ID : {job_id}\n"
            f"Status : queued\n\n"
            f"Track it: check_job('{job_id}')"
        )
    except Exception as exc:
        logger.warning("create_background_job error: %s", exc)
        return f"Failed to create job: {exc}"


@mcp_server.tool()
async def check_job(job_id: str) -> str:
    """Check the status and result of a background job.

    Args:
        job_id: The job ID returned by create_background_job().
    """
    from app.storage.database import get_connection

    try:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT type, status, progress, result_json, error, created_at, updated_at "
                "FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return f"No job found with ID: {job_id}"

        pct = int((row["progress"] or 0) * 100)
        lines = [
            f"Job ID   : {job_id}",
            f"Type     : {row['type']}",
            f"Status   : {row['status']}",
            f"Progress : {pct}%",
            f"Created  : {row['created_at']}",
            f"Updated  : {row['updated_at']}",
        ]
        if row["error"]:
            lines.append(f"Error    : {row['error']}")
        if row["result_json"]:
            result = json.loads(row["result_json"])
            text = result.get("response", "") if isinstance(result, dict) else str(result)
            if text:
                lines.append(f"\nResult:\n{text[:3000]}")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("check_job error: %s", exc)
        return f"Error fetching job: {exc}"


@mcp_server.tool()
async def web_fetch(url: str) -> str:
    """Fetch the text content of any public URL.

    Strips HTML tags and returns the readable text. Use this for reading
    documentation, articles, GitHub files, APIs, or any public web page.

    Args:
        url: The URL to fetch (must start with http:// or https://).
    """
    import re
    import httpx

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(url, headers={"User-Agent": "AgentAtlas/1.0"})
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        text = resp.text

        if "html" in content_type:
            # strip tags, collapse whitespace
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S)
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)

        return text[:8000].strip()
    except Exception as exc:
        logger.warning("web_fetch error: %s", exc)
        return f"Error fetching {url}: {exc}"


@mcp_server.tool()
async def web_search(query: str, max_results: int = 8) -> str:
    """Search the web using DuckDuckGo (no API key required, completely free).

    Returns titles, URLs, and snippets for the top results. Use this when
    you need up-to-date information that isn't in the local knowledge base.

    Args:
        query: Search terms.
        max_results: How many results to return (1-20, default 8).
    """
    import httpx

    max_results = max(1, min(20, max_results))
    # DuckDuckGo Instant Answer JSON API — free, no key
    ddg_url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(ddg_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        lines = [f"Search: {query}\n"]

        # Instant answer
        if data.get("AbstractText"):
            lines.append(f"Summary: {data['AbstractText']}")
            if data.get("AbstractURL"):
                lines.append(f"Source: {data['AbstractURL']}")
            lines.append("")

        # Related topics as search results
        results = data.get("RelatedTopics", [])[:max_results]
        for i, r in enumerate(results, 1):
            if isinstance(r, dict) and r.get("Text"):
                url = r.get("FirstURL", "")
                lines.append(f"{i}. {r['Text'][:200]}")
                if url:
                    lines.append(f"   URL: {url}")
                lines.append("")

        if len(lines) <= 2:
            lines.append(
                "No instant results found. Try web_fetch() on a specific URL, "
                "or use ask_atlas() — it can synthesize an answer from local knowledge."
            )

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("web_search error: %s", exc)
        return f"Error searching '{query}': {exc}"


@mcp_server.tool()
async def list_email_accounts() -> str:
    """List all email accounts configured in Agent Atlas.

    Shows account number, name, and address. Use the number or name
    as the 'account' parameter in send_email and read_emails.
    """
    accounts = _load_email_accounts()
    if not accounts:
        return _no_accounts_msg()

    lines = [f"{len(accounts)} email account(s) configured:\n"]
    for acc in accounts:
        password_set = "✓ app password set" if acc.app_password else "✗ app password missing"
        lines.append(
            f"  [{acc.number}] {acc.name}\n"
            f"      Address : {acc.address}\n"
            f"      IMAP    : {acc.imap_host}\n"
            f"      SMTP    : {acc.smtp_host}:{acc.smtp_port}\n"
            f"      Status  : {password_set}"
        )
    lines.append(
        '\nUsage: send_email(to="x@y.com", subject="Hi", body="...", account="Personal")'
    )
    return "\n".join(lines)


@mcp_server.tool()
async def send_email(
    to: str,
    subject: str,
    body: str,
    account: Optional[str] = None,
    cc: Optional[str] = None,
) -> str:
    """Send an email from one of your configured email accounts.

    Args:
        to: Recipient address(es), comma-separated.
        subject: Email subject line.
        body: Email body (plain text).
        account: Account number (1, 2, …) or name (e.g. "Personal", "Work").
                 Defaults to account 1 if omitted.
        cc: Optional CC address(es), comma-separated.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    acc = _resolve_account(account)
    if acc is None:
        return _no_accounts_msg() if not _load_email_accounts() else (
            f"Account '{account}' not found. Use list_email_accounts() to see available accounts."
        )
    if not acc.app_password:
        return (
            f"App password missing for account [{acc.number}] {acc.name} ({acc.address}).\n"
            "Add it to .env:\n"
            f"  EMAIL_{acc.number}_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx\n"
            "Gmail: myaccount.google.com/apppasswords"
        )

    msg = MIMEMultipart()
    msg["From"] = f"{acc.name} <{acc.address}>"
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    msg.attach(MIMEText(body, "plain"))

    recipients = [r.strip() for r in to.split(",")]
    if cc:
        recipients += [r.strip() for r in cc.split(",")]

    def _do_send():
        with smtplib.SMTP(acc.smtp_host, acc.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(acc.address, acc.app_password)
            server.sendmail(acc.address, recipients, msg.as_string())

    try:
        await asyncio.to_thread(_do_send)
        return (
            f"Email sent from [{acc.number}] {acc.name} ({acc.address})\n"
            f"To: {to}" + (f"\nCC: {cc}" if cc else "")
        )
    except Exception as exc:
        logger.warning("send_email error [account %s]: %s", acc.number, exc)
        return f"Failed to send email from {acc.address}: {exc}"


@mcp_server.tool()
async def read_emails(
    account: Optional[str] = None,
    folder: str = "INBOX",
    max_count: int = 10,
    unread_only: bool = True,
) -> str:
    """Read emails from one of your configured inboxes.

    Args:
        account: Account number (1, 2, …) or name (e.g. "Personal", "Work").
                 Defaults to account 1 if omitted.
        folder: Mail folder to read (default: INBOX).
        max_count: How many emails to return (1-50, default 10).
        unread_only: Return only unread emails (default true).
    """
    import imaplib
    import email as email_lib
    from email.header import decode_header

    acc = _resolve_account(account)
    if acc is None:
        return _no_accounts_msg() if not _load_email_accounts() else (
            f"Account '{account}' not found. Use list_email_accounts() to see available accounts."
        )
    if not acc.app_password:
        return (
            f"App password missing for account [{acc.number}] {acc.name}.\n"
            f"Add EMAIL_{acc.number}_APP_PASSWORD to .env."
        )

    max_count = max(1, min(50, max_count))

    def _decode(val) -> str:
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
        return str(val)

    def _header(raw) -> str:
        parts = decode_header(raw or "")
        out = []
        for part, enc in parts:
            if isinstance(part, bytes):
                out.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(part))
        return " ".join(out)

    def _fetch_imap() -> str:
        mail = imaplib.IMAP4_SSL(acc.imap_host)
        try:
            mail.login(acc.address, acc.app_password)
            mail.select(folder)

            criterion = "(UNSEEN)" if unread_only else "ALL"
            _, data = mail.search(None, criterion)
            ids = data[0].split()[-max_count:]

            if not ids:
                label = "unread " if unread_only else ""
                return f"No {label}emails in {folder} for [{acc.number}] {acc.name}."

            label = "unread " if unread_only else ""
            lines = [f"{len(ids)} {label}email(s) — [{acc.number}] {acc.name} / {folder}\n"]
            for uid in reversed(ids):
                _, msg_data = mail.fetch(uid, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])
                subject = _header(msg.get("Subject"))
                sender = _header(msg.get("From"))
                date = _header(msg.get("Date"))

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = _decode(part.get_payload(decode=True))
                            break
                else:
                    body = _decode(msg.get_payload(decode=True))

                lines += [
                    f"From   : {sender}",
                    f"Subject: {subject}",
                    f"Date   : {date}",
                    f"Preview: {body.strip()[:300]}",
                    "",
                ]

            return "\n".join(lines)
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    try:
        return await asyncio.to_thread(_fetch_imap)
    except Exception as exc:
        logger.warning("read_emails error [account %s]: %s", acc.number, exc)
        return f"Failed to read emails from {acc.address}: {exc}"


@mcp_server.tool()
async def list_n8n_workflows() -> str:
    """List all workflows in the local n8n instance (name, id, active state).

    Use this before create_n8n_workflow to check whether something similar
    already exists.
    """
    from app.services import n8n_client

    try:
        wfs = await n8n_client.list_workflows()
        if not wfs:
            return "No workflows in n8n yet."
        lines = [f"{len(wfs)} workflow(s):\n"]
        for w in wfs:
            lines.append(f"  [{'ACTIVE' if w.get('active') else 'inactive'}] {w['name']}  (id: {w['id']})")
        return "\n".join(lines)
    except n8n_client.N8nError as exc:
        return f"Error: {exc}"


@mcp_server.tool()
async def create_n8n_workflow(
    name: str,
    nodes_json: str,
    connections_json: str,
    activate: bool = True,
) -> str:
    """Create a new n8n workflow from raw node/connection JSON, ready to run.

    n8n's REST API cannot execute a Manual Trigger workflow -- the only
    trigger type that can be run over HTTP is a Webhook node. If this
    workflow needs to be run/tested by an agent (not just by a human
    clicking around the n8n UI), give it a Webhook trigger, not a Manual
    Trigger. If it should run on a timer instead, use a Schedule Trigger
    (n8n-nodes-base.scheduleTrigger) -- those fire on their own once active,
    no manual run needed.

    IMPORTANT: n8n runs inside Docker. Any HTTP Request node that calls
    Ollama on this machine MUST use http://host.docker.internal:11434,
    NOT http://localhost:11434 -- localhost inside the container is the
    container itself.

    Minimal working example (webhook -> ask local Ollama -> respond):
        nodes_json:
        [
          {"parameters": {"path": "my-flow", "httpMethod": "POST", "responseMode": "lastNode"},
           "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0,0], "name": "Webhook"},
          {"parameters": {"method": "POST", "url": "http://host.docker.internal:11434/v1/chat/completions",
           "sendBody": true, "specifyBody": "json",
           "jsonBody": "{\\"model\\": \\"qwen2.5:7b\\", \\"messages\\": [{\\"role\\": \\"user\\", \\"content\\": \\"hello\\"}]}",
           "options": {}}, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4,
           "position": [220,0], "name": "Ask Ollama"}
        ]
        connections_json:
        {"Webhook": {"main": [[{"node": "Ask Ollama", "type": "main", "index": 0}]]}}

    Args:
        name: Workflow name, shown in the n8n UI.
        nodes_json: JSON array of n8n node objects (see example above).
        connections_json: JSON object mapping node name -> its outgoing connections.
        activate: Activate immediately so a Webhook/Schedule trigger can fire (default true).
    """
    from app.services import n8n_client

    try:
        nodes = json.loads(nodes_json)
        connections = json.loads(connections_json)
    except json.JSONDecodeError as exc:
        return f"nodes_json/connections_json is not valid JSON: {exc}"

    try:
        wf = await n8n_client.create_workflow(name, nodes, connections, activate=activate)
        webhook_path = n8n_client.find_webhook_path(wf)
        lines = [
            f"Created workflow '{name}' (id: {wf['id']}), active={wf.get('active', False)}.",
        ]
        if webhook_path:
            lines.append(f"Run it with: run_n8n_workflow('{wf['id']}')")
        else:
            lines.append(
                "No Webhook trigger found -- this workflow can only be run from the n8n UI "
                "(or it self-triggers if it has a Schedule Trigger)."
            )
        return "\n".join(lines)
    except n8n_client.N8nError as exc:
        return f"Error creating workflow: {exc}"


@mcp_server.tool()
async def run_n8n_workflow(workflow_id: str, payload_json: Optional[str] = None) -> str:
    """Run an n8n workflow that has a Webhook trigger, and return its output.

    Ensures the workflow is active, POSTs to its webhook URL, and returns
    the response. Follow up with check_n8n_workflow() if you want the full
    execution log rather than just the webhook response.

    Args:
        workflow_id: The workflow's id (from create_n8n_workflow or list_n8n_workflows).
        payload_json: Optional JSON object to POST as the webhook's input data.
    """
    from app.services import n8n_client

    payload = None
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            return f"payload_json is not valid JSON: {exc}"

    try:
        wf = await n8n_client.get_workflow(workflow_id)
        path = n8n_client.find_webhook_path(wf)
        if not path:
            return (
                f"Workflow '{wf.get('name')}' has no Webhook trigger node, so it can't be run "
                "over the API. Re-create it with a Webhook trigger, or run it manually from the n8n UI."
            )
        if not wf.get("active"):
            await n8n_client.set_active(workflow_id, True)
        result = await n8n_client.run_via_webhook(path, payload)
        return f"Ran '{wf.get('name')}' -- HTTP {result['status_code']}\n\n{json.dumps(result['body'], indent=2)[:3000]}"
    except n8n_client.N8nError as exc:
        return f"Error running workflow: {exc}"


@mcp_server.tool()
async def check_n8n_workflow(workflow_id: str, execution_limit: int = 5) -> str:
    """Check a workflow's active state and its most recent execution results.

    Use this after run_n8n_workflow() (or after a Schedule Trigger should
    have fired) to confirm the workflow actually succeeded, not just that
    it was triggered.

    Args:
        workflow_id: The workflow's id.
        execution_limit: How many recent executions to show (default 5).
    """
    from app.services import n8n_client

    try:
        wf = await n8n_client.get_workflow(workflow_id)
        execs = await n8n_client.list_executions(workflow_id, limit=execution_limit)
        lines = [f"Workflow '{wf.get('name')}' -- {'ACTIVE' if wf.get('active') else 'inactive'}\n"]
        if not execs:
            lines.append("No executions yet.")
        for e in execs:
            status = "error" if e.get("stoppedAt") and e.get("status") == "error" else e.get("status", "?")
            lines.append(f"  [{status}] started {e.get('startedAt')}  (execution id: {e.get('id')})")
        return "\n".join(lines)
    except n8n_client.N8nError as exc:
        return f"Error checking workflow: {exc}"


@mcp_server.tool()
async def list_agents() -> str:
    """List all agents currently registered in Agent Atlas.

    Shows agent IDs organized by layer (control → knowledge → action → platform).
    """
    from app.services.collaboration_bus import list_handlers

    ids = list_handlers()
    if not ids:
        return "No agents currently registered (backend may still be starting)."

    # Group loosely by known layer membership
    groups = {
        "control":  ["orchestrator", "planner", "evaluator"],
        "knowledge": ["knowledge_hub", "memory_agent", "obsidian_brain", "retrieval_agent"],
        "action":   ["action_hub", "code_agent", "automation_agent", "background_runtime"],
        "platform": ["creative_studio", "agent_factory", "guardian", "deployment",
                     "observability", "local_trainer"],
    }
    placed: set[str] = set()
    lines = [f"Agent Atlas — {len(ids)} registered agents\n"]

    for layer, members in groups.items():
        in_layer = [m for m in members if m in ids]
        if in_layer:
            lines.append(f"[{layer.upper()}]")
            for m in in_layer:
                lines.append(f"  • {m}")
            placed.update(in_layer)

    others = [i for i in ids if i not in placed]
    if others:
        lines.append("[OTHER]")
        for o in others:
            lines.append(f"  • {o}")

    return "\n".join(lines)
