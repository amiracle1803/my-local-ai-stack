import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger("agent_atlas.config")

CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


@dataclass
class ModelConfig:
    name: str
    provider: str = "local"       # local | groq
    type: str = "chat"
    endpoint: Optional[str] = None
    model: str = ""
    capabilities: List[str] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.7
    api_key_env: Optional[str] = None


@dataclass
class RoutingConfig:
    discovery_order: List[str] = field(
        default_factory=lambda: ["ollama_local", "lmstudio_local", "groq_powerful", "groq_fast"]
    )
    allow_remote_models: bool = True
    allow_remote_search: bool = True
    default_model: str = ""
    privacy_first: bool = False


class ConfigLoader:
    """
    Loads config/models.yml and config/agents/*.yml into memory.

    Reload safety: _load_models()/_load_agents() each build a fresh dict and
    assign it in one step at the end, instead of mutating the existing class
    dict in place. A prior version mutated in place, so deleting an agent's
    YAML file and reloading left its stale entry in memory forever (the
    handler-registry delete API would "succeed" but the agent kept showing
    up until the process restarted). Building fresh and swapping atomically
    makes that class of bug structurally impossible: whatever key set is on
    disk right now is exactly the key set in memory after load().
    """

    _models: Dict[str, ModelConfig] = {}
    _agents: Dict[str, Any] = {}
    _routing: RoutingConfig = RoutingConfig()
    _loaded: bool = False

    @classmethod
    def load(cls):
        cls._models = cls._read_models()
        cls._agents = cls._read_agents()
        cls._loaded = True
        logger.info("Config loaded: %d models, %d agents", len(cls._models), len(cls._agents))

    @classmethod
    def _read_models(cls) -> Dict[str, ModelConfig]:
        path = CONFIG_DIR / "models.yml"
        if not path.exists():
            logger.warning("models.yml not found at %s -- using defaults", path)
            return {}
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        routing_raw = data.get("routing", {})
        cls._routing = RoutingConfig(
            discovery_order=routing_raw.get(
                "discovery_order",
                ["ollama_local", "lmstudio_local", "groq_powerful", "groq_fast"],
            ),
            allow_remote_models=routing_raw.get("allow_remote_models", True),
            allow_remote_search=routing_raw.get("allow_remote_search", True),
            default_model=routing_raw.get("default_model", ""),
            privacy_first=routing_raw.get("privacy_first", False),
        )

        models: Dict[str, ModelConfig] = {}
        for name, cfg in data.get("models", {}).items():
            endpoint = cfg.get("endpoint")
            env_key = f"AGENT_ATLAS_{name.upper()}_ENDPOINT"
            endpoint = os.getenv(env_key, endpoint)
            models[name] = ModelConfig(
                name=name,
                provider=cfg.get("provider", "local"),
                type=cfg.get("type", "chat"),
                endpoint=endpoint,
                model=cfg.get("model", ""),
                capabilities=cfg.get("capabilities", []),
                max_tokens=cfg.get("max_tokens", 4096),
                temperature=cfg.get("temperature", 0.7),
                api_key_env=cfg.get("api_key_env"),
            )
        return models

    @classmethod
    def _read_agents(cls) -> Dict[str, Any]:
        agents_dir = CONFIG_DIR / "agents"
        if not agents_dir.exists():
            logger.warning("config/agents/ not found")
            return {}
        agents: Dict[str, Any] = {}
        for yml_file in sorted(agents_dir.glob("*.yml")):
            try:
                with open(yml_file, encoding="utf-8") as f:
                    agent_data = yaml.safe_load(f) or {}
                if "id" in agent_data:
                    agents[agent_data["id"]] = agent_data
            except Exception as exc:
                logger.error("Failed to load agent config %s: %s", yml_file, exc)
        return agents

    @classmethod
    def get_model(cls, name: str) -> Optional[ModelConfig]:
        return cls._models.get(name)

    @classmethod
    def get_all_models(cls) -> Dict[str, ModelConfig]:
        return dict(cls._models)

    @classmethod
    def get_agent(cls, agent_id: str) -> Optional[Dict]:
        return cls._agents.get(agent_id)

    @classmethod
    def get_all_agents(cls) -> Dict[str, Any]:
        return dict(cls._agents)

    @classmethod
    def routing(cls) -> RoutingConfig:
        return cls._routing


def load_config():
    """Compatibility entry point mirroring the old module -- some call
    sites import load_config() rather than calling ConfigLoader.load()
    directly."""
    ConfigLoader.load()
    return ConfigLoader
