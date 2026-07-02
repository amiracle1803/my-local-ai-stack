---
title: "Atlas: Observability Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Collects and analyzes agent performance metrics — call counts, latency, error rates — exposed via /api/metrics and the /logs web UI page.
---

# Atlas: Observability Agent

**Layer:** Platform | **ID:** `observability`

The Observability Agent is the monitoring system for Agent Atlas itself. It collects metrics on every agent call, tracks model usage, and exposes the data via the `/logs` web UI page and `/api/metrics` endpoints.

## Metrics collected

| Metric | Description |
|---|---|
| `call_count` | Total invocations per agent |
| `success_rate` | Fraction of successful completions |
| `avg_latency_ms` | Average duration per agent call |
| `token_usage` | Token count per model per call |
| `error_count` | Count of failed or blocked calls |

## Data flow

Every agent call goes through `handle_traced()` in the base class, which writes to the `agent_traces` table. The Observability Agent aggregates this into the `metrics` table.

## API endpoints

- `GET /api/metrics/agents` — per-agent call counts and latency
- `GET /api/metrics/models` — model usage breakdown

## Web UI

The `/logs` page in the Agent Atlas web UI shows these metrics in real time, letting you see which agents are most active, which are slow, and which models are being used.

## Connections
- Reads from: `agent_traces` SQLite table (written by every agent's `handle_traced`)
- Exposes to: Web UI `/logs` page, `/api/metrics/*` endpoints
