# Troubleshooting

The consolidated fix-list for the whole stack. Find your symptom; apply the fix.

---

## Setup & environment

| Symptom | Fix |
|---|---|
| `setup.bat`: "Ollama is not installed" | Install from <https://ollama.com/download>, launch it, re-run `setup.bat`. |
| `setup.bat`: "Python is not installed" | Install Python 3.11+ from python.org and **tick "Add python.exe to PATH"**. Re-run. |
| `pip install` fails | Check internet; re-run `setup.bat`. Base packages are lightweight, so this is usually a network blip. |
| A `start.bat` says "run setup.bat first" | The `.venv` is missing — run `setup.bat` in the main folder. |
| Model download stalls | Re-run `setup.bat` — downloads resume. Or run `ollama pull llama3.1:8b` manually. |
| Everything is very slow | You're on CPU or the model is big. Set `"chat_model": "llama3.2:3b"` in `config.json` and `ollama pull llama3.2:3b`. |

## Ollama

| Symptom | Fix |
|---|---|
| "Ollama does not seem to be running" | Launch the Ollama app (or run `ollama serve`). Test: open <http://localhost:11434> — you should see "Ollama is running". |
| "The model '…' is not downloaded" | `ollama pull <model>` (the message tells you which). |
| Port 11434 in use | Another Ollama instance is running — that's fine, use it. To change, set `OLLAMA_HOST` and update `config.json`. |

## Linux (systemd / podman / SSD)

Since 2026-07-10 the stack also runs natively on Fedora. `./setup.sh` /
`./start.sh` mirror `setup.bat` / `start.bat`; Ollama, ComfyUI, and Voice
Studio run as **systemd user units**, and n8n/Langfuse run under **podman**
instead of Docker Desktop.

| Symptom | Fix |
|---|---|
| A service is dead after a reboot (Ollama, ComfyUI, Voice Studio) | `systemctl --user status <unit>` (e.g. `ollama`, `comfyui-server`, `voice-studio`) to see why, then `systemctl --user restart <unit>`. ComfyUI/Voice Studio are started as transient units via `systemd-run --user --unit=<name> ...` (see docs/GUIDE.md section 11), so they only exist while running or recently failed. |
| SSD not mounted (`/run/media/amirel/Amir1tb SSD` missing -- breaks ComfyUI's `extra_model_paths.yaml` and the pipeline's `loras` path) | `systemctl --user restart mount-amir1tb-ssd.service`, or manually `udisksctl mount -b /dev/disk/by-uuid/2A0A35510A351AF1`. |
| ComfyUI returns HTTP 000 / connection refused on `:8188` | `systemctl --user restart comfyui-server` (or start it per docs/GUIDE.md section 11 if the unit doesn't exist yet). |
| n8n / Langfuse containers didn't come back after a reboot | Check `podman ps -a`; `podman-restart.service` is what restarts containers with a restart policy on boot -- `systemctl --user status podman-restart.service` and `systemctl --user enable --now podman-restart.service` if it isn't enabled. |
| `podman-compose` not found | `pip install podman-compose`, or use plain `podman` commands (see `foundation/docker-compose.yml` -- the compose files use fully-qualified image names so either works). |
| `gh push` / `git push` fails from `scripts/backup-code.sh` | Fresh Linux installs have no stored GitHub credentials yet -- run `gh auth login` once (sets up git's credential helper for `github.com`), then re-run the backup script. |

## ~~Project 1 � Ops Hub~~ (archived)

| Symptom | Fix |
|---|---|
| Page shows "Ollama OFFLINE" | Start Ollama, refresh. |
| Can't reach `localhost:8750` | Port busy or firewall. Change `"flask_port"` in `config.json`; allow Python through Windows Firewall. |
| Research: "could not read page" | Site blocks bots or is JS-only. Try another source or install the optional Crawl4AI upgrade. |
| Inbox file not processed | Must be `.txt`/`.md`; run `run-inbox.bat`; check `inbox.log`. |

## ~~Project 2 � Second Brain~~ (archived)

| Symptom | Fix |
|---|---|
| No output after `start.bat` | Check the run log in `<vault>/_generated/logs/`. Usually Ollama was off. |
| Review invented details | Trust the critique pass (catches most); use a bigger model; re-run. |
| Duplicate items in indexes | Keep `_generated/.state/second_brain.json`. To rebuild cleanly, clear the logs and delete that state file, then re-run. |
| Nightly task didn't run overnight | Task Scheduler → the task → tick "Run whether user is logged on or not" and "Wake the computer to run this task". |
| AnythingLLM can't reach Ollama | In AnythingLLM set Base URL `http://localhost:11434` and pick your model. |

## ~~Project 3 � Automation~~ (archived)

| Symptom | Fix |
|---|---|
| "No feeds configured" | Copy `feeds.example.txt` → `feeds.txt`, add RSS URLs. |
| Feed returns nothing | Open the feed URL in a browser; fix/remove dead feeds. |
| Repo digest: "not a git repo" | Point `repos` at the folder containing `.git`. |
| Repo digest empty | No new commits since last run — expected. |
| Scheduled jobs silent | See the "run whether logged on" fix above; check `research.log` / `digest.log`. |

## Docker & n8n (optional)

| Symptom | Fix |
|---|---|
| `docker` not found | Install Docker Desktop; make sure it's running before `start-n8n.bat`. |
| Docker won't start | Enable virtualization in BIOS and WSL2 (Docker Desktop prompts you). |
| n8n UI won't load | Wait ~30s after start; confirm the container is up in Docker Desktop. |
| HTTP node "connection refused" to Ollama | Set Windows env var `OLLAMA_HOST=0.0.0.0`, restart Ollama, and use `http://host.docker.internal:11434` in n8n. |
| IMAP login fails | Use an **app password** (enable 2FA first), not your real password. |
| Port 5678 in use | Change the `ports` mapping in `foundation/docker-compose.yml`. |


## Olympus (agent hub)

| Symptom | Fix |
|---|---|
| Dashboard won't load at `http://127.0.0.1:4600` | Olympus may not have started. Check the terminal window titled "Olympus". Run `start.bat` again. |
| "Agent not found" in a task | The agent's `.md` file is missing from `olympus/agents/`. Create one with the correct `id` and `domain` frontmatter. |
| Health check fails | `curl http://127.0.0.1:4600/api/health` should return JSON. If not, check `olympus/data/olympus.log`. |
| Voice endpoint returns 500 | Verify `engine_python` in `olympus.toml` points to the correct voice-studio venv, and Kokoro/F5-TTS is installed there. |

## Anime pipeline (olympus/engines/pipeline)

| Symptom | Fix |
|---|---|
| `SkippedStageError` when running a stage | A stage gate is structural -- it refuses to run until the previous stage proves its metric. Run `python run.py report <slug>` to see the stage ledger and which `missing_metrics` are blocking you, fix/rerun that stage, then retry. |
| `StoryPollutionError` | `input/script.txt` no longer matches the project's `title_hash` (someone edited/swapped the script file after `new-project`). Restore the original script, or start a new project if the change was intentional. |
| `BannedModelError` | The resolved image model is on the ban list in `pipeline.toml` (`z-anime-distill-4step-fp8`, `wai-illustrious-v110`, `NoobAI-XL-v1.1`). Point `image_primary`/`image_fallback` at a permitted model -- currently `krea2` (primary, not yet installed) falling back to `flux1-schnell-Q4_K_S.gguf`. |
| Ollama + ComfyUI VRAM thrash / a history poll stalls during stage1r or stage3b | Already fixed as of commit `84d5ab8` (2026-07-10) -- those stages call `comfy.unload_ollama()` before their first generation so the two never load at once on the 8 GB card. If you still see stalls, check `journalctl --user -u comfyui-server` and `journalctl --user -u ollama`. |
| Stage 1R LoRA gate can't be satisfied | `kohya_ss` itself doesn't run on the Linux install yet; its underlying engine (`tools-external/sd-scripts`) is installed directly as the workaround. Until that's wired in, `pipeline.toml`'s `[automation] allow_missing_loras = true` lets Stage 3B proceed anyway -- the deviation is recorded in every affected scorecard. |

## Port reference

| Port | Service |
|---|---|
| 11434 | Ollama |
| 8750 | Project 1 web app |
| 5678 | n8n |
| 4720 | OpenCode MCP |
| 4600 | Olympus (agent hub) |
| 5050 | Voice Studio |
| 8188 | ComfyUI |
| 3030 | Langfuse (optional) |
| 6333 | Qdrant (optional) |
| 9443 | Portainer (optional) |

## Nuclear options (safe)

- **Reset the AI's memory:** delete `<vault>/_generated/`. Your notes are
  untouched; it rebuilds on the next run.
- **Rebuild the environment:** delete `.venv/` and run `setup.bat` again.
- **Reset n8n:** `docker compose down -v` in `foundation/` (deletes workflows —
  export them first).


