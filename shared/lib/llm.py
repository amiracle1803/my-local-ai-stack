"""
llm.py  --  A tiny, forgiving wrapper around the local Ollama model.

Why this exists:
  - Every project calls the model the same way, so the connection details,
    retries, and "is Ollama even running?" check live in ONE place.
  - If something is wrong (Ollama not started, model not pulled) you get a
    plain-English message telling you exactly how to fix it, instead of a
    stack trace.

Ollama exposes an OpenAI-compatible API, so we use the standard `openai`
Python client and just point it at http://localhost:11434/v1.
"""

from __future__ import annotations
import sys
import time

import requests

from .config import load_config

CFG = load_config()


# --------------------------------------------------------------------------
# Health check
# --------------------------------------------------------------------------
def ollama_up() -> bool:
    """Return True if the Ollama server answers."""
    try:
        r = requests.get(CFG["ollama_native_url"] + "/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def installed_models() -> list[str]:
    try:
        r = requests.get(CFG["ollama_native_url"] + "/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def require_ollama(model: str | None = None) -> None:
    """
    Stop the program with a helpful message if Ollama isn't ready.
    Call this at the top of any script that needs the model.
    """
    model = model or CFG["chat_model"]
    if not ollama_up():
        print(
            "\n[!] Ollama does not seem to be running.\n"
            "    Fix:\n"
            "      1. Make sure Ollama is installed:  https://ollama.com/download\n"
            "      2. Start it (open the Ollama app, or run `ollama serve`).\n"
            f"      3. Test it:  curl {CFG['ollama_native_url']}/api/tags\n",
            file=sys.stderr,
        )
        sys.exit(2)

    have = installed_models()
    # model names can be "llama3.1:8b" or "llama3.1" – match loosely
    if have and not any(m == model or m.startswith(model.split(":")[0]) for m in have):
        print(
            f"\n[!] The model '{model}' is not downloaded yet.\n"
            f"    Fix:  ollama pull {model}\n"
            f"    (Models currently available: {', '.join(have) or 'none'})\n",
            file=sys.stderr,
        )
        sys.exit(3)


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------
def get_client():
    """Return an OpenAI client pointed at the local Ollama server."""
    from openai import OpenAI  # imported lazily so config.py works without openai
    return OpenAI(base_url=CFG["ollama_base_url"], api_key="ollama")


def chat(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.4,
    max_retries: int = 3,
    **kwargs,
) -> str:
    """
    Send chat messages to the local model and return the text reply.
    Retries with exponential backoff on transient errors.
    """
    model = model or CFG["chat_model"]
    client = get_client()
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                timeout=CFG["request_timeout"],
                **kwargs,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = 2 ** (attempt - 1)
            print(f"[llm] attempt {attempt}/{max_retries} failed: {exc} -> retry in {wait}s")
            time.sleep(wait)

    raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_error}")


def ask(prompt: str, system: str | None = None, **kwargs) -> str:
    """Convenience one-shot helper: ask(prompt) -> reply text."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, **kwargs)


if __name__ == "__main__":
    # Quick manual test:  python shared/lib/llm.py
    require_ollama()
    print(ask("Reply with the single word: pong"))
