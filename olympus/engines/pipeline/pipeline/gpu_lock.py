"""File-based GPU ownership lock + in-process batch context (AGENTS.md GPU scheduling rule).

Ollama and ComfyUI must NEVER do GPU work simultaneously on the 8GB card --
they OOM each other. A stage that owns the GPU (stage3b panels, stage3c LTX,
stage1r refs) must hold this lock for the duration of its GPU phase so a
concurrent run (another terminal, a second agent) cannot start an Ollama or
ComfyUI job in the same window and burn the card into OOM-retry loops.

Deliberately dumb and dependency-free: an atomic ``os.open(O_CREAT|O_EXCL)``
lease file with a stale-lease timeout. Not cross-process-safe beyond a single
host, which is exactly the scope needed here.

M-AP-4 (2026-08-09): ``GpuBatch`` context manager wraps the file lease with
in-process ``threading.Lock`` and guarantees the GPU scheduling sequence:
  __enter__  -> file lease acquire + comfy.unload_ollama()
  __exit__   -> comfy.free() + file lease release

The kernel's ``pipeline_run_stage`` worker acquires the same lock on its
thread if it's about to call any LLM Ollama traffic during a stage that
could be GPU-heavy.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOCK_ROOT = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "pipeline-gpu"
_LEASE_TIMEOUT_S = 300.0  # a crashed stage releases its lease after 5 min

# In-process mutual exclusion for GPU batches (same process, different threads)
_PROCESS_LOCK = threading.Lock()


class GpuLockError(RuntimeError):
    """The GPU is owned by another stage/process -- do not generate."""


class GpuLock:
    """Acquire/release the GPU lease. Usable as a context manager."""

    def __init__(self, owner: str, lock_root: Path | None = None):
        self.owner = owner
        self._root = lock_root or _LOCK_ROOT
        self._path = self._root / "gpu.lock"
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self, *, wait_s: float = 0.0, timeout_s: float = _LEASE_TIMEOUT_S) -> bool:
        """Take the lease. Returns True on success, False if a live owner
        holds it (unless ``wait_s`` > 0, in which case it retries up to
        ``wait_s`` before giving up). Stale leases (older than
        ``timeout_s``) are stolen so a crashed stage never wedges the card."""
        self._root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + wait_s
        while True:
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(f"{self.owner}\n{time.time():.3f}\n")
                self._held = True
                logger.info("GPU lock acquired by %s", self.owner)
                return True
            except FileExistsError:
                holder = self._read_lock()
                age = time.time() - holder.get("ts", time.time())
                if age > timeout_s:
                    logger.warning(
                        "GPU lock stale (%s held by %s for %.0fs) - stealing",
                        self._path.name, holder.get("owner"), age,
                    )
                    self._path.unlink(missing_ok=True)
                    continue
                if time.monotonic() >= deadline:
                    logger.warning(
                        "GPU lock held by %s (age %.0fs) - %s standing down",
                        holder.get("owner"), age, self.owner,
                    )
                    return False
                time.sleep(0.5)

    def release(self) -> None:
        if not self._held:
            return
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass
        self._held = False
        logger.info("GPU lock released by %s", self.owner)

    def _read_lock(self) -> dict[str, str]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            return {"owner": lines[0] if lines else "?", "ts": float(lines[1]) if len(lines) > 1 else 0.0}
        except (OSError, ValueError):
            return {"owner": "?", "ts": 0.0}

    def __enter__(self) -> "GpuLock":
        if not self.acquire():
            raise GpuLockError(f"GPU is owned by another stage; cannot run {self.owner}")
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class GpuBatch:
    """Context manager for a single GPU batch (M-AP-4).

    Guarantees the GPU scheduling sequence:
      1. Acquires in-process thread lock (blocks other threads in same process)
      2. Acquires cross-process file lease (blocks other processes/terminals)
      3. Calls comfy.unload_ollama() to evict Ollama models from VRAM
      4. Yields to caller for GPU work
      5. Calls comfy.free() to clear ComfyUI models from VRAM
      6. Releases file lease
      7. Releases in-process thread lock

    Usage:
        with GpuBatch("stage3b", comfy_client) as batch:
            # GPU work here (ComfyClient.generate calls)
            paths = comfy.generate(...)

    The kernel's pipeline_run_stage worker should also wrap any Ollama LLM
    calls during GPU-heavy stages with this same context manager.
    """

    def __init__(
        self,
        owner: str,
        comfy_client: "ComfyClient",
        *,
        lock_root: Optional[Path] = None,
        wait_s: float = 0.0,
        timeout_s: float = 300.0,
    ):
        self.owner = owner
        self.comfy = comfy_client
        self._file_lock = GpuLock(owner, lock_root)
        self._wait_s = wait_s
        self._timeout_s = timeout_s
        self._acquired = False

    @property
    def held(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Acquire both locks. Returns True on success, False if blocked."""
        # 1. In-process thread lock
        if self._wait_s > 0:
            # Wait with timeout
            if not _PROCESS_LOCK.acquire(blocking=True, timeout=self._wait_s):
                logger.warning("GPU batch %s blocked on in-process lock", self.owner)
                return False
        else:
            # Non-blocking (default behavior)
            if not _PROCESS_LOCK.acquire(blocking=False):
                logger.warning("GPU batch %s blocked on in-process lock", self.owner)
                return False

        # 2. Cross-process file lease
        if not self._file_lock.acquire(wait_s=self._wait_s, timeout_s=self._timeout_s):
            _PROCESS_LOCK.release()
            logger.warning("GPU batch %s blocked on file lease", self.owner)
            return False

        # 3. Unload Ollama models from VRAM
        logger.info("GPU batch %s acquired - unloading Ollama", self.owner)
        try:
            self.comfy.unload_ollama()
        except Exception as exc:
            logger.warning("Ollama unload failed in GPU batch %s: %s", self.owner, exc)

        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return

        # 1. Free ComfyUI models from VRAM
        logger.info("GPU batch %s releasing - freeing ComfyUI", self.owner)
        try:
            self.comfy.free()
        except Exception as exc:
            logger.warning("ComfyUI free failed in GPU batch %s: %s", self.owner, exc)

        # 2. Release cross-process file lease
        self._file_lock.release()

        # 3. Release in-process thread lock
        _PROCESS_LOCK.release()

        self._acquired = False
        logger.info("GPU batch %s fully released", self.owner)

    def __enter__(self) -> "GpuBatch":
        if not self.acquire():
            raise GpuLockError(f"GPU is owned by another stage; cannot run {self.owner}")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
