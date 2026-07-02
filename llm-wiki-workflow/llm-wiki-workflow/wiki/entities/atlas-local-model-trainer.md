---
title: "Atlas: Local Model Trainer"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-hermes-bridge.md
  - wiki/concepts/model-router.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: medium
summary: Prepares fine-tuning datasets from Agent Atlas's own run history and Obsidian notes, enabling local model improvement over time.
---

# Atlas: Local Model Trainer

**Layer:** Platform | **ID:** `local_model_trainer`

The Local Model Trainer agent handles model improvement over time. It exports training datasets from Agent Atlas's SQLite history (agent traces, memory episodes) and Obsidian notes in formats suitable for fine-tuning local models via Ollama or other local runtimes.

## Capabilities

- **Dataset preparation** — export `agent_traces` as instruction/response pairs
- **Obsidian fine-tuning data** — format vault notes as training examples
- **Format conversion** — output in Alpaca, ShareGPT, or JSONL formats
- **Training trigger** — initiate fine-tuning via Ollama API (where supported)

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `operation` (prepare/export/train), `source` (traces/obsidian/both), `model_target` |
| **Outputs** | Dataset file path, training job ID, or completion status |
| **Message type** | `prepare` |

## Why it matters

Every interaction with Agent Atlas generates training signal — task inputs, agent outputs, evaluator scores. Over time, the Local Model Trainer can distill this into a fine-tuned local model that performs better on your specific use cases without sending data to the cloud.

## Connections
- Data source: SQLite `agent_traces`, `memory_episodes` tables
- Data source: Obsidian vault via [[entities/atlas-obsidian-brain]]
- Trains: Local models accessible via [[entities/atlas-hermes-bridge]]
