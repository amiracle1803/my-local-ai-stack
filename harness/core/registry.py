"""Registry loader: reads harness/registry/*.yaml (routing.md §7).

Code references roles/tiers only; this module resolves them to concrete model
entries. No model names are hardcoded anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"


@dataclass(frozen=True)
class ModelEntry:
    """One concrete model from models.yaml."""
    id: str
    runtime: str
    endpoint: str
    model: str            # the runtime's own tag (e.g. "qwen2.5:7b")
    tier: str
    capabilities: dict
    defaults: dict
    qualified: bool
    offline_asset: Optional[str]


class RegistryError(RuntimeError):
    """Raised when the registry is missing entries a resolution needs."""


class Registry:
    def __init__(self, models: dict, routing: dict, agents: dict):
        self._raw_models = models
        self.routing = routing
        self.agents = agents.get("agents", {})
        self._tiers: dict[str, list[str]] = models.get("tiers", {})
        self._roles: dict[str, str] = models.get("roles", {})
        self.entries: dict[str, ModelEntry] = {
            mid: _to_entry(mid, spec) for mid, spec in models.get("models", {}).items()
        }

    # --- resolution ------------------------------------------------------

    def tier_candidates(self, tier: str) -> list[ModelEntry]:
        ids = self._tiers.get(tier, [])
        missing = [mid for mid in ids if mid not in self.entries]
        if missing:
            raise RegistryError(f"tier {tier} references unknown models: {missing}")
        return [self.entries[mid] for mid in ids]

    def resolve_tier(self, tier: str) -> ModelEntry:
        """Preferred (first) model for a tier."""
        candidates = self.tier_candidates(tier)
        if not candidates:
            raise RegistryError(f"no models mapped to tier {tier}")
        return candidates[0]

    def entry(self, model_id: str) -> ModelEntry:
        if model_id not in self.entries:
            raise RegistryError(f"unknown model id: {model_id}")
        return self.entries[model_id]

    def role_model(self, role: str) -> ModelEntry:
        mid = self._roles.get(role)
        if mid is None:
            raise RegistryError(f"no model mapped to role {role}")
        return self.entry(mid)

    def siblings(self, model_id: str) -> list[ModelEntry]:
        """Same-tier models other than model_id (ladder rung 2)."""
        entry = self.entry(model_id)
        return [m for m in self.tier_candidates(entry.tier) if m.id != model_id]

    def next_tier(self, tier: str) -> Optional[str]:
        order = ["T0", "T1", "T2", "T3"]
        if tier not in order:
            return None
        idx = order.index(tier)
        for t in order[idx + 1:]:
            if self._tiers.get(t):
                return t
        return None


def _to_entry(mid: str, spec: dict) -> ModelEntry:
    return ModelEntry(
        id=mid,
        runtime=spec["runtime"],
        endpoint=spec["endpoint"],
        model=spec["model"],
        tier=spec.get("tier", ""),
        capabilities=spec.get("capabilities", {}),
        defaults=spec.get("defaults", {}),
        qualified=bool(spec.get("qualified", False)),
        offline_asset=spec.get("offline_asset"),
    )


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise RegistryError(f"registry file missing: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_registry(registry_dir: Path = REGISTRY_DIR) -> Registry:
    return Registry(
        models=_load_yaml(registry_dir / "models.yaml"),
        routing=_load_yaml(registry_dir / "routing.yaml"),
        agents=_load_yaml(registry_dir / "agents.yaml"),
    )
