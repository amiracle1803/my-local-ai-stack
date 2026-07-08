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
## Port reference

| Port | Service |
|---|---|
| 11434 | Ollama |
| 8750 | Project 1 web app |
| 5678 | n8n |
| 4720 | OpenCode MCP |
| 4600 | Olympus (agent hub) |
| 6333 | Qdrant (optional) |
| 9443 | Portainer (optional) |

## Nuclear options (safe)

- **Reset the AI's memory:** delete `<vault>/_generated/`. Your notes are
  untouched; it rebuilds on the next run.
- **Rebuild the environment:** delete `.venv/` and run `setup.bat` again.
- **Reset n8n:** `docker compose down -v` in `foundation/` (deletes workflows —
  export them first).


