# ADR-001: Prime-Agent Port — Background Daemon Sessions + Memory Snapshots in Angelic Harness

## Status
Accepted

## Date
2026-08-17

## Context
The local AI stack uses the Angelic Harness (`harness/`) — a stdlib-only Python task loop with INTAKE→PLANNING→EXECUTION→VERIFICATION→DELIVERY state machine, file-based memory, and side-effect gates. It lacked two capabilities present in the upstream prime-agent project (MIT, ~16.6k stars, ~4.5k commits):

1. **Background/daemon task execution** — prime-agent runs agent sessions as detached background processes with heartbeat + log streaming, reattachable via `prime status <id>` / `prime attach <id>`.
2. **Refine snapshots + rollback** — prime-agent's `/refine` command snapshots the agent's memory state before a self-modification and rolls back if the change degrades performance. This maps to: snapshot the harness memory index before each task; on task FAILED, restore the recall baseline so failed-task noise doesn't pollute future evidence retrieval.

The DeepSeek Harness fork (`harness-deepseek/`, vendored Cordis, v0.1.0-rc.5) was explicitly excluded per user directive.

## Decision
Port the two prime-agent capabilities into `harness/` (Angelic Harness) with minimal, surgical changes:

### 1. Background Daemon Sessions
- `harness/daemon.py` (new): `spawn()`, `status()`, `attach()`, `child_main()`, heartbeat JSON (`logs/heartbeat.json`), transcript log (`logs/daemon.log`), daemon record (`logs/daemon.json`).
- `harness/core/runstate.py`: `create_task(..., task_id=None)` — allows pinning a run dir for the child.
- `harness/core/loop.py`: `run_task(..., task_id=None)` — passes task_id through; called by child with `emit` streaming to log + heartbeat.
- `harness/cli.py`: `run --background "<goal>"`, `status <task-id>`, `attach <task-id>`, hidden `daemon-run` child entry.

### 2. Memory Snapshots + Rollback
- `harness/core/memory.py`: `snapshot_index()`, `rollback_index()`, `list_snapshots()` — uses the existing unused `snapshots/` STRATA directory.
- `harness/core/loop.py`: `run_task` calls `snapshot_index()` at task start; on FAILED path (after `_writeback_episode`), calls `rollback_index(snap_id)` to restore the MEMORY.md baseline. Evidence files (error/episode entries) remain on disk; only the index reverts.
- `harness/tests/test_loop.py` env fixture: binds `snapshot_index`/`rollback_index` to tmp memory dir so tests never pollute real `harness/memory/`.

### Skipped (deliberate)
- Persistent IPython + RLM (reinforcement learning model) loop
- Agent-to-agent messaging
- Autonomous schedules / heartbeats / budget daemons

## Alternatives Considered
| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Use DeepSeek Harness (`harness-deepseek/`) instead | Has append-only `SessionEvent` log, mature plugin system, ACP/JSON-RPC subagent protocol | 1.6GB, vendored Cordis, pre-release, Node.js heavy, different architecture | Rejected — user explicit: "not the deepseek harness one" |
| Keep Angelic Harness as-is | Simple, stdlib-only, already working | No background sessions, no memory rollback on failure | Rejected — missing desired UX |
| Full prime-agent integration | All features | Heavy rewrite, different language (Python but different architecture), external dep | Rejected — user wanted only the good parts ported |

## Consequences
- **Positive**: Background tasks now work (`harness run --background "goal"` → detached, `harness status <id>`, `harness attach <id>`). Failed tasks no longer pollute recall state (evidence files preserved, index restored). All 61 harness tests pass.
- **Negative**: Slight increase in `harness/` complexity (new `daemon.py`, 3 new test files). The daemon child uses the same ModelPort → Ollama, so background tasks still need Ollama running.
- **Neutral**: No changes to `harness-deepseek/` or other components.

## Verification
- `pytest harness/tests -q` → 61 passed
- Live smoke test: `harness run --background "Write a one-line haiku to haiku.txt"` → spawned detached task (PID 1679682), heartbeat streamed through INTAKE→PLANNING→EXECUTION, artifact written, attach/tailed successfully.