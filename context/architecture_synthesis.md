# Architecture Synthesis: How Both Articles Converge for This Project

This document connects the concepts from both reference articles into a unified architecture for the nvidia-agent-frontend project.

## The Two Pillars

| Pillar | Source | What It Provides |
|---|---|---|
| **Filesystem & Bash Agents** | Vercel blog | The agent's ability to *act* — explore, search, read, and manipulate data using sandboxed Unix commands |
| **Self-Organizing Memory** | MarkTechPost article | The agent's ability to *remember* — extract, categorize, consolidate, and retrieve knowledge across interactions |

These are complementary, not competing. One gives the agent hands (filesystem/bash tools); the other gives it long-term memory.

## Unified Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Flask Frontend                        │
│              (User interaction layer)                    │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│                   WorkerAgent                            │
│         (Reasoning via Ollama API)                       │
│                                                          │
│  Inputs:                                                 │
│    - User message                                        │
│    - Retrieved memory context (from MemoryManager)       │
│    - Filesystem exploration results (from Sandbox)       │
│                                                          │
│  Outputs:                                                │
│    - Response to user                                    │
│    - Tool calls (bash commands to sandbox)               │
│    - Raw interaction pair → MemoryManager                │
└─────┬──────────────────────────────┬─────────────────────┘
      │                              │
      ▼                              ▼
┌───────────────────┐  ┌─────────────────────────────────┐
│    Sandbox        │  │       MemoryManager              │
│  (Filesystem &    │  │  (Extraction & Consolidation)    │
│   Bash execution) │  │                                  │
│                   │  │  - Extracts typed memory cells    │
│  - ls, grep, cat  │  │  - Assigns scenes & salience     │
│  - find, awk      │  │  - Consolidates scene summaries  │
│  - Isolated env   │  │  - Retrieves relevant context    │
└───────────────────┘  └──────────────┬────────────────────┘
                                      │
                       ┌──────────────▼────────────────────┐
                       │          MemoryDB                 │
                       │     (SQLite + FTS5)               │
                       │                                   │
                       │  Tables:                          │
                       │    mem_cells (atomic memories)    │
                       │    mem_scenes (summaries)         │
                       │    mem_cells_fts (search index)   │
                       └───────────────────────────────────┘
```

## How They Work Together

### During a single interaction:

1. **User sends message** via Flask frontend
2. **MemoryManager retrieves** relevant memories (FTS search → salience fallback)
3. **WorkerAgent reasons** using Ollama, with memory context in prompt
4. **If the task requires data exploration**, WorkerAgent issues bash commands to the Sandbox
5. Sandbox results feed back into WorkerAgent's reasoning loop
6. **WorkerAgent responds** to user
7. **MemoryManager extracts** new memory cells from the (user, assistant) pair
8. Affected **scenes consolidate** automatically

### The filesystem serves two roles:

1. **Agent workspace** — the sandbox where the agent explores and manipulates data (Vercel pattern)
2. **Persistent memory backing** — SQLite files and potentially file-based memory exports

## Key Design Decisions to Make During Implementation

### Ollama vs OpenAI
The memory article uses OpenAI's gpt-4o-mini. This project uses **Ollama** (local models). Implications:
- Extraction and consolidation prompts must work with local model capabilities
- May need to adjust temperature and prompt formats for the specific Ollama model
- Benefit: no API costs, full local control, privacy

### Sandbox Implementation
The Vercel article uses cloud sandboxes. For a local Ollama setup:
- Consider using Python's `subprocess` with restricted permissions
- Or Docker containers for true isolation
- Or `chroot`/namespace-based sandboxing
- The key principle remains: **separate the agent's reasoning from its execution environment**

### Memory Retrieval: Start Simple
- Begin with SQLite FTS5 (symbolic retrieval) as the article demonstrates
- Add vector embeddings later only if keyword search proves insufficient
- Ollama can generate embeddings locally if needed (no external API dependency)

## Module Boundaries (Extreme Modularization)

Following the project vision's emphasis on modularization:

```
project/
├── app.py                    # Flask entry point
├── agents/
│   ├── worker.py             # WorkerAgent — reasoning loop
│   └── tools.py              # Tool definitions for bash/filesystem
├── memory/
│   ├── db.py                 # MemoryDB — SQLite schema and operations
│   ├── manager.py            # MemoryManager — extraction & consolidation
│   └── retrieval.py          # Retrieval strategies (FTS, salience fallback)
├── sandbox/
│   ├── executor.py           # Bash command execution (isolated)
│   └── filesystem.py         # Filesystem operations and data layout
├── ollama/
│   ├── client.py             # Ollama API wrapper
│   └── prompts.py            # Prompt templates for extraction, consolidation, reasoning
├── config/
│   └── settings.py           # Environment variables, model config
├── context/                  # Project planning and research notes
└── tests/                    # Test suite mirroring module structure
```

Each module has a single responsibility. Dependencies flow inward (agents depend on memory and sandbox; memory depends on db; nothing depends on agents).

## What to Build First

Suggested implementation order based on dependency chain:

1. **Ollama client** — verify API connectivity and basic prompt/response
2. **MemoryDB** — SQLite schema, insert, query operations
3. **MemoryManager** — extraction and consolidation using Ollama
4. **Retrieval** — FTS search + salience fallback
5. **Sandbox** — bash command execution with isolation
6. **WorkerAgent** — reasoning loop tying memory + sandbox together
7. **Flask frontend** — UI layer on top of the working agent
8. **Logging, monitoring, error handling** — cross-cutting concerns woven through all modules
