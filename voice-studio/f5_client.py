"""
f5_client.py -- parent-side handle for the persistent F5-TTS worker process
(f5_worker.py). See that file's docstring for why this exists.

Auto-respawns the worker if it dies (crash, OOM abort, timeout) so a single
bad generation degrades to "that request failed, try again" instead of
taking down the whole app.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time


class F5Worker:
    def __init__(self, worker_script: str, ready_timeout: float = 300.0):
        self._python = sys.executable
        self._script = worker_script
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._ready_timeout = ready_timeout
        self.sr = 24000
        self.available = False
        self._start()

    def _start(self) -> None:
        print("  Starting F5-TTS worker (isolated subprocess)...")
        try:
            self._proc = subprocess.Popen(
                [self._python, "-u", self._script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, cwd=os.path.dirname(os.path.abspath(self._script)),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  F5 worker failed to start: {exc}")
            self.available = False
            return

        threading.Thread(target=self._relay_stderr, daemon=True).start()

        msg = self._read_json_line(self._ready_timeout, max_skip=20)
        if msg is None:
            self.available = False
            return

        if msg.get("ready"):
            self.sr = int(msg.get("sr", 24000))
            self.available = True
            print(f"  F5-TTS worker ready! (sample rate: {self.sr} Hz)")
        else:
            print(f"  F5 worker failed to load: {msg.get('error')}")
            self.available = False

    def _relay_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        for line in self._proc.stderr:
            print(f"  [f5-worker] {line.rstrip()}")

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _read_json_line(self, timeout: float, max_skip: int = 5) -> dict | None:
        """
        Read stdout lines until one parses as JSON, an empty line (EOF/died)
        is hit, or the timeout/skip budget runs out. f5_worker.py redirects
        library print() noise to stderr, but this tolerates anything that
        still slips through (e.g. a C extension writing to the raw fd).
        """
        deadline = time.monotonic() + timeout
        for _ in range(max_skip):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(f"  F5 worker did not respond within {timeout}s.")
                return None
            q: queue.Queue = queue.Queue()
            threading.Thread(target=lambda: q.put(self._proc.stdout.readline()), daemon=True).start()
            try:
                line = q.get(timeout=remaining)
            except queue.Empty:
                print(f"  F5 worker did not respond within {timeout}s.")
                return None
            if not line:
                print("  F5 worker exited unexpectedly (likely crashed).")
                return None
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol output -- keep looking
        print(f"  F5 worker sent {max_skip} non-JSON lines in a row, giving up.")
        return None

    def generate(
        self, ref_file: str, ref_text: str, gen_text: str, out_path: str,
        nfe_step: int = 16, cfg_strength: float = 2.0, speed: float = 1.0,
        cross_fade_duration: float = 0.15, timeout: float = 120.0,
    ) -> int:
        """Runs one F5-TTS generation, writes the result to out_path, returns the sample rate."""
        with self._lock:
            if not self.available or not self._alive():
                self._start()
                if not self.available:
                    raise RuntimeError("F5-TTS worker is not available.")

            req = json.dumps({
                "ref_file": ref_file, "ref_text": ref_text, "gen_text": gen_text,
                "nfe_step": nfe_step, "cfg_strength": cfg_strength, "speed": speed,
                "cross_fade_duration": cross_fade_duration, "out_path": out_path,
            })
            try:
                self._proc.stdin.write(req + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.available = False
                raise RuntimeError(f"F5 worker pipe broke: {exc}") from exc

            payload = self._read_json_line(timeout, max_skip=20)
            if payload is None:
                self.available = False
                raise RuntimeError(
                    "F5 worker did not return a valid response (timed out, crashed, or sent "
                    "unparseable output) -- it will restart on the next request."
                )

            if not payload.get("ok"):
                raise RuntimeError(payload.get("error") or "F5 worker reported failure")
            return int(payload.get("sr", self.sr))
