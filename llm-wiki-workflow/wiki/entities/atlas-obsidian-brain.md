---
title: "Atlas: Obsidian Brain Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-knowledge-hub.md
  - wiki/entities/atlas-memory-agent.md
  - wiki/entities/obsidian.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Semantic search, summarize, and append to the Obsidian vault — the bridge between Agent Atlas and your personal knowledge base, including this LLM Wiki.
---

# Atlas: Obsidian Brain Agent

**Layer:** Knowledge | **ID:** `obsidian_brain`

The Obsidian Brain agent is the interface between Agent Atlas and the Obsidian vault. It indexes the entire vault into ChromaDB on startup, enables hybrid search (vector + keyword), and can write new notes or append to existing ones.

## Capabilities

### 1. Vault indexing (`index_vault`)

On Agent Atlas startup, recursively walks all `.md` files in the vault:
1. Parses YAML frontmatter and wikilinks
2. Detects changes via MD5 content hash
3. Stores in `obsidian_notes` SQLite table
4. Embeds text into ChromaDB with `nomic-embed-text-v1.5`

**This is why syncing the LLM Wiki to `Atlas/Knowledge/` matters** — once synced, all wiki pages are indexed here and searchable by any agent.

### 2. Search (`search`)

Hybrid retrieval: semantic (vector similarity) + keyword (SQLite FTS) ranked and merged.

```python
results = await obsidian_brain.search(
    query="What agent handles file operations?",
    top_k=5
)
# Returns list of {path, title, excerpt, score}
```

### 3. Summarize (`summarize`)

Takes a path or search result and generates a structured summary using the LLM.

### 4. Append (`append`)

Writes new content to existing vault notes (daily sessions, project notes):
```python
await obsidian_brain.append(
    path="Atlas/Sessions/2026-06-23.md",
    content="## 14:32 · orchestrator\n**Goal:** Research RAG...\n**Response:** ...\n\n---"
)
```

## Vault structure it manages

```
Obsidian Vault/
└── Atlas/
    ├── Sessions/      ← daily run logs (appended by every task)
    ├── Projects/      ← per-project context
    ├── Profile/       ← user facts from Memory Agent
    └── Knowledge/     ← this LLM Wiki syncs here
```

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | operation (`search`/`summarize`/`append`), query or content |
| **Outputs** | search results, summaries, or write confirmation |
| **Message type** | `obsidian_search` |

## Connections
- Called by: [[entities/atlas-knowledge-hub]] (parallel with Retrieval Agent)
- Writes to: [[entities/obsidian]] vault
- Indexes: this LLM Wiki (via `Atlas/Knowledge/` sync)
