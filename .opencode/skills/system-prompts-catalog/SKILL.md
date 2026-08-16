---
name: system-prompts-catalog
description: "Searchable catalog of 130+ leaked/released AI system prompts from major providers (Anthropic, OpenAI, Google, xAI, etc.). Use when studying prompt engineering patterns, comparing safety mechanisms across providers, analyzing tool schemas, or researching how commercial AI systems are instructed to behave. NOT for adversarial use — this is a reference library for learning and defense."
compatibility:
  tools: ["bash", "read_file", "list_files"]
  frameworks: ["python"]
---

# System Prompts Catalog

Reference library of published/released AI system prompts from 16 providers.
Source: `tools-external/skills-audit/system_prompts_leaks/`

## How to Use

### Search across all prompts
```bash
grep -ril "keyword" tools-external/skills-audit/system_prompts_leaks/
```

### Browse by provider
- `Anthropic/` — Claude models (27+ prompts, including Claude Code agents/skills)
- `OpenAI/` — ChatGPT/GPT-5.x/Codex (53+ prompts)
- `Google/` — Gemini family (22+ prompts)
- `xAI/` — Grok family (11 prompts)
- `Microsoft/` — Copilot family (5 prompts)
- `Perplexity/` — Comet, Deep Research, Voice (4 prompts)
- `Misc/` — Cursor, Devin, Brave, Zed, Warp, etc. (23 prompts)

### Key areas to study
1. **Safety mechanisms** — How each provider handles refusals, jailbreaks, and harmful content
2. **Tool schemas** — Function calling definitions, parameter validation, permission models
3. **Persona design** — How personality, tone, and behavior are encoded
4. **Context management** — Conversation length handling, memory, summarization
5. **Code execution** — How providers sandbox and control code generation

### Python search helper
Use `scripts/search_prompts.py` to search with context and ranking:
```bash
python scripts/search_prompts.py "prompt injection" --context 3
python scripts/search_prompts.py --provider anthropic --topic safety
```

## Ethical Use

This catalog exists for:
- **Learning** how AI systems are instructed
- **Defense** against adversarial prompt attacks
- **Research** into AI safety and alignment
- **Comparison** of provider approaches to similar problems

Do NOT use to:
- Craft jailbreaks or adversarial prompts
- Bypass safety mechanisms in production systems
- Impersonate or spoof AI system behavior
