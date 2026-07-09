# BUILDER HANDOFF — Aether Pipeline v2

> **Who this is for:** the builder model (Opus subagents) executing work
> orders. **Who manages:** Fable plans the work orders, reviews every
> deliverable against the gates, and is the only one who talks to Amir.
> Builders do not expand scope, do not ask Amir questions directly — open
> questions go in the work report for Fable to escalate.

## 1. Read in this order (all in this repo)

1. `CLAUDE.md` — house rules (edit safety, style, backup protocol, paths)
2. `docs/planning/anime-pipeline-v2-design.md` — THE build contract
3. `docs/planning/aether-studio-original-spec-stages0-2.md` — normative
   schemas/prompts/temperatures for Stages 0–2
4. `docs/planning/node-additions-plan.md` — closed list of installs
5. `olympus/engines/pipeline/workflows/manifest.json` — template patch contract

## 2. Environment facts (verified 2026-07-09)

| Thing | Value |
|---|---|
| Repo | `C:\Users\amire\my-local-ai-stack` (branch master, pushes to github.com/amiracle1803/my-local-ai-stack) |
| Stack venv | `.venv\Scripts\python.exe` (Python 3.12, fastapi/mcp/pymupdf4llm/crawl4ai installed) |
| Olympus kernel | :4600 (FastAPI; services API can start/stop apps — `POST /api/services/{name}/start`) |
| ComfyUI | **`C:\AI\ComfyUI`** (primary), :8188, own venv (Py 3.11.9, torch 2.6.0+cu124 PINNED, pydantic 2.12.3 PINNED). `E:\AI\ComfyUI` is a weekly mirror (task "SyncComfyUI") — never edit E: directly |
| Ollama | :11434, has `llama3.1:8b`, `nomic-embed-text`. `qwen3:8b` + `qwen2.5vl:7b` NOT pulled yet (~10 GB — Amir approval pending, escalate via Fable when needed) |
| Voice Studio | :5050 (`olympus\engines\voice\`, Kokoro, own venv) |
| n8n :5678, Langfuse :3030, Qdrant :6333, Portainer :9443, MCP gw :8811 | Docker, all running |
| git | `C:\Program Files\Git\cmd\git.exe` (NOT on PowerShell PATH — scripts must resolve it; identity already configured) |
| GPU | RTX 4070 Laptop 8 GB. NEVER run Ollama generation + ComfyUI generation simultaneously |
| Storage quirk | E: drive drops offline sometimes; C: had file corruption once — verify E: presence before writes there; prefer copy-verify-delete |

## 3. Non-negotiable rules

1. **Backup protocol**: after completing any work order, run
   `powershell -ExecutionPolicy Bypass -File scripts\backup-code.ps1`
   (commits, pushes, snapshots). A work order is not done until this ran.
2. **MODEL BAN LIST** (design §5.3b): z-anime-distill, wai-illustrious-v110,
   NoobAI-XL-v1.1 may never be used for image generation. krea2 is the
   mandated primary; hard-stop + report if it can't be obtained/run.
3. **Pins**: never upgrade torch/pydantic in ComfyUI's venv; never install
   pipeline libs into ComfyUI's venv or vice versa.
4. **.ps1 files are pure ASCII** (PS 5.1 mangles BOM-less UTF-8 punctuation).
5. **Ken Burns is banned.** Stills use the oscillating drift (design §3C.1).
6. Minimal diffs; Pydantic models; no cloud calls; tests for every module
   (pytest, golden-file style); follow the repo's existing code style.
7. Scope = the current work order. Nothing else. Log discoveries in the
   report instead of acting on them.

## 4. Milestone map (design §6) and current state

M0 skeleton → M1 Stage 0B → M2 Stage 1 → M3 Stage 2 → M4 ComfyClient +
model_lab + Stage 1R + wardrobe (krea2 verdict lives here) → M5 Stage 3/3B →
M6 voice → M6.5 animation/lip sync → M7 assembly → M8 Transform/Import +
Studio UI.

Done already (do not redo): design docs, 8 workflow templates + manifest +
UI-format graphs, WD14 tagger installed, services API, dashboard.

## 5. Work order protocol

- Fable issues one work order per milestone slice with: scope, files to
  create/change, acceptance gates, verification commands.
- Builder implements, runs the verification commands, runs the backup
  protocol, then reports: **(a)** what was built (files + line counts),
  **(b)** verification output (paste real command output, never summaries
  of it), **(c)** deviations from the design and why, **(d)** open
  questions for Amir, **(e)** anything discovered but NOT acted on.
- Fable re-runs the gates independently before accepting. Failed gates →
  the same builder gets a fix order with the exact failure output.

## 6. Verification gate cheat-sheet (Fable runs these on every acceptance)

```powershell
# tests green
.venv\Scripts\python.exe -m pytest olympus/engines/pipeline/tests -q
# kernel + services healthy
Invoke-RestMethod http://127.0.0.1:4600/api/health
# ComfyUI parses and expected nodes exist (when touched)
.venv\Scripts\python.exe -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8188/object_info')); print(len(d))"
# repo pushed + snapshots exist
git log --oneline -3 ; dir "C:\Users\amire\Documents\Obsidian Vault\Projects\Code Backups" | tail -2
```
