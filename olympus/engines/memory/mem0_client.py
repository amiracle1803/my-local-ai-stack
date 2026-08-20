"""Mem0-backed durable memory: Ollama for LLM + embeddings, Qdrant for storage.

Mem0 extracts, deduplicates, and updates memories from free-form text using an
LLM, then stores vectors in Qdrant. The registry (registry.py) keeps provenance
for every memory so we can trace it to a user/project/agent/source/evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mem0 import Memory
from mem0.configs.llms.ollama import OllamaConfig
from mem0.llms.ollama import OllamaLLM

from .registry import MemoryRegistry


class _NoThinkOllamaLLM(OllamaLLM):
    """OllamaLLM that disables qwen3 thinking mode.

    qwen3 models emit /think blocks which corrupt mem0's JSON extraction.
    Injecting think=False keeps responses clean.
    """

    def generate_response(
        self,
        messages,
        response_format=None,
        tools=None,
        tool_choice="auto",
        **kwargs,
    ):
        params = {
            "model": self.config.model,
            "messages": messages,
            "think": False,  # disable qwen3 thinking mode
        }
        if response_format and response_format.get("type") == "json_object":
            params["format"] = "json"
            messages = [dict(m) for m in messages]
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\nPlease respond with valid JSON only."
            else:
                messages.append({"role": "user", "content": "Please respond with valid JSON only."})
            params["messages"] = messages
        params["options"] = {
            "temperature": self.config.temperature,
            "num_predict": self.config.max_tokens,
            "top_p": self.config.top_p,
        }
        if tools:
            params["tools"] = tools
        response = self.client.chat(**params)
        return self._parse_response(response, tools)


class Mem0Client:
    def __init__(
        self,
        *,
        llm_model: str = "qwen3:8b",
        llm_base_url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
        embed_base_url: str = "http://localhost:11434",
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection: str = "agent_memories",
        db_path: str | Path = "memory_registry.db",
    ):
        self.registry = MemoryRegistry(db_path)
        config = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": llm_model,
                    "ollama_base_url": llm_base_url,
                    "temperature": 0.1,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": embed_model,
                    "ollama_base_url": embed_base_url,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": collection,
                    "host": qdrant_host,
                    "port": qdrant_port,
                    "embedding_model_dims": 768,  # nomic-embed-text
                },
            },
        }
        self.memory = Memory.from_config(config)
        self.memory.llm = _NoThinkOllamaLLM(
            config=OllamaConfig(
                model=llm_model,
                ollama_base_url=llm_base_url,
            )
        )
        self.collection = collection

    def add(
        self,
        text: str,
        *,
        user_id: str = "",
        project_id: str = "",
        agent_id: str = "",
        source: str = "",
        confidence: float = 1.0,
        evidence: str = "",
    ) -> list[dict[str, Any]]:
        """Store memories extracted from `text`. Returns created memory ids."""
        metadata = {}
        if user_id:
            metadata["user_id"] = user_id
        if agent_id:
            metadata["agent_id"] = agent_id
        result = self.memory.add(text, user_id=user_id, metadata=metadata)
        items = result.get("results", []) if isinstance(result, dict) else result
        created = [m.get("id", "") for m in items if m.get("event") in ("ADD", "UPDATE")]
        for m in items:
            mid = m.get("id", "")
            if mid:
                self.registry.record(
                    mid,
                    m.get("memory", text[:500]),
                    user_id=user_id,
                    project_id=project_id,
                    agent_id=agent_id,
                    source=source,
                    confidence=confidence,
                    evidence=evidence,
                )
        return [{"id": m.get("id"), "memory": m.get("memory"), "event": m.get("event")} for m in items]

    def search(
        self,
        query: str,
        *,
        user_id: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memories by semantic relevance."""
        filters = {k: v for k, v in {"user_id": user_id}.items() if v}
        if not filters:
            users = {r["user_id"] for r in self.registry.all() if r.get("user_id")}
            results: list[dict[str, Any]] = []
            for u in users:
                res = self.memory.search(query, filters={"user_id": u}, limit=limit)
                if isinstance(res, dict):
                    results.extend(res.get("results", []))
                else:
                    results.extend(res)
            return results
        results = self.memory.search(query, filters=filters, limit=limit)
        if isinstance(results, dict):
            return results.get("results", [])
        return results

    def all(self, user_id: str = "") -> list[dict[str, Any]]:
        return self.memory.get_all(user_id=user_id or None)

    def delete(self, memory_id: str) -> None:
        self.memory.delete(memory_id=memory_id)