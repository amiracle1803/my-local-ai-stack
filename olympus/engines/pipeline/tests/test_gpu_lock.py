"""File-based GPU ownership lock (gpu_lock) -- cross-stage contention guard."""
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.gpu_lock import GpuLock, GpuLockError, GpuBatch, _PROCESS_LOCK


@pytest.fixture
def lock_root(tmp_path):
    return tmp_path / "gpu-locks"


@pytest.fixture
def mock_comfy():
    """Mock ComfyClient with unload_ollama and free methods."""
    comfy = MagicMock()
    comfy.unload_ollama = MagicMock()
    comfy.free = MagicMock()
    comfy.healthy = MagicMock(return_value=True)
    return comfy


def test_acquire_and_release(lock_root):
    lock = GpuLock("stage3c", lock_root)
    assert lock.acquire() is True
    assert lock.held
    assert (lock_root / "gpu.lock").exists()
    lock.release()
    assert not lock.held
    assert not (lock_root / "gpu.lock").exists()


def test_double_acquire_refuses(lock_root):
    a = GpuLock("stage-a", lock_root)
    b = GpuLock("stage-b", lock_root)
    assert a.acquire() is True
    assert b.acquire() is False  # live lease
    a.release()
    assert b.acquire() is True  # available now
    b.release()


def test_stale_lease_stolen(lock_root):
    old = lock_root / "gpu.lock"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(f"crashed-stage\n{time.time() - 600:.3f}\n")
    lock = GpuLock("new-stage", lock_root)
    # stale (600s > default 300s timeout) -> steal
    assert lock.acquire() is True
    assert lock.held
    lock.release()


def test_context_manager_raises_when_held(lock_root):
    a = GpuLock("stage-a", lock_root)
    b = GpuLock("stage-b", lock_root)
    a.acquire()
    with pytest.raises(GpuLockError, match="GPU is owned"):
        with b:
            pass
    a.release()


def test_context_manager_ok_when_free(lock_root):
    lock = GpuLock("ok-stage", lock_root)
    with lock:
        assert lock.held
    assert not lock.held
    assert not (lock_root / "gpu.lock").exists()


def test_release_idempotent(lock_root):
    lock = GpuLock("idempotent", lock_root)
    lock.release()  # not held -> no error
    lock.acquire()
    lock.release()
    lock.release()  # already released -> no error
    assert not lock.held


# --- GpuBatch (M-AP-4) tests ---


def test_gpu_batch_acquire_release(lock_root, mock_comfy):
    """GpuBatch acquires file lease, calls unload_ollama, and releases both."""
    batch = GpuBatch("stage3b", mock_comfy, lock_root=lock_root)
    assert batch.acquire() is True
    assert batch.held
    assert (lock_root / "gpu.lock").exists()
    mock_comfy.unload_ollama.assert_called_once()
    batch.release()
    assert not batch.held
    assert not (lock_root / "gpu.lock").exists()
    mock_comfy.free.assert_called_once()


def test_gpu_batch_double_acquire_refuses(lock_root, mock_comfy):
    """Second GpuBatch for same lock_root should fail when first holds it."""
    a = GpuBatch("stage-a", mock_comfy, lock_root=lock_root)
    b = GpuBatch("stage-b", mock_comfy, lock_root=lock_root)
    assert a.acquire() is True
    assert b.acquire() is False  # file lease held
    a.release()
    assert b.acquire() is True  # available now
    b.release()


def test_gpu_batch_stale_lease_stolen(lock_root, mock_comfy):
    """GpuBatch steals stale file lease."""
    old = lock_root / "gpu.lock"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(f"crashed-stage\n{time.time() - 600:.3f}\n")
    batch = GpuBatch("new-stage", mock_comfy, lock_root=lock_root)
    assert batch.acquire() is True
    assert batch.held
    batch.release()


def test_gpu_batch_context_manager(lock_root, mock_comfy):
    """GpuBatch works as context manager with unload_ollama on enter, free on exit."""
    with GpuBatch("ok-stage", mock_comfy, lock_root=lock_root) as batch:
        assert batch.held
        mock_comfy.unload_ollama.assert_called_once()
    assert not batch.held
    mock_comfy.free.assert_called_once()


def test_gpu_batch_context_manager_raises_when_held(lock_root, mock_comfy):
    """Context manager raises GpuLockError when another batch holds the lock."""
    a = GpuBatch("stage-a", mock_comfy, lock_root=lock_root)
    a.acquire()
    b = GpuBatch("stage-b", mock_comfy, lock_root=lock_root)
    with pytest.raises(GpuLockError, match="GPU is owned"):
        with b:
            pass
    a.release()


def test_gpu_batch_in_process_lock(lock_root, mock_comfy):
    """GpuBatch uses in-process threading.Lock for thread safety."""
    # First batch acquires both locks
    a = GpuBatch("stage-a", mock_comfy, lock_root=lock_root)
    assert a.acquire() is True
    
    # Second batch in SAME process should block on _PROCESS_LOCK
    # We can't easily test blocking in a unit test, but we can verify
    # the lock is held by checking _PROCESS_LOCK.locked()
    assert _PROCESS_LOCK.locked()
    
    a.release()
    assert not _PROCESS_LOCK.locked()
    
    # Now second batch should work
    b = GpuBatch("stage-b", mock_comfy, lock_root=lock_root)
    assert b.acquire() is True
    b.release()


def test_gpu_batch_release_idempotent(lock_root, mock_comfy):
    """GpuBatch.release() is idempotent."""
    batch = GpuBatch("idempotent", mock_comfy, lock_root=lock_root)
    batch.release()  # not held -> no error
    batch.acquire()
    batch.release()
    batch.release()  # already released -> no error
    assert not batch.held
    # free() should only be called once (on the actual release)
    assert mock_comfy.free.call_count == 1