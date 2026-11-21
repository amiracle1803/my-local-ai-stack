"""One way for the pipeline's text stages to call any model the owner has set up (2026-11-21).

A model is a "provider:name" string from stack.toml ([writer] models, [director] models):
  wat:<group>      a W.A.T. gateway model group (Bifrost on the ProDesk, :4000) through W.A.T.'s
                   own client (runtime/llm_router.py) — every key/model configured there
                   (xplabs, NVIDIA, Legion + ProDesk Ollama) with its fallback chain.
                   e.g. wat:xpl-smart, wat:reasoning, wat:xpl-fast
  groq:<model>     Groq direct (GROQ_API_KEY)
  nim:<model>      NVIDIA NIM direct (the NVIDIA key)
  ollama:<model>   local Ollama on this machine
A list is tried in order; the first model that answers wins and is tried first next time.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
WAT_RUNTIME = Path(os.environ.get("WAT_RUNTIME", Path.home() / "Dev" / "wat" / "runtime"))

Chat = Callable[..., str]


def _key(provider: str) -> str:
    from . import director, nim_vision
    return nim_vision._api_key() if provider == "nim" else director._key("GROQ_API_KEY")


def _openai(url: str, key: str, model: str, messages: list[dict], temperature: float, max_tokens: int,
            timeout: int = 300, json_mode: bool = False) -> str:
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "medium"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}",
        "User-Agent": "olympus-pipeline/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (json.load(r)["choices"][0]["message"].get("content") or "").strip()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise RuntimeError(f"{model} HTTP {e.code}") from e
            time.sleep(min(60.0, float(e.headers.get("retry-after") or 20)))
    return ""


def _wat(group: str, messages: list[dict], temperature: float, max_tokens: int) -> str:
    if str(WAT_RUNTIME) not in sys.path:
        sys.path.insert(0, str(WAT_RUNTIME))
    import llm_router  # W.A.T.'s gateway client: key lookup, timeouts, rescue tiers
    return (llm_router.chat(group, messages, max_tokens=max(1024, max_tokens), temperature=temperature) or "").strip()


def call(spec: str, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4000,
         json_mode: bool = False) -> str:
    """One call to one "provider:name" model. Raises on failure."""
    provider, _, name = spec.partition(":")
    if provider == "wat":
        return _wat(name, messages, temperature, max_tokens)
    if provider == "groq":
        return _openai(GROQ_URL, _key("groq"), name, messages, temperature, max_tokens, json_mode=json_mode)
    if provider == "nim":
        return _openai(NIM_URL, _key("nim"), name, messages, temperature, max_tokens, json_mode=json_mode)
    if provider == "ollama":
        from .llm import ollama_generate
        res = ollama_generate("\n\n".join(m["content"] for m in messages), model=name, timeout=900,
                              num_predict=max_tokens, temperature=temperature, think=False)
        return res.text if res else ""
    raise ValueError(f"unknown model provider in {spec!r} (use wat:, groq:, nim:, ollama:)")


def make_chat(specs: list[str], json_mode: bool = False) -> Chat:
    """chat(messages, temperature, max_tokens) over a fallback list; chat.used = the model that answered."""
    order = list(specs)

    def chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 4000) -> str:
        errors = []
        for spec in list(order):
            try:
                text = call(spec, messages, temperature, max_tokens, json_mode)
            except Exception as e:  # noqa: BLE001  (next model)
                errors.append(f"{spec}: {str(e)[:120]}")
                continue
            if text:
                if order[0] != spec:
                    order.remove(spec)
                    order.insert(0, spec)
                chat.used = spec
                return text
            errors.append(f"{spec}: empty reply")
        raise RuntimeError("no model answered: " + "; ".join(errors))

    chat.used = ""
    return chat
