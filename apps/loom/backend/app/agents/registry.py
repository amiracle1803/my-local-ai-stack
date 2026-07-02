"""
registry.py  --  Explicit list of built-in agent classes to register on
startup. No decorator/auto-discovery magic: add a class here and it's
live.

Agents created through the Agent Factory (POST /agents/factory) aren't
in AGENT_CLASSES -- they're just a YAML file. Without a bus handler
they'd show up in the UI and be pingable-looking but every ping/dispatch
would raise NoHandlerError forever. register_generic_agents() closes
that gap: any configured agent without a dedicated Python class gets a
plain llm_call-with-its-own-system-prompt handler instead.
"""

import logging
from typing import Any, List, Type

from app.agents.automation_agent import AutomationAgent
from app.agents.base import BaseAgent
from app.agents.code_agent import CodeAgent
from app.agents.evaluator import EvaluatorAgent
from app.agents.knowledge_hub import KnowledgeHubAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.obsidian_brain import ObsidianBrainAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.planner import PlannerAgent
from app.config.loader import ConfigLoader
from app.models.agent import AgentDefinition
from app.models.message import AgentMessage
from app.services import collaboration_bus as bus

logger = logging.getLogger("agent_atlas.registry")

AGENT_CLASSES: List[Type[BaseAgent]] = [
    OrchestratorAgent,
    PlannerAgent,
    EvaluatorAgent,
    ObsidianBrainAgent,
    MemoryAgent,
    KnowledgeHubAgent,
    CodeAgent,
    AutomationAgent,
]

BUILTIN_AGENT_IDS = frozenset(cls.agent_id for cls in AGENT_CLASSES)


class GenericAgent(BaseAgent):
    """Fallback handler for config-only agents (Agent Factory output):
    just an llm_call using the agent's own system_prompt. No tools, no
    memory, no delegation -- if a factory-created agent needs any of
    that, it needs a real Python class in AGENT_CLASSES instead."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        raw = ConfigLoader.get_agent(agent_id)
        self.definition = AgentDefinition(**raw)

    async def handle(self, message: AgentMessage) -> Any:
        goal = message.payload.get("goal") or message.payload.get("query", "")
        return await self.llm_call(goal, system=self.definition.system_prompt)


def register_generic_agents() -> int:
    """Registers a GenericAgent for every configured agent that isn't
    one of the built-in classes and doesn't already have a handler.
    Called at startup (after the built-ins) and again right after the
    Agent Factory writes a new config, so a new agent is dispatchable
    immediately -- no backend restart needed."""
    count = 0
    for agent_id in ConfigLoader.get_all_agents():
        if agent_id in BUILTIN_AGENT_IDS or bus.has_handler(agent_id):
            continue
        try:
            instance = GenericAgent(agent_id)
        except Exception:
            logger.exception("Failed to construct generic agent '%s' -- skipping", agent_id)
            continue
        bus.register_handler(instance.agent_id, instance.handle_traced)
        count += 1
    if count:
        logger.info("Registered %d generic (factory-created) agent(s)", count)
    return count


def register_all() -> int:
    count = 0
    for cls in AGENT_CLASSES:
        try:
            instance = cls()
        except Exception:
            logger.exception("Failed to construct agent %s -- skipping", cls.__name__)
            continue
        bus.register_handler(instance.agent_id, instance.handle_traced)
        count += 1
    logger.info("Registered %d/%d built-in agents", count, len(AGENT_CLASSES))
    return count + register_generic_agents()
