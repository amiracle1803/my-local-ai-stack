"""PipelineLLM -- the shared LLM layer (design 5.1).

Every stage's LLM traffic goes through this module:

- Talks to Ollama's ``/api/chat`` at ``http://127.0.0.1:11434``.
- Model roles ("script" / "vision" / "default") resolve from
  ``pipeline.toml``'s ``[models]`` table via :class:`~pipeline.config.PipelineConfig`.
- Prompts are versioned ``.md`` files: YAML frontmatter carries call params
  (``temperature``, optional ``max_tokens``); the body is a ``str.format``
  template rendered against a caller-supplied context dict.
- :meth:`PipelineLLM.complete_json` enforces ``format: json`` + Pydantic
  validation, with a 2-retry repair loop that feeds the validation error
  back to the model. Raw failures are persisted under the project's
  ``logs/`` directory for postmortem.
- :meth:`PipelineLLM.complete_text` is the raw-prose counterpart (Pass 2
  scene writing, critique, revise).
- A token-budget guard trims the *context* values passed to the template --
  never the instruction text baked into the prompt file itself.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import frontmatter
import requests
from pydantic import BaseModel, ValidationError

from .config import PipelineConfig

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
KEEP_ALIVE_S = 300  # design 5.1 -- stages 0-2 keep the model warm between calls

# No tokenizer dependency for the budget guard: ~4 chars/token is a standard
# rough estimate, good enough for a soft trim guard (not a hard limit).
CHARS_PER_TOKEN = 4
DEFAULT_TOKEN_BUDGET = 6000  # design 5.1

_MAX_JSON_ATTEMPTS = 3  # 1 initial call + 2 repair retries


class LLMCallError(RuntimeError):
    """Raised when an Ollama call fails (transport error or repair loop exhausted)."""


@dataclass
class PromptTemplate:
    """A parsed prompt file: YAML frontmatter (call params) + body template."""

    temperature: float
    body: str
    max_tokens: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "PromptTemplate":
        post = frontmatter.load(str(path))
        meta = dict(post.metadata)
        return cls(
            temperature=float(meta.get("temperature", 0.3)),
            max_tokens=meta.get("max_tokens"),
            body=post.content,
            meta=meta,
        )

    def render(self, context: dict[str, Any]) -> str:
        """Fill ``{placeholders}`` in the body from ``context``.

        Uses plain ``str.format`` so a missing placeholder raises ``KeyError``
        loudly rather than silently shipping an unfilled instruction to the
        model.
        """
        return self.body.format(**context)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


class PipelineLLM:
    """Ollama chat client with prompt templates, JSON-schema enforcement, and
    a token-budget guard. One instance is normally shared for a whole stage
    run so ``keep_alive`` keeps the model resident between calls.
    """

    def __init__(
        self,
        config: PipelineConfig,
        *,
        prompts_dir: str | Path,
        logs_dir: str | Path | None = None,
        base_url: str = DEFAULT_OLLAMA_URL,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        num_ctx: int | None = None,
        request_timeout: float = 300.0,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.prompts_dir = Path(prompts_dir)
        self.logs_dir = Path(logs_dir) if logs_dir is not None else None
        self.base_url = base_url.rstrip("/")
        self.token_budget = token_budget
        # num_ctx: Ollama's vram-based default (4096) is too small for the
        # stage 0-2 prompts + their JSON output -- the pipeline now passes an
        # explicit context window (stack.toml [ollama] num_ctx, default 16384).
        self.num_ctx = num_ctx if num_ctx is not None else getattr(config, "num_ctx", 16384)
        self.request_timeout = request_timeout
        self._session = session or requests.Session()

    # ---- model role resolution ------------------------------------------
    def _model_for_role(self, role: str) -> str:
        m = self.config.models
        roles = {"script": m.llm_script, "vision": m.llm_vision, "default": m.llm_default}
        if role not in roles:
            raise ValueError(f"unknown model role {role!r}; want one of {list(roles)}")
        return roles[role]

    # ---- token-budget guard ----------------------------------------------
    def _budget_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Trim long string/list-of-string context values to fit
        ``token_budget``. Short scalar values (ids, numbers, flags) are left
        untouched; this only shrinks the bulky "evidence" style entries
        (chunks of prior text, character lists, etc.) -- never the prompt's
        own instruction text, which lives in the template body, not here.
        """
        char_budget = self.token_budget * CHARS_PER_TOKEN
        total = sum(len(_stringify(v)) for v in context.values())
        if total <= char_budget:
            return context

        trimmed = dict(context)
        # Trim the largest string/list values first, proportionally, until
        # the total fits (or nothing left worth trimming).
        sizes = sorted(
            ((k, len(_stringify(v))) for k, v in context.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )
        overflow = total - char_budget
        for key, size in sizes:
            if overflow <= 0:
                break
            if size < 200:  # not worth trimming small scalars
                continue
            value = trimmed[key]
            cut = min(size, overflow)
            keep = max(size - cut, 200)
            if isinstance(value, list):
                joined = " ".join(str(v) for v in value)
                trimmed[key] = joined[:keep] + " ...[trimmed for token budget]"
            elif isinstance(value, str):
                trimmed[key] = value[:keep] + " ...[trimmed for token budget]"
            else:
                continue
            overflow -= cut - len(" ...[trimmed for token budget]")
        return trimmed

    # ---- transport ---------------------------------------------------------
    def _chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        format_json: bool,
        max_tokens: int | None,
    ) -> str:
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        if self.num_ctx:
            # Explicit context window (stack.toml [ollama] num_ctx) -- without
            # this Ollama falls back to its vram-based default (4096 on 8GB),
            # which is smaller than the prompt + output and either truncates the
            # input or errors out ("context length too small"). Also clamp
            # num_predict so the total never exceeds the window, regardless of
            # what a prompt file requests.
            options["num_ctx"] = self.num_ctx
            est_input = sum(len(m.get("content", "")) // CHARS_PER_TOKEN + 1 for m in messages)
            reserve = min(2048, max(256, self.num_ctx // 8))
            avail = self.num_ctx - est_input - reserve
            requested = options.get("num_predict")
            if requested is None or requested > avail:
                options["num_predict"] = max(16, avail)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": KEEP_ALIVE_S,
            "think": False,  # original spec: all stage 0-2 qwen3:8b calls run think:false;
            # harmless no-op for non-thinking models (llama3.1:8b) -- verified against
            # a live Ollama instance rather than assumed.
            "options": options,
        }
        if format_json:
            payload["format"] = "json"

        resp = self._session.post(
            f"{self.base_url}/api/chat", json=payload, timeout=self.request_timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]

    # ---- failure logging -----------------------------------------------
    def _save_failure(self, stage_hint: str, prompt_file: str, raw: str, error: str) -> Path | None:
        if self.logs_dir is None:
            return None
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        path = self.logs_dir / f"llm_failure_{stage_hint}_{_now_ts()}.json"
        path.write_text(
            json.dumps(
                {"prompt_file": prompt_file, "error": error, "raw": raw},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.error("LLM call failed (%s); raw output saved to %s", prompt_file, path)
        return path

    # ---- public API ------------------------------------------------------
    def complete_json(
        self,
        prompt_file: str | Path,
        context: dict[str, Any],
        schema: type[T],
        *,
        role: str = "script",
        stage_hint: str = "stage",
    ) -> T:
        """Render ``prompt_file`` against ``context``, call Ollama with
        ``format: json``, and validate the response against ``schema``.

        On a JSON-decode or Pydantic validation failure, up to two repair
        retries are made: the previous raw output plus the validation error
        are fed back to the model, asking for corrected JSON only. If all
        attempts fail, the last raw output is saved under ``logs/`` and
        :class:`LLMCallError` is raised.
        """
        tmpl = PromptTemplate.load(self.prompts_dir / prompt_file)
        rendered = tmpl.render(self._budget_context(context))
        model = self._model_for_role(role)
        base_messages = [{"role": "user", "content": rendered}]

        last_raw = ""
        last_error = ""
        for attempt in range(_MAX_JSON_ATTEMPTS):
            if attempt == 0:
                messages = base_messages
            else:
                messages = base_messages + [
                    {"role": "assistant", "content": last_raw},
                    {
                        "role": "user",
                        "content": (
                            "That response was not valid JSON for the required schema.\n"
                            f"Validation error: {last_error}\n\n"
                            "Return ONLY corrected JSON matching the schema. "
                            "No prose, no markdown code fences."
                        ),
                    },
                ]
            try:
                raw = self._chat(
                    model=model,
                    messages=messages,
                    temperature=tmpl.temperature,
                    format_json=True,
                    max_tokens=tmpl.max_tokens,
                )
            except requests.RequestException as exc:
                last_raw, last_error = "", str(exc)
                logger.warning("complete_json transport error (attempt %d): %s", attempt, exc)
                continue

            last_raw = raw
            try:
                # Extract JSON from markdown code fences if present
                json_text = _extract_json(raw)
                data = json.loads(json_text)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)
                logger.warning(
                    "complete_json validation failed (attempt %d/%d): %s",
                    attempt + 1,
                    _MAX_JSON_ATTEMPTS,
                    last_error,
                )

        self._save_failure(stage_hint, str(prompt_file), last_raw, last_error)
        raise LLMCallError(
            f"complete_json failed after {_MAX_JSON_ATTEMPTS} attempts "
            f"({prompt_file}): {last_error}"
        )

    def complete_text(
        self,
        prompt_file: str | Path,
        context: dict[str, Any],
        *,
        role: str = "script",
        stage_hint: str = "stage",
    ) -> str:
        """Render ``prompt_file`` against ``context`` and return raw prose
        (no JSON enforcement) -- used for scene prose, critique, and revise.
        """
        tmpl = PromptTemplate.load(self.prompts_dir / prompt_file)
        rendered = tmpl.render(self._budget_context(context))
        model = self._model_for_role(role)
        messages = [{"role": "user", "content": rendered}]
        try:
            return self._chat(
                model=model,
                messages=messages,
                temperature=tmpl.temperature,
                format_json=False,
                max_tokens=tmpl.max_tokens,
            )
        except requests.RequestException as exc:
            self._save_failure(stage_hint, str(prompt_file), "", str(exc))
            raise LLMCallError(f"complete_text failed ({prompt_file}): {exc}") from exc


def _extract_json(text: str) -> str:
    """Extract JSON from text that may contain markdown code fences."""
    text = text.strip()
    # Handle ```json ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            # Find the closing fence; if the output was truncated (no closing
            # fence), still strip the opening fence line and keep the rest.
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "```":
                    return "\n".join(lines[1:i])
            return "\n".join(lines[1:])
    return text


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)
