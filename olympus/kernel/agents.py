"""Agent registry: agents are .md files with YAML frontmatter in agents/.

Frontmatter schema (see hermes local-agent-hub-ops skill):
    id, name, domain, model (a ROLE, not a model name), keywords, description
The markdown body below the frontmatter is the agent's system prompt.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field, asdict

import frontmatter

from .config import AGENTS_DIR, load_config


@dataclass
class Agent:
    id: str
    name: str
    domain: str = "general"
    model: str = "worker"
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    system_prompt: str = ""

    def to_public(self) -> dict:
        d = asdict(self)
        d.pop("system_prompt")
        return d


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> int:
        agents: dict[str, Agent] = {}
        AGENTS_DIR.mkdir(exist_ok=True)
        for path in sorted(AGENTS_DIR.glob("*.md")):
            try:
                post = frontmatter.load(path)
            except Exception:
                continue  # a malformed file must not take the registry down
            aid = str(post.get("id") or path.stem)
            keywords = post.get("keywords") or ""
            if isinstance(keywords, str):
                keywords = [k.strip().lower() for k in keywords.split(",") if k.strip()]
            agents[aid] = Agent(
                id=aid,
                name=str(post.get("name") or aid.title()),
                domain=str(post.get("domain") or "general"),
                model=str(post.get("model") or "worker"),
                keywords=keywords,
                description=str(post.get("description") or ""),
                system_prompt=post.content.strip(),
            )
        with self._lock:
            self._agents = agents
        return len(agents)

    def get(self, aid: str) -> Agent | None:
        with self._lock:
            return self._agents.get(aid)

    def all(self) -> list[Agent]:
        with self._lock:
            return list(self._agents.values())

    def count(self) -> int:
        with self._lock:
            return len(self._agents)

    def route(self, text: str) -> Agent:
        """Pick the agent whose keywords best match the task text.

        Falls back to 'scribe' (or any agent) when nothing matches.
        """
        words = set(re.findall(r"[a-z0-9']+", text.lower()))
        best, best_score = None, 0
        for agent in self.all():
            score = sum(1 for k in agent.keywords if k in words or k in text.lower())
            if score > best_score:
                best, best_score = agent, score
        if best:
            return best
        return self.get("scribe") or self.all()[0]

    def create(self, aid: str, name: str, domain: str, model: str,
               keywords: str, description: str, system_prompt: str) -> Agent:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", aid):
            raise ValueError(f"invalid agent id: {aid!r}")
        path = AGENTS_DIR / f"{aid}.md"
        if path.exists():
            raise FileExistsError(f"agent '{aid}' already exists")
        post = frontmatter.Post(
            system_prompt,
            id=aid, name=name, domain=domain, model=model,
            keywords=keywords, description=description,
        )
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        self.reload()
        agent = self.get(aid)
        assert agent is not None
        return agent

    def delete(self, aid: str) -> None:
        core = load_config()["kernel"]["core_agents"]
        if aid in core:
            raise PermissionError(f"'{aid}' is a core agent and cannot be deleted")
        path = AGENTS_DIR / f"{aid}.md"
        if not path.exists():
            raise FileNotFoundError(aid)
        path.unlink()
        self.reload()
