"""Tests for the Guardian policy engine."""
import pytest
import yaml
from pathlib import Path

import app.services.policy_engine as engine


@pytest.fixture(autouse=True)
def reset_engine():
    engine._rules = []
    engine._loaded = False
    yield
    engine._rules = []
    engine._loaded = False


def _load_inline(rules: list):
    engine._rules = rules
    engine._loaded = True


def test_block_rule_matched():
    _load_inline([
        {"id": "block_rm", "match": {"tool": "shell_exec", "args_contains": "rm -rf"},
         "decision": "block", "reason": "Dangerous."},
    ])
    result = engine.evaluate("shell_exec", args={"cmd": "rm -rf /tmp/test"})
    assert result["allowed"] is False
    assert result["decision"] == "block"
    assert result["rule_id"] == "block_rm"


def test_allow_rule_matched():
    _load_inline([
        {"id": "allow_read", "match": {"tool": "file_read"}, "decision": "allow"},
    ])
    result = engine.evaluate("file_read")
    assert result["allowed"] is True


def test_default_allow_when_no_rules():
    _load_inline([])
    result = engine.evaluate("unknown_tool")
    assert result["allowed"] is True


def test_first_match_wins():
    _load_inline([
        {"id": "block_all_shell", "match": {"tool": "shell_exec"}, "decision": "block", "reason": "Shell blocked."},
        {"id": "allow_safe", "match": {"tool": "shell_exec"}, "decision": "allow"},
    ])
    result = engine.evaluate("shell_exec")
    assert result["allowed"] is False
    assert result["rule_id"] == "block_all_shell"


def test_warn_decision_is_allowed():
    _load_inline([
        {"id": "warn_http", "match": {"tool": "http_get"}, "decision": "warn", "reason": "Check intent."},
    ])
    result = engine.evaluate("http_get")
    assert result["allowed"] is True
    assert result["decision"] == "warn"


def test_loads_policies_yml(tmp_path, monkeypatch):
    pol_file = tmp_path / "policies.yml"
    pol_file.write_text(yaml.dump({"rules": [
        {"id": "test_block", "match": {"tool": "bad_tool"}, "decision": "block", "reason": "Testing."}
    ]}))
    monkeypatch.setattr(engine, "POLICIES_FILE", pol_file)
    engine._loaded = False
    engine.load_policies()
    result = engine.evaluate("bad_tool")
    assert result["allowed"] is False
