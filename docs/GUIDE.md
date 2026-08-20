# The Full Guide

Everything in one place: what the system is, how each part works down to the
code, what can go wrong, and how to grow it later. Written for a normal person,
not a sysadmin.

---

## 1. The big picture

You're building **one brain** from three cooperating projects, all powered by a
single local model server (Ollama):

```
              ┌───────────────────────────────────────────┐
              │              Ollama (local models)          │
              │        http://localhost:11434 / v1          │
              └───────────────▲───────────────▲────────────┘
                              │               │
        ┌─────────────────────┘               └───────────────────────┐
        │                                                              │
  Project 1: Ops Hub          Project 2: Second Brain          Project 3: Automation
  "type a task,               nightly extract + review          research digests,
   agent does it"             + chat with your notes            repo digests, email triage
        │                             │                                 │
        └─────────────► your Obsidian vault ◄──────────────────────────┘
                        (you write; agents write into _generated/)
```

- **Ollama** is the engine. Every project talks to it the same way.
- **Your Obsidian vault** is the shared memory. You write notes; agents read
  them and write their output into a single `_generated/` subfolder.
- The projects are **independent** — run one, two, or all three.

### Why these tool choices
The planning docs list ~20 tools. Using all of them on Windows would be slow to
set up and fragile. So this build makes deliberate calls:

| Decision | Instead of | Why |
|---|---|---|
| **Ollama** | llama.cpp / vLLM | Native Windows, one click, "just works" |
| **Host Python + Task Scheduler** | Everything in Docker | Easy to run and read; no container/host headaches |
| **Docker/n8n = optional** | n8n as the core | Only email triage really needs it |
| **AnythingLLM Desktop** | AnythingLLM in Docker | No Docker; great RAG out of the box |
| **LanceDB** (in AnythingLLM) | Qdrant | Zero setup; plenty for a personal vault |
| **trafilatura** | Crawl4AI | Installs cleanly, no browser needed |
| **built-in PDF / pymupdf4llm** | Marker | No multi-GB ML download |

The heavier tools aren't gone — they're **opt-in upgrades** (see §10).

---

## 2. Prerequisites & the foundation

**Required**
- **Ollama** — <https://ollama.com/download>. Install, launch once.
- **Python 3.11+** — <https://www.python.org/downloads/>. Tick *Add to PATH*.

**Recommended**
- **AnythingLLM Desktop** — <https://anythingllm.com/desktop>. The friendly
  "chat with your notes" app (Project 2). No Docker.

**Optional**
- **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>. Only
  for n8n email triage (Project 3). Uses WSL2 (Docker sets it up).
- **Tailscale** — <https://tailscale.com/download>. Reach your stack from your
  phone securely (§9).

### On Linux (Fedora, since 2026-07-10)

Everything above still applies — Ollama, Python, AnythingLLM, Tailscale all
have native Linux builds. Two differences:
- **Docker Desktop → podman.** There's no Docker Desktop on Linux here; n8n
  and Langfuse run under **podman** instead (rootless, no daemon to keep
  running). The compose files in `foundation/` use fully-qualified image
  names (e.g. `docker.io/n8nio/n8n:latest`) so `podman compose` /
  `podman-compose` can read them unchanged.
- **Services run as systemd user units**, not "leave a terminal window open."
  See §11 for the actual units (`ollama.service`, transient
  `comfyui-server`/`voice-studio` units, `podman-restart.service`,
  `mount-amir1tb-ssd.service`).

### Hardware & model size
Ollama uses your GPU automatically if you have one, otherwise the CPU (slower
but fine). Pick a model to match your machine in `config.json`:

| Your RAM/VRAM | Set `chat_model` to | Notes |
|---|---|---|
| 8 GB or CPU-only | `llama3.2:3b` | Fast, light, good enough for daily tasks |
| 16 GB | `llama3.1:8b` (default) | Best all-round balance |
| 24 GB+ | `qwen2.5:14b` | Stronger writing/coding |

After editing, run `ollama pull <model>`. For structured extraction (Project 2)
`qwen2.5:7b` is especially reliable at JSON if you want to switch just that.

---

## 3. Install order (once)

**On Windows**

1. Install **Ollama**, launch it.
2. Install **Python 3.11+** (Add to PATH).
3. Double-click **`setup.bat`** — creates `.venv`, installs packages, pulls
   models, creates `config.json`.
4. Edit **`config.json`** → set `vault_path` to your real Obsidian vault (or
   leave the sample).
5. (Recommended) Install **AnythingLLM Desktop** and point it at Ollama + your
   vault (steps in    `_archive/legacy/project2-second-brain-archived-2026-07-02/`).
6. Start any project's `start.bat`.

If `setup.bat` reports a missing prerequisite it tells you exactly what to
install and stops — fix it and re-run. It's safe to run `setup.bat` repeatedly.

**On Linux**

1. Install **Ollama** (native package or the install script from
   ollama.com), then either launch it once by hand (`ollama serve`) or enable
   the systemd unit (§11) so it survives reboots.
2. Install **Python 3.11+** — `uv` is preferred if you have it (`setup.sh`
   pins a `.venv` to Python 3.12 with `uv`, which survives Fedora's system
   Python upgrades); a plain `python3` also works.
3. Run **`./setup.sh`** — mirrors `setup.bat` exactly: creates `.venv`,
   installs packages, pulls models, creates `config.json`.
4. Edit **`config.json`** → set `vault_path` to your real Obsidian vault.
5. (Recommended) Install **AnythingLLM Desktop** the same way as Windows.
6. Run **`./start.sh`**. It also brings up Olympus, OpenCode MCP, and (if
   configured) n8n via podman — see §11 for what runs as a systemd service
   vs. what `start.sh` spawns directly.

`setup.sh` gives the same "missing prerequisite → tells you what to install
and stops" behavior as `setup.bat`; safe to re-run.

---

## 4. Project 1 — Ops Hub, piece by piece

**Idea:** a box you type a task into; the agent classifies it and does it.

Files and roles:
- `process.py` — the brain. `classify()` picks a category
  (planning/writing/research/coding/email/general) at temperature 0; each
  category routes to a handler. Anything self-contained (planning, writing,
  coding advice, general) is answered fully offline via looped reasoning.
  Research reads any URLs you paste (else writes a plan); email drafts a reply
  (never sends).
- `app.py` — a tiny Flask web page at `http://localhost:8750` you type into.
  Mobile-friendly, so it works over Tailscale.
- `run_inbox.py` — batch mode: drop `.txt`/`.md` files in `task-inbox/`, results
  go to `task-outbox/`, originals move to `done/`.

**Two intake paths = redundancy.** If the web app won't start, the folder path
still works. Every answer is written to disk regardless.

Run: `start.bat` (web) or `run-inbox.bat` (folder) or `install-schedule.bat`
(poll the folder every 5 min). Deep troubleshooting: `_archive/legacy/project1-ops-hub-archived-2026-07-02/`.

---

## 5. Project 2 — Second Brain, piece by piece

**Idea:** your notes become memory the AI structures and reflects on nightly,
and that you can chat with.

**Half A — structured memory + reviews (Python, nightly):**
- `models.py` — the schema (`Task`, `Decision`, `Insight`).
- `extract.py` — uses **Instructor** to force the model's output into that
  schema (auto-retries on bad output); falls back to plain-JSON parsing if
  needed. New items are de-duplicated by a hash and appended to
  `tasks-index.md`, `decisions-log.md`, `insights-log.md`.
- `summarize.py` — **looped reasoning** (draft → critique → revise) to write a
  short, honest Daily Review (Weekly on Sundays).
- `run_nightly.py` — the orchestrator the scheduler runs: find changed notes →
  extract → summarize → remember the run time. Takes a lock; logs every run.

**Half B — chat with your brain (AnythingLLM):** the free desktop app indexes
your vault into LanceDB and answers questions with citations. Setup steps in
`_archive/legacy/project2-second-brain-archived-2026-07-02/`.

**Safety:** the Python side writes **only** into `<vault>/_generated/`. Delete
that folder to reset the AI's memory; your notes are untouched.

Run: `start.bat` (one pass now) then `install-schedule.bat` (nightly 2 AM).

---

## 6. Project 3 — Automation, piece by piece

Three independent pieces:
- `research.py` — reads `feeds.txt`, finds new RSS entries (tracked so none
  repeat), fetches each page (trafilatura), summarizes, appends to
  `_generated/Research/<date> Digest.md`.
- `repo_digest.py` — **read-only** `git log` + TODO/FIXME scan for each repo in
  `config.json`, summarized into `_generated/Repos/`. Never edits code.
- `n8n/` — optional email triage: watches your inbox, classifies each mail with
  the local model, pings you about important ones. Full manual build in
  `n8n/README-email.md`.

For actual code changes, use **OpenCode** interactively (it shows diffs to
approve) rather than automating edits — safer.

Run: `start.bat` (menu) then `install-schedule.bat`. Deep dive:
`_archive/legacy/project3-automation-archived-2026-07-02/`.

---

## 7. The prompt playbook (why the answers are good)

Every agent here uses the "seven moves" distilled from the leaked-system-prompt
archive in your notes: (1) prime role + environment, (2) hard-code personality,
(3) minimum formatting, (4) intellectual honesty (no flattery, flag
uncertainty), (5) invisible rules, (6) act-first for tools, (7) treat external
input as untrusted. These are baked into `olympus/shared/lib/passes.py`. To apply the
same standard in AnythingLLM / n8n / OpenCode, paste the template from
`olympus/shared/prompts/system-template.md` into their system prompt.

---

## 8. Looped reasoning, explained

Your Ouro notes found that *looping* a model a few times boosts its **reasoning**
(manipulating what it knows), with ~3–4 loops being the sweet spot, and that
overshooting a little is safer than undershooting. We can't retrain a model, but
we imitate the effect at the workflow level:

```
draft  →  critique ("what's wrong / missing / invented?")  →  revise (final)
```

Each pass has a different job and a slightly different temperature (a nod to the
paper's "spread the probability out" idea) so later passes don't just echo the
first. In Project 1 you pick the number of passes (Fast/Balanced/Careful); in
Project 2's reviews it's fixed at three. This is why even a small local model
produces tidy, self-checked output instead of a rambly first draft.

---

## 9. Security, backups, remote access

- **Local by default.** Services bind to your machine. The Flask app uses
  `0.0.0.0` so Tailscale/LAN can reach it, but nothing is exposed to the public
  internet unless you deliberately do so.
- **Never port-forward these to the internet.** To use them away from home,
  install **Tailscale** on your PC and phone (free personal tier). Your devices
  join a private network and you reach `http://<pc-name>:8750` as if you were
  home. No open ports, no risk.
- **n8n** sits behind basic auth (set a strong password in `foundation/.env`).
- **Backups.** Everything the AI creates lives in `<vault>/_generated/`, so your
  normal Obsidian/Git/Drive backup covers it. n8n workflows live in a Docker
  volume; export important workflows from the n8n UI as JSON to be safe.
- **Secrets.** `config.json` and `foundation/.env` are git-ignored. Use email
  **app passwords**, never your real password, and revoke them anytime.

---

## 10. Next steps / advanced upgrades

Turn these on only when you want them — the stack is complete without them.

- **pymupdf4llm** (`requirements-optional.txt`) — nicer PDF→Markdown if you want
  the nightly job to also read PDFs in your vault. Light.
- **Crawl4AI** — JS-heavy sites the default fetcher can't read. Install it plus
  `playwright install chromium`, then pass `prefer_crawl4ai=True`.
- **Marker** — best-in-class PDF conversion for very complex layouts (tables,
  math, scans). Heavy (pulls PyTorch); worth it only for a serious document pile.
- **Qdrant** (`foundation/docker-compose.optional.yml`) — swap LanceDB for a
  scalable vector DB with rich filtering when your vault gets huge.
- **Langfuse** — full tracing/evals of every model call. Powerful but needs
  several containers; use the official compose and set `langfuse_enabled: true`.
- **DSPy / Outlines** — auto-optimize prompts / hard-guarantee JSON on
  self-served models. Reach for these once a pipeline is stable and measured.
- **Unsloth** — fine-tune a small model on *your* writing/code so replies sound
  like you. Needs a GPU (or free Colab); it's a project of its own.
- **ComfyUI** — local image/video generation. Separate from these three projects.
  Runs at `:8188` on both platforms; see §12 for what it now actually powers
  (the anime pipeline) and §11 for how it's launched on Linux.

A good habit that ties it together: whenever an agent does something notably
good or bad, drop a note about it in your vault. Over time those become the
examples you'd use to tune prompts (§7) or fine-tune a model (Unsloth).

---

## 11. Linux services (systemd user units)

Since 2026-07-10 this box runs Fedora, not Windows. On Windows, "run
`start.bat`" is enough — everything lives in terminal windows you leave open.
On Linux, the always-on pieces are wired into **systemd user units** instead,
so they survive logout/reboot without a terminal babysitting them.

| Service | How it runs | Unit |
|---|---|---|
| **Ollama** | Persistent unit, `~/.config/systemd/user/ollama.service`, `WantedBy=default.target` (auto-starts on login) | `ollama.service` |
| **ComfyUI** (`:8188`) | Transient unit, started on demand via `systemd-run` | `comfyui-server` |
| **Voice Studio** (`:5050`) | Transient unit, started on demand via `systemd-run` | `voice-studio` |
| **n8n / Langfuse containers** | podman, restarted on boot | `podman-restart.service` |
| **SSD automount** (`/run/media/amirel/Amir1tb SSD`) | Persistent unit, `WantedBy=graphical-session.target`, retries `udisksctl mount` for up to 2 minutes after login | `mount-amir1tb-ssd.service` |

**Ollama** (`~/.config/systemd/user/ollama.service`) just wraps `ollama
serve` with `Restart=on-failure`:

```ini
[Unit]
Description=Ollama local LLM server
After=network-online.target

[Service]
Environment=LD_LIBRARY_PATH=%h/.local/share/ollama-app/lib/ollama
ExecStart=%h/.local/share/ollama-app/bin/ollama serve
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

`start.sh` checks for it and falls back to a plain `ollama serve` in the
background if the unit isn't installed, so the unit is a nicety, not a
hard requirement.

**ComfyUI and Voice Studio are GPU-heavy** — the same reason `start.bat` /
`start.sh` never auto-start them on Windows: loading Ollama + ComfyUI +
Voice Studio at once has driven this 8 GB laptop GPU down to ~400 MB free
VRAM before. So instead of a permanent unit file, they're launched as
**transient** systemd units with `systemd-run` when you actually need them —
you get systemd's process supervision (`systemctl --user status/stop/restart`,
`journalctl --user -u <name>`) without a unit file to maintain:

```bash
# ComfyUI
systemd-run --user --unit=comfyui-server \
  --working-directory="$HOME/my-local-ai-stack/ComfyUI" \
  --property=Restart=on-failure \
  -- .venv/bin/python main.py --listen 127.0.0.1 --port 8188

# Voice Studio
systemd-run --user --unit=voice-studio \
  --working-directory="$HOME/my-local-ai-stack/olympus/engines/voice" \
  --property=Restart=on-failure \
  -- .venv/bin/python app.py
```

Check on either with `systemctl --user status comfyui-server`; stop with
`systemctl --user stop comfyui-server`. Because they're transient, the unit
disappears once fully stopped — that's expected, just re-run the
`systemd-run` command next time you need it.

**n8n / Langfuse (podman, not Docker).** There's no Docker Desktop daemon on
Linux; containers run rootless under **podman**, and the compose files in
`foundation/` (`docker-compose.yml`, `docker-compose-langfuse.yml`) already
use fully-qualified image names (`docker.io/n8nio/n8n:latest`,
`docker.io/library/postgres:15-alpine`, etc.) specifically so `podman` /
`podman-compose` can read them without edits. Rootless podman containers
don't come back on their own after a reboot the way a Docker daemon's
`restart: unless-stopped` would — `podman-restart.service` is the systemd
user unit that replays each container's restart policy on login:

```bash
systemctl --user enable --now podman-restart.service
```

**SSD automount** (`mount-amir1tb-ssd.service`) exists because both ComfyUI's
`extra_model_paths.yaml` and the pipeline's `loras` path point at
`/run/media/amirel/Amir1tb SSD/...` — if the drive isn't mounted yet when
those start, they simply won't find their models. The unit retries
`udisksctl mount` every 5 seconds for up to 2 minutes after the graphical
session starts:

```ini
[Unit]
Description=Auto-mount Amir1tb SSD (AI models, Obsidian Vault, LifeOS)
After=graphical-session.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c "for i in $(seq 1 24); do mountpoint -q \"/run/media/amirel/Amir1tb SSD\" && exit 0; udisksctl mount -b /dev/disk/by-uuid/2A0A35510A351AF1 && exit 0; sleep 5; done; exit 1"
RemainAfterExit=yes

[Install]
WantedBy=graphical-session.target
```

If it still isn't mounted, see docs/TROUBLESHOOTING.md.

---

## 12. The anime pipeline (`olympus/engines/pipeline`)

This is the fourth "project" in the repo, alongside Ops Hub / Second Brain /
Automation, and the reason ComfyUI is more than an optional add-on now: it
turns a creative brief into a narrated, edited **recap-style anime video**
end to end (script → world bible → screenplay → storyboard → panels → voice
→ motion → assembled `.mp4`), gated at every step by a real scorecard so a
stage can't silently run on garbage from the one before it.

### Quickstart

```bash
cd olympus/engines/pipeline

# 1. Write a creative brief -- frontmatter `word_target` is required,
#    `style_exemplars` (a few sentences of prose to match tone/voice) is
#    optional. See any projects/<slug>/input/brief.md for a full example.
cat > /tmp/my-brief.md <<'EOF'
---
word_target: 700
style_exemplars:
  - "Some sentence in the voice/tone you want."
---
Genre: ... Setting: ... Protagonist: ... Themes: ...
EOF

# 2. Create the project. new-project needs a script FILE to seed the
#    project folder and pin its title_hash -- a placeholder is fine, because
#    stage0 (mode 0B, below) generates and re-pins the real script from the
#    brief.
echo "placeholder" > /tmp/placeholder.txt
python run.py new-project my-story --script /tmp/placeholder.txt

# 3. Run every stage in order (stage0 -> stage1 -> stage1r -> stage2 ->
#    stage3 -> stage3b -> stage4 -> stage3c -> stage5), skipping any stage
#    the scorecard already proves complete -- resume-safe if it dies
#    partway through:
python run.py all my-story --brief /tmp/my-brief.md

# 4. Check progress / see what's blocking a stage at any time:
python run.py report my-story
```

### CLI Reference — `run.py all` (Self-Critique Loop)

The self-critique runs **after each stage** in the pipeline, comparing the original script against stage artifacts. Use these flags to control it:

| Command | Description |
|---------|-------------|
| `python run.py all <slug> --brief <brief.md>` | **Run all stages with critique (default)** — runs stage0→stage5 sequentially, runs critique after each stage, auto-retries failed stages |
| `python run.py all <slug> --brief <brief.md> --no-critique` | **Disable critique** — runs all stages without the self-critique LLM call (faster, no intermediate validation) |
| `python run.py all <slug> --brief <brief.md> --no-retry` | **Disable auto-retry** — runs critique after each stage but does NOT re-run failed stages |

#### Visual Quick-Reference

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DEFAULT: Full critique + auto-retry                                        │
│  ─────────────────────────────────────────────────────────────────────────  │
│  python run.py all my-story --brief /tmp/my-brief.md                        │
│                                                                             │
│  Stage0 → Critique → Stage1 → Critique → Stage2 → Critique → ... → Done    │
│       │           │          │           │          │           │          │
│       ▼           ▼          ▼           ▼          ▼           ▼          ▼
│    (auto-retry on critique failure — re-runs stage, then re-critiques)      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  --no-critique: Skip all LLM critique calls                                 │
│  ─────────────────────────────────────────────────────────────────────────  │
│  python run.py all my-story --brief /tmp/my-brief.md --no-critique          │
│                                                                             │
│  Stage0 → Stage1 → Stage2 → Stage3 → Stage3b → Stage4 → Stage3c → Stage5   │
│       │          │          │          │          │          │          │  │
│       ▼          ▼          ▼          ▼          ▼          ▼          ▼  ▼
│    (fastest, no validation between stages)                                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  --no-retry: Critique runs but NO auto-retry on failure                     │
│  ─────────────────────────────────────────────────────────────────────────  │
│  python run.py all my-story --brief /tmp/my-brief.md --no-retry             │
│                                                                             │
│  Stage0 → Critique → Stage1 → Critique → ... → (stops, reports failure)    │
│       │           │          │          │                                   │
│       ▼           ▼          ▼          ▼                                   │
│    (manual intervention required on failure)                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### What the Critique Actually Does

| Stage | Critique Checks | Typical Failure Triggers |
|-------|----------------|--------------------------|
| stage0 | Scenes/shots match brief; no plot holes | Missing scenes, wrong tone |
| stage1 | Character profiles complete; voices unique | Duplicate voice IDs, missing appearance |
| stage1_world | World bible consistent; no contradictions | Location missing, timeline conflict |
| stage1r | Ref images match character/world bible | Wrong outfit in character sheet |
| stage3 | Shots use refs; blocks have correct shots | Missing camera angles |
| stage2 | Narration/dialogue matches storyboard | Character speaks out of character |
| stage3b | Panels match plates + refs; vision judge passes | Wrong character in frame |
| stage4 | Audio durations match shot timing | TTS too short/long |
| stage3c | Animation clips match panels + prompts | Tier mismatch, wrong template |
| stage5 | Final MP4 has chapters, SRT, av_sync | Missing chapters, sync drift |

#### Critique Output Files

Each critique writes to `projects/<slug>/logs/critique_<stage>_<timestamp>.json`:
```json
{
  "stage_name": "stage3b",
  "consistency_score": 0.72,
  "critical_issues": [
    {"type": "character", "description": "Rin's hair color changed from 'crimson' to 'brown'", "severity": "critical", "artifact_ref": "panels/sc-001-sh-003.png"}
  ],
  "warnings": [],
  "suggested_fixes": [
    {"stage": "stage3b", "action": "regenerate", "details": "Regenerate panel with correct hair color token in prompt"}
  ],
  "passes": false
}
```

#### Configuration

| Setting | Default | Where |
|---------|---------|-------|
| Retry threshold | `0.6` | `config.automation.critique_retry_threshold` |
| Max critique retries per stage | `1` | Hardcoded in `run_all()` |

Adjust in `stack.toml`:
```toml
[automation]
critique_retry_threshold = 0.7  # stricter: retry if score < 0.7
```

---

The finished video lands at `projects/my-story/video/final.mp4`, with
`final.srt` subtitles and a `timeline.json` alongside it. A real example
that ran this all the way through lives at
`olympus/engines/pipeline/projects/lantern-test/` — its `video/final.mp4`
and `video/final.srt` are the proof this pipeline works end to end, not just
on paper.

You can also run one stage at a time with `python run.py run <slug>
<stage>` — useful for iterating on a single stage without re-running
everything.

### The stage graph

```
stage0 ──► stage1 ──► stage1r ──► stage2 ──► stage3 ──► stage3b ──► stage4 ──► stage3c ──► stage5
intake     world      refs        screen-    story-     panels      voice       motion      assembly
           bible      +voices     play       board      (GPU)       (CPU)       plan        (ffmpeg)
```

Every arrow is a **structural gate**: `scores.require_stage()` refuses to run
a stage unless the previous one wrote `stage.done` *and* its mandatory proof
metric (e.g. stage3b won't run until stage3's `block_count` is present).
`python run.py report <slug>` prints this ledger — stage-by-stage
done/partial/pending plus any `missing_metrics` — and is the first thing to
check when a stage refuses to run (`SkippedStageError`). The full node-by-node
breakdown of both this stage graph and the ComfyUI workflow graphs it drives
lives in `olympus/engines/pipeline/workflows/NODES.md` — read that before
touching a workflow JSON or adding a stage.

### Known deviations from the original design (honest, as of 2026-07-10)

The pipeline's own config (`pipeline.toml`) and `workflows/NODES.md` are
explicit about where the current Linux install falls short of the design
spec:

- **Image model:** `krea2` is the *mandated* primary
  (`[models] image_primary = "krea2"` in `pipeline.toml`), but it has no
  weights on disk yet. Every generation today actually runs on the one
  *permitted* fallback, `flux1-schnell-Q4_K_S.gguf`
  (`image_flux_fallback.json` — see NODES.md §1 for exactly how that workflow
  is wired). The SDXL-family workflow templates (`scene_plate.json`,
  `panel_txt2img.json`, `character_sheet.json`, etc.) exist and are ready,
  but stay dormant until a permitted SDXL checkpoint replaces the
  placeholder `PATCH_*` node — every local SDXL checkpoint on this machine
  is on the model ban list.
- **Model ban list** (`pipeline.toml [models] banned`, enforced by
  `ComfyClient`/`BannedModelError`): `z-anime-distill-4step-fp8`,
  `wai-illustrious-v110`, `NoobAI-XL-v1.1`. These can never be selected for
  image generation, full stop.
- **LoRA training gap:** the design's Stage 1R mandatory per-character LoRA
  gate can't be satisfied yet — `kohya_ss` (the Windows GUI wrapper) doesn't
  run on this Linux install. The fix in progress is using its underlying
  engine directly: `tools-external/sd-scripts` is installed and callable
  without the GUI wrapper. Until that's fully wired into Stage 1R,
  `pipeline.toml`'s `[automation] allow_missing_loras = true` lets Stage 3B
  proceed anyway, and every affected project's scorecard records the
  deviation (`"lora_training": "contingency_stop (kohya unavailable on
  Linux; deviation recorded)"`) rather than silently pretending it happened.
- **GPU scheduling:** Ollama and ComfyUI were never meant to generate at the
  same time on an 8 GB card. Stage 1R and Stage 3B call
  `comfy_client.unload_ollama()` before their first generation automatically
  (fixed in commit `84d5ab8`, 2026-07-10) — you shouldn't need to do this by
  hand, but it's worth knowing it's there if you're debugging a stall.
- **Video/animation templates** (`ltx_ambient.json`, `ltx_director.json`,
  `wan_ti2v.json`) are dormant/contingency-stopped — the LTX nodes aren't
  installed on this box yet, and Wan2.2 is gated behind its own motion-second
  budget. Every shot degrades to Tier-0 oscillating drift (a plain ffmpeg pan
  in Stage 5, alternating direction per shot — Ken Burns zooms are banned by
  spec) until those land.

None of this blocks a full run end to end — `lantern-test` proves that — it
just means today's output is flux1-schnell + Tier-0 drift, not the krea2 +
LoRA + LTX/Wan pipeline the design describes as the eventual target.
