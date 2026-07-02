"""
Policy engine for the Guardian Agent.
Reads rules from config/policies.yml and evaluates them against tool calls.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger("agent_atlas.policy")

POLICIES_FILE = Path(__file__).parent.parent.parent.parent / "config" / "policies.yml"

_rules: List[Dict[str, Any]] = []
_loaded = False


def load_policies():
    global _rules, _loaded
    if not POLICIES_FILE.exists():
        logger.warning("policies.yml not found at %s", POLICIES_FILE)
        _rules = []
        _loaded = True
        return
    with open(POLICIES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _rules = data.get("rules", [])
    _loaded = True
    logger.info("Loaded %d policy rules.", len(_rules))


def _matches(rule_match: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Return True if all conditions in rule_match are satisfied by context."""
    if not rule_match:
        return True  # empty match = wildcard
    for key, expected in rule_match.items():
        if key == "args_contains":
            args_str = str(context.get("args", ""))
            if expected not in args_str:
                return False
        elif key in context:
            if context[key] != expected:
                return False
        else:
            return False
    return True


def evaluate(tool: str, agent: str = "", args: Any = None) -> Dict[str, Any]:
    """
    Evaluate whether an action is allowed.
    Returns {"allowed": bool, "decision": str, "reason": str, "rule_id": str}.
    """
    if not _loaded:
        load_policies()

    context = {
        "tool": tool,
        "agent": agent,
        "args": args or {},
    }

    for rule in _rules:
        match_spec = rule.get("match", {})
        if _matches(match_spec, context):
            decision = rule.get("decision", "allow")
            reason = rule.get("reason", "")
            rule_id = rule.get("id", "unknown")
            logger.debug("Rule '%s' matched tool='%s' → %s", rule_id, tool, decision)
            return {
                "allowed": decision != "block",
                "decision": decision,
                "reason": reason,
                "rule_id": rule_id,
            }

    return {"allowed": True, "decision": "allow", "reason": "No rules matched.", "rule_id": "default"}
