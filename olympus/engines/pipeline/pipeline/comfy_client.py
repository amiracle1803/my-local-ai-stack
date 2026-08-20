"""ComfyClient -- the shared ComfyUI layer (design 5.3).

Every image/video stage's ComfyUI traffic goes through this module:

- Loads workflow templates from ``workflows/`` (API format) and patches node
  inputs by the manifest's ``patchable`` title -> ``node_id.input_field`` map.
- POSTs to ``/prompt``, polls ``/history/<id>`` until the job lands, and
  copies the outputs into the caller's target directory.
- **Ban enforcement** (design 5.3b): refuses to queue any workflow whose
  resolved checkpoint/unet name is on the MODEL BAN LIST.
- **Failure contingency**: 3 consecutive failures -> :class:`ContingencyStop`
  so the stage stops and reports instead of burning GPU time.
- ``free()`` asks ComfyUI to unload models between batches (the Linux
  equivalent of the generate-safe restart pattern; a full process restart is
  not needed when ``/free`` clears the VRAM).
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

import requests

from .config import ENGINE_ROOT, PipelineConfig

logger = logging.getLogger(__name__)

WORKFLOWS_DIR = ENGINE_ROOT / "workflows"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"

_POLL_INTERVAL_S = 1.0
_MAX_CONSECUTIVE_FAILURES = 3


class ComfyError(RuntimeError):
    """A single ComfyUI job failed (queue rejected, execution error, timeout)."""


class ContingencyStop(RuntimeError):
    """Raised after 3 consecutive failures -- the stage must stop and report
    (design 5.3: contingency_stop scorecard entry)."""


class WorkflowTemplate:
    """One workflow JSON + its manifest ``patchable`` map."""

    _cache: dict[str, "WorkflowTemplate"] = {}

    def __init__(self, name: str, graph: dict[str, Any], patchable: dict[str, str]):
        self.name = name
        self.graph = graph
        self.patchable = patchable

    @classmethod
    def load(cls, name: str) -> "WorkflowTemplate":
        if name in cls._cache:
            return cls._cache[name]
        manifest = json.loads((WORKFLOWS_DIR / "manifest.json").read_text(encoding="utf-8"))
        entry = manifest["templates"].get(name)
        if entry is None:
            raise ComfyError(f"workflow {name!r} not in manifest.json")
        graph = json.loads((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
        patchable = entry.get("patchable", {})
        # Validate on load (design 5.3b): every patchable target must exist.
        # A target may be comma-separated (e.g. "13.width,15.width") so one
        # patch title can keep multiple nodes in sync -- used by the FLUX.2
        # klein templates to keep Flux2Scheduler's resolution-dependent sigma
        # schedule matched to the EmptyFlux2LatentImage canvas.
        for title, targets in patchable.items():
            for target in targets.split(","):
                node_id, field = target.split(".", 1)
                if node_id not in graph:
                    raise ComfyError(f"{name}: patchable {title} -> missing node {node_id}")
                if field not in graph[node_id].get("inputs", {}):
                    raise ComfyError(f"{name}: patchable {title} -> node {node_id} has no input {field}")
        tmpl = cls(name, graph, patchable)
        cls._cache[name] = tmpl
        return tmpl

    def patched(self, patches: dict[str, Any]) -> dict[str, Any]:
        """Deep-copy the graph with ``patches`` (title -> value) applied.

        Each title resolves to one or more ``node_id.input_field`` targets
        (comma-separated in the manifest) -- every target gets the value.
        """
        graph = json.loads(json.dumps(self.graph))
        for title, value in patches.items():
            targets = self.patchable.get(title)
            if targets is None:
                raise ComfyError(f"{self.name}: unknown patch title {title!r}")
            for target in targets.split(","):
                node_id, field = target.split(".", 1)
                graph[node_id]["inputs"][field] = value
        return graph


def _banned_models_in(graph: dict[str, Any], banned: list[str]) -> list[str]:
    """Names of banned checkpoints/unets referenced by ``graph``. Matches with
    and without file extension so 'NoobAI-XL-v1.1' bans 'NoobAI-XL-v1.1.safetensors'."""
    hits = []
    for node in graph.values():
        for field in ("ckpt_name", "unet_name"):
            name = node.get("inputs", {}).get(field)
            if not isinstance(name, str):
                continue
            stem = name.rsplit(".", 1)[0]
            if name in banned or stem in banned:
                hits.append(name)
    return hits


class ComfyClient:
    """HTTP client for one ComfyUI instance, with ban enforcement and the
    3-consecutive-failure contingency."""

    def __init__(
        self,
        config: PipelineConfig,
        *,
        base_url: str = DEFAULT_COMFY_URL,
        timeout_s: float = 600.0,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._session = session or requests.Session()
        self._consecutive_failures = 0

    # ---- health ---------------------------------------------------------
    def healthy(self) -> bool:
        try:
            r = self._session.get(f"{self.base_url}/system_stats", timeout=5)
            return r.ok
        except requests.RequestException:
            return False

    def output_dir(self) -> Path:
        return self.config.comfyui_dir() / "output"

    def input_dir(self) -> Path:
        return self.config.comfyui_dir() / "input"

    def upload_image(self, src: Path, name: str | None = None) -> str:
        """Upload an image to ComfyUI's input directory via /upload/image.

        Returns the filename as registered by ComfyUI (used in LoadImage nodes).
        """
        name = name or src.name
        with open(src, "rb") as f:
            r = self._session.post(
                f"{self.base_url}/upload/image",
                files={"image": (name, f, "image/png")},
                data={"overwrite": "true"},
                timeout=30,
            )
        r.raise_for_status()
        return r.json().get("name", name)

    def free(self) -> None:
        """Ask ComfyUI to unload models + free VRAM (between batches)."""
        try:
            self._session.post(
                f"{self.base_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=30,
            )
        except requests.RequestException as exc:  # non-fatal
            logger.warning("comfy /free failed: %s", exc)

    def unload_ollama(self, base_url: str = "http://127.0.0.1:11434") -> None:
        """GPU scheduling rule (design section 1): never run Ollama and
        ComfyUI generation simultaneously. Called by image stages before
        their first generation -- asks Ollama to evict every loaded model
        (keep_alive: 0). Non-fatal if Ollama is down."""
        try:
            loaded = self._session.get(f"{base_url}/api/ps", timeout=10).json()
            for m in loaded.get("models", []):
                self._session.post(
                    f"{base_url}/api/generate",
                    json={"model": m["name"], "keep_alive": 0},
                    timeout=30,
                )
                logger.info("unloaded ollama model %s before image batch", m["name"])
        except requests.RequestException as exc:
            logger.warning("ollama unload skipped: %s", exc)

    # ---- generation ------------------------------------------------------
    def generate(
        self,
        template_name: str,
        patches: dict[str, Any],
        *,
        dest: str | Path,
    ) -> list[Path]:
        """Queue one patched workflow, wait for completion, and copy every
        output image to ``dest``. Returns the copied paths (in node order).

        Raises :class:`ContingencyStop` after 3 consecutive failures.
        """
        template = WorkflowTemplate.load(template_name)
        graph = template.patched(patches)

        hits = _banned_models_in(graph, self.config.models.banned)
        if hits:
            raise ComfyError(
                f"workflow {template_name} resolves to BANNED model(s) {hits} "
                f"(design 5.3b) - refusing to queue."
            )

        try:
            paths = self._run(graph, dest=Path(dest))
        except ComfyError:
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                raise ContingencyStop(
                    f"{self._consecutive_failures} consecutive ComfyUI failures "
                    f"on {template_name} - stopping stage (design 5.3)."
                )
            raise
        self._consecutive_failures = 0
        return paths

    def _run(self, graph: dict[str, Any], *, dest: Path) -> list[Path]:
        try:
            r = self._session.post(
                f"{self.base_url}/prompt", json={"prompt": graph}, timeout=30
            )
        except requests.RequestException as exc:
            raise ComfyError(f"queue failed: {exc}") from exc
        if not r.ok:
            raise ComfyError(f"queue rejected ({r.status_code}): {r.text[:500]}")
        prompt_id = r.json()["prompt_id"]

        deadline = time.monotonic() + self.timeout_s
        poll_errors = 0
        while True:
            if time.monotonic() > deadline:
                raise ComfyError(f"job {prompt_id} timed out after {self.timeout_s}s")
            time.sleep(_POLL_INTERVAL_S)
            try:
                h = self._session.get(f"{self.base_url}/history/{prompt_id}", timeout=15)
            except requests.RequestException as exc:
                # Transient: the server stalls while loading a multi-GB model.
                # Keep polling until the job deadline; only a sustained outage
                # (10 consecutive failures) is a real error.
                poll_errors += 1
                if poll_errors >= 10:
                    raise ComfyError(f"history poll failed {poll_errors}x: {exc}") from exc
                logger.warning("history poll hiccup (%d/10): %s", poll_errors, exc)
                continue
            poll_errors = 0
            entry = h.json().get(prompt_id)
            if not entry:
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                messages = json.dumps(status.get("messages", []))[:500]
                raise ComfyError(f"job {prompt_id} errored: {messages}")
            if entry.get("outputs"):
                return self._collect(entry["outputs"], dest)

    def _collect(self, outputs: dict[str, Any], dest: Path) -> list[Path]:
        """Copy every produced artifact to ``dest``.

        Handles two ComfyUI output shapes:

        - Image save nodes (SaveImage, PreviewImage): ``"images"`` key, files
          land under ``ComfyUI/output/<subfolder>/<filename>``.
        - Video save nodes (VHS_VideoCombine): ``"gifs"`` UI key with a
          ``"type"`` field of ``"output"`` or ``"temp"`` -- files land under
          ``ComfyUI/output/<subfolder>/<filename>`` or ``ComfyUI/temp/<subfolder>/<filename>``.
          Without this branch every LTX/Wan animation job raises "produced no
          images" even though the clip was written successfully.
        """
        dest.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        out_root = self.output_dir()
        temp_root = self.config.comfyui_dir() / "temp"
        for node_output in outputs.values():
            for art in node_output.get("images", []):
                src = out_root / art.get("subfolder", "") / art["filename"]
                if not src.exists():
                    raise ComfyError(f"output image missing on disk: {src}")
                target = dest / art["filename"]
                shutil.copy2(src, target)
                copied.append(target)
            for art in node_output.get("gifs", []):
                kind = art.get("type", "output")
                base = temp_root if kind == "temp" else out_root
                src = base / art.get("subfolder", "") / art["filename"]
                if not src.exists():
                    raise ComfyError(f"output video missing on disk: {src}")
                target = dest / art["filename"]
                shutil.copy2(src, target)
                copied.append(target)
        if not copied:
            raise ComfyError("job completed but produced no images")
        return copied
