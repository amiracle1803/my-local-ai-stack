"""
registry.py  --  Explicit list of built-in agent classes to register on
startup. No decorator/auto-discovery magic: add a class here and it's
live.
"""

import logging
from typing import List, Type

from app.agents.base import BaseAgent
from app.agents.evaluator import EvaluatorAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.planner import PlannerAgent
from app.services import collaboration_bus as bus

logger = logging.getLogger("agent_atlas.registry")

AGENT_CLASSES: List[Type[BaseAgent]] = [
    OrchestratorAgent,
    PlannerAgent,
    EvaluatorAgent,
]


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
    return count
