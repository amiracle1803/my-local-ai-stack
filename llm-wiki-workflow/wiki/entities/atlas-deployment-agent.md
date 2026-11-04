---
title: "Atlas: Deployment Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: medium
summary: Manages deployment operations — status checks, log retrieval, and rollback coordination for services managed by Agent Atlas.
---

# Atlas: Deployment Agent

**Layer:** Platform | **ID:** `deployment_agent`

The Deployment Agent handles infrastructure-adjacent tasks — checking deployment status, retrieving service logs, and coordinating rollbacks when things go wrong.

## Capabilities

- **Status** — check whether a service or deployment is healthy
- **Logs** — retrieve recent logs from a deployment
- **Rollback** — initiate a rollback to a previous version
- **Deploy** — trigger a deployment (gated by Guardian for production targets)

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `operation` (status/logs/rollback/deploy), `target`, `version` |
| **Outputs** | Status data, log excerpts, or operation confirmation |
| **Message type** | `deploy_request` |

## Guardian policy
All production deployments are `high` or `critical` risk and require human review before execution.

## Connections
- Called by: [[entities/atlas-orchestrator]], [[entities/atlas-background-runtime]]
- Gated by: [[entities/atlas-guardian]]
