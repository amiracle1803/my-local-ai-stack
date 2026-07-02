"""
Register all agent handlers with the Collaboration Bus on startup.
"""
import logging

from app.services import collaboration_bus as bus

logger = logging.getLogger("agent_atlas.agents.registry")


def register_all_agents():
    from app.agents.orchestrator import OrchestratorAgent
    from app.agents.planner import PlannerAgent
    from app.agents.evaluator import EvaluatorAgent
    from app.agents.knowledge_hub import KnowledgeHubAgent
    from app.agents.memory_agent import MemoryAgent
    from app.agents.obsidian_brain import ObsidianBrainAgent
    from app.agents.retrieval_agent import RetrievalAgent
    from app.agents.action_hub import ActionHubAgent
    from app.agents.code_agent import CodeAgent
    from app.agents.automation_agent import AutomationAgent
    from app.agents.background_runtime import BackgroundRuntimeAgent
    from app.agents.creative_studio import CreativeStudioAgent
    from app.agents.agent_factory import AgentFactoryAgent
    from app.agents.guardian import GuardianAgent
    from app.agents.deployment import DeploymentAgent
    from app.agents.observability import ObservabilityAgent
    from app.agents.local_trainer import LocalModelTrainerAgent
    from app.agents.hermes_bridge import HermesBridgeAgent

    agents = [
        OrchestratorAgent(),
        PlannerAgent(),
        EvaluatorAgent(),
        KnowledgeHubAgent(),
        MemoryAgent(),
        ObsidianBrainAgent(),
        RetrievalAgent(),
        ActionHubAgent(),
        CodeAgent(),
        AutomationAgent(),
        BackgroundRuntimeAgent(),
        CreativeStudioAgent(),
        AgentFactoryAgent(),
        GuardianAgent(),
        DeploymentAgent(),
        ObservabilityAgent(),
        LocalModelTrainerAgent(),
        HermesBridgeAgent(),
    ]

    for agent in agents:
        bus.register_handler(agent.agent_id, agent.handle_traced)

    logger.info("Registered %d agents.", len(agents))

    from app.services.tools import register_all_tools
    register_all_tools()
