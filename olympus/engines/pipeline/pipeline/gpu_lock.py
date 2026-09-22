"""Process-level mutex for GPU workloads shared by ComfyUI and TTS."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


LOCK_PATH = Path(os.environ.get("OLYMPUS_GPU_LOCK", "/tmp/olympus-gpu.lock"))


@contextmanager
def gpu_batch(owner: str, timeout: float = 900):
    """Hold an exclusive filesystem lock for one GPU batch."""
    import fcntl

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"GPU lock timeout while waiting for {owner}")
                time.sleep(0.25)
        handle.seek(0)
        handle.truncate()
        handle.write(owner)
        handle.flush()
        try:
            yield
        finally:
            handle.seek(0)
            handle.truncate()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
