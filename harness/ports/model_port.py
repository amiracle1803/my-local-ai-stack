"""ModelPort — the single seam between agents and model runtimes (routing.md §7).

Agents pass a ROLE (agent name or tier); the port resolves role -> tier -> concrete
model via the registry (never a hardcoded model name), calls Ollama's native
/api/chat, enforces structured output, walks the fallback ladder, and logs every
call as one JSON line to runs/<task-id>/logs/calls.jsonl.

Fallback ladder (routing.md §5), each rung logged:
  0. primary model, first attempt
  1. same model, repair prompt          (once; schema/format failures only)
  2. same-tier sibling model
  3. tier + 1 (preferred model)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from jsonschema import Draft7Validator

from ..core.registry import ModelEntry, Registry
from ..core.runstate import RUNS_DIR, atomic_write, run_dir

TIER_ORDER = ["T0", "T1", "T2", "T3", "F"]


# --- exceptions ----------------------------------------------------------

class ModelPortError(RuntimeError):
    """Base for all ModelPort failures."""


class ModelTimeout(ModelPortError):
    """The runtime did not respond within the budget."""


class ModelConnectionError(ModelPortError):
    """The runtime endpoint refused the connection / is unreachable."""


class ModelRuntimeError(ModelPortError):
    """The runtime returned a non-2xx / malformed response."""


class LadderExhausted(ModelPortError):
    """Every rung of the fallback ladder failed."""


# --- result --------------------------------------------------------------

@dataclass
class Result:
    ok: bool
    text: str
    model_id: str
    rung: int
    outcome: str
    usage: dict = field(default_factory=dict)
    data: Optional[dict] = None   # parsed+validated JSON when a schema was given


# --- port ----------------------------------------------------------------

class ModelPort:
    def __init__(
        self,
        registry: Registry,
        *,
        runs_dir: Path = RUNS_DIR,
        client: Optional[httpx.Client] = None,
        timeout: float = 120.0,
    ):
        self.registry = registry
        self.runs_dir = runs_dir
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    # --- role resolution -------------------------------------------------

    def resolve(self, role: str) -> tuple[str, ModelEntry]:
        """role -> (tier, preferred ModelEntry). role is a tier (T0..F) or an agent name."""
        tier = role if role in TIER_ORDER else self._agent_tier(role)
        return tier, self.registry.resolve_tier(tier)

    def _agent_tier(self, agent: str) -> str:
        spec = self.registry.agents.get(agent)
        if not spec:
            raise ModelPortError(f"unknown role/agent: {agent}")
        return spec.get("min_tier") or spec.get("tier_default") or "T1"

    # --- public API ------------------------------------------------------

    def generate(
        self,
        role: str,
        messages: list[dict],
        schema: Optional[dict] = None,
        budget: Optional[dict] = None,
        *,
        task_id: str = "T-unassigned",
        agent: Optional[str] = None,
    ) -> Result:
        tier, primary = self.resolve(role)
        agent_name = agent or (role if role not in TIER_ORDER else "unknown")
        validator = Draft7Validator(schema) if schema else None

        for rung, model, msgs, is_repair in self._ladder(tier, primary, messages, schema):
            outcome, text, usage, err, ms = self._attempt(model, msgs, schema, validator)
            self._log(task_id, agent_name, model, msgs, usage, outcome, rung, latency_ms=ms)
            if outcome == "ok":
                data = json.loads(text) if schema else None
                return Result(True, text, model.id, rung, outcome, usage, data)
            # schema-invalid on the primary: allow exactly one same-model repair (rung 1)
            if outcome == "schema-invalid" and not is_repair and rung == 0:
                repair_msgs = _repair_messages(messages, text, err)
                r_out, r_text, r_usage, _, r_ms = self._attempt(
                    model, repair_msgs, schema, validator)
                self._log(task_id, agent_name, model, repair_msgs, r_usage, r_out, 1,
                          latency_ms=r_ms)
                if r_out == "ok":
                    return Result(True, r_text, model.id, 1, r_out, r_usage,
                                  json.loads(r_text))
        raise LadderExhausted(
            f"all ladder rungs failed for role={role} tier={tier} task={task_id}")

    # --- ladder construction --------------------------------------------

    def _ladder(self, tier, primary, messages, schema):
        """Yield (rung, model, messages, is_repair). Rung numbers per routing.md §5."""
        yield 0, primary, messages, False                       # first attempt
        for sib in self.registry.siblings(primary.id):          # rung 2: same-tier sibling
            yield 2, sib, messages, False
        nxt = self.registry.next_tier(tier)                     # rung 3: tier + 1
        if nxt:
            try:
                yield 3, self.registry.resolve_tier(nxt), messages, False
            except Exception:
                return

    # --- one HTTP attempt ------------------------------------------------

    def _attempt(self, model, messages, schema, validator):
        """Return (outcome, text, usage, error_detail, latency_ms). Model failures the
        ladder should absorb become an outcome string, not an exception."""
        start = time.monotonic()
        try:
            text, usage = self._call_ollama(model, messages, schema)
        except ModelTimeout:
            return "timeout", "", {}, "timeout", _ms(start)
        except ModelConnectionError:
            return "connection-refused", "", {}, "connection-refused", _ms(start)
        except ModelRuntimeError as exc:
            return "runtime-error", "", {}, str(exc), _ms(start)
        ms = _ms(start)

        if validator is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                return "schema-invalid", text, usage, f"not JSON: {exc}", ms
            errors = sorted(validator.iter_errors(parsed), key=lambda e: str(e.path))
            if errors:
                return "schema-invalid", text, usage, "; ".join(e.message for e in errors[:3]), ms
        return "ok", text, usage, "", ms

    def _call_ollama(self, model: ModelEntry, messages, schema) -> tuple[str, dict]:
        payload: dict[str, Any] = {
            "model": model.model,
            "messages": messages,
            "stream": False,
            "options": _options(model.defaults),
        }
        if schema is not None:
            payload["format"] = "json"
        url = model.endpoint.rstrip("/") + "/api/chat"
        try:
            resp = self._http().post(url, json=payload)
        except httpx.ConnectError as exc:
            raise ModelConnectionError(f"{model.id}: {exc}") from exc
        except (httpx.TimeoutException,) as exc:
            raise ModelTimeout(f"{model.id}: {exc}") from exc
        if resp.status_code != 200:
            raise ModelRuntimeError(f"{model.id}: HTTP {resp.status_code} {resp.text[:200]}")
        body = resp.json()
        text = body.get("message", {}).get("content", "")
        usage = {
            "tokens_in": body.get("prompt_eval_count", 0),
            "tokens_out": body.get("eval_count", 0),
        }
        return text, usage

    # --- logging ---------------------------------------------------------

    def _log(self, task_id, agent, model, messages, usage, outcome, rung, *, latency_ms=None):
        line = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "agent": agent,
            "model_id": model.id,
            "prompt_hash": _prompt_hash(messages),
            "tokens_in": usage.get("tokens_in", 0),
            "tokens_out": usage.get("tokens_out", 0),
            "latency_ms": latency_ms,
            "outcome": outcome,
            "rung": rung,
        }
        log_path = run_dir(task_id, self.runs_dir) / "logs" / "calls.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(line) + "\n")


# --- helpers -------------------------------------------------------------

def _ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)


def _options(defaults: dict) -> dict:
    opts: dict[str, Any] = {}
    if "temperature" in defaults:
        opts["temperature"] = defaults["temperature"]
    if "num_ctx" in defaults:
        opts["num_ctx"] = defaults["num_ctx"]
    return opts


def _prompt_hash(messages: list[dict]) -> str:
    blob = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _repair_messages(original: list[dict], bad_output: str, error: str) -> list[dict]:
    return list(original) + [
        {"role": "assistant", "content": bad_output},
        {"role": "user",
         "content": f"Your previous reply failed schema validation: {error}. "
                    f"Return ONLY valid JSON that satisfies the schema. No prose."},
    ]
