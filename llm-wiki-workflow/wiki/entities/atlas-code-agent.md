---
title: "Atlas: Code Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-action-hub.md
  - wiki/entities/atlas-guardian.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Generates, edits, and executes code using LLM + repo-map context. All file writes and shell executions are policy-gated by Guardian.
---

# Atlas: Code Agent

**Layer:** Action | **ID:** `code_agent`

The Code Agent handles any task that involves writing, editing, or executing code. It builds a repo-map of the target codebase for context, generates code with the LLM, and can write files or run shell commands — all gated by the Guardian policy engine.

## Capabilities

- **Generate code** — new files, functions, scripts from natural language
- **Edit code** — surgical changes to existing files with diff context
- **Execute code** — run shell commands and return stdout/stderr
- **Repo-map** — builds a tree view of the repo to help LLM understand structure

## Repo map

```python
def _build_repo_map(repo_path: str, depth: int = 3) -> str:
    # Returns a tree like:
    # src/
    #   api/
    #     run.py (42 lines)
    #     agents.py (118 lines)
    #   services/
    #     model_router.py (201 lines)
    ...
```

This context is prepended to every LLM call so the model knows what files exist and their sizes before suggesting edits.

## Tools available

| Tool | Effect | Guardian required |
|---|---|---|
| `file_read` | Read any file | No |
| `file_write` | Write/overwrite a file | Yes (warn) |
| `shell_exec` | Run a shell command | Yes (warn/block for rm -rf etc.) |
| `http_get` | Fetch a URL | Yes (warn) |
| `http_post` | POST to an endpoint | Yes (warn) |

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `task`, `repo_path` (optional), `files_context` |
| **Outputs** | `code`, `files_written`, `shell_output` |
| **Message type** | `code_request` |

## Model preference
`hermes_local` (coding-optimized local model) → `groq_powerful` → `claude`

## Connections
- Called by: [[entities/atlas-action-hub]]
- Checked by: [[entities/atlas-guardian]] before every file write / shell exec
