"""Tests for ModelRouter routing logic."""
import pytest
from unittest.mock import patch, MagicMock

from app.models.task import TaskDescriptor
from app.services.model_router import ModelRouter
from app.config.loader import ConfigLoader


def _make_router() -> ModelRouter:
    return ModelRouter()


def test_private_task_stays_local(monkeypatch):
    router = _make_router()
    task = TaskDescriptor(goal="secret", privacy_level="private", difficulty="normal")
    with patch("app.services.model_router.build_client") as mock_build:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        result = router.choose(task)
    assert result is mock_client


def test_hard_task_with_remote_disabled_uses_local(monkeypatch):
    router = _make_router()
    # Config already has allow_remote_models=False from conftest
    task = TaskDescriptor(goal="write a compiler", difficulty="hard", privacy_level="mixed")
    with patch("app.services.model_router.build_client") as mock_build:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        result = router.choose(task)
    assert result is mock_client


def test_local_only_env_blocks_remote(monkeypatch):
    monkeypatch.setenv("LOCAL_ONLY", "true")
    router = _make_router()
    task = TaskDescriptor(goal="research", requires_fresh_web=True, privacy_level="public")
    with patch("app.services.model_router.build_client") as mock_build:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        result = router.choose(task)
    # Must not call perplexity or claude — should fall through to local
    assert result is mock_client


def test_no_local_model_raises():
    router = _make_router()
    task = TaskDescriptor(goal="test", privacy_level="private")
    with patch("app.services.model_router.build_client", return_value=None):
        with pytest.raises(RuntimeError, match="No local model available"):
            router.choose(task)
