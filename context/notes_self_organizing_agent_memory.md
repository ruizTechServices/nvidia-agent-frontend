# Notes: How to Build a Self-Organizing Agent Memory System for Long-Term AI Reasoning

Source: https://www.marktechpost.com/2026/02/14/how-to-build-a-self-organizing-agent-memory-system-for-long-term-ai-reasoning/

## Core Thesis

Build a memory system where the agent automatically extracts, categorizes, and consolidates knowledge from every interaction — then retrieves relevant memories to ground future reasoning. Memory curation is deliberately separated from response generation so each function operates independently.

## Three-Component Architecture

```
┌─────────────┐     ┌────────────────┐     ┌─────────────┐
│  MemoryDB   │◄───►│ MemoryManager  │◄───►│ WorkerAgent │
│ (Storage)   │     │ (Extraction &  │     │ (Reasoning) │
│             │     │  Consolidation)│     │             │
└─────────────┘     └────────────────┘     └─────────────┘
```

### MemoryDB — Persistent Storage Layer
- Uses **SQLite** with normalized tables
- Three tables:
  - `mem_cells` — atomic memory units (scene, type, salience, content)
  - `mem_scenes` — aggregated summaries indexed by scene name
  - `mem_cells_fts` — full-text search index for symbolic retrieval (SQLite fts5)
- In-memory SQLite for speed; can be swapped to file-based for persistence

### MemoryManager — Extraction and Consolidation
- Converts raw interactions into structured memory cells
- Assigns each cell to a **scene** (topical grouping)
- Assigns a **salience score** (0.0–1.0) indicating importance
- Periodically consolidates scenes into compressed summaries

### WorkerAgent — Reasoning Interface
- Queries memory before generating responses
- Assembles retrieved context into the prompt
- After responding, hands the interaction back to MemoryManager for storage

## Memory Cell Types

Six distinct categories for classifying extracted knowledge:

| Type | Purpose |
|---|---|
| `fact` | Objective information |
| `plan` | Intended actions or strategies |
| `preference` | User or system preferences |
| `decision` | Choices made and their rationale |
| `task` | Work items or goals |
| `risk` | Potential problems or constraints |

## The Agent Loop (Full Cycle)

```
1. User provides input
2. Agent queries mem_cells_fts (full-text search on user query)
3. If no FTS matches → fallback to salience-ranked retrieval
4. Retrieved scene summaries assembled into context block
5. LLM generates response using memory context
6. MemoryManager extracts new cells from the (user, assistant) pair
7. Each new cell assigned: scene, cell_type, salience, compressed content
8. Cells inserted into mem_cells table
9. Affected scenes consolidated (summary updated)
```

## Memory Extraction Process

```python
def extract_cells(self, user, assistant) -> List[Dict]:
```

- Takes a (user_message, assistant_response) pair
- Uses the LLM to produce structured JSON with fields:
  - `scene` — topical label grouping related memories
  - `cell_type` — one of the six types above
  - `salience` — float 0.0–1.0 indicating importance
  - `content` — compressed representation of the information
- Low temperature (0.1) for consistent extraction

## Retrieval Strategy (Two-Tier Fallback)

1. **Full-text search** — tokenize user query, search `mem_cells_fts` for keyword matches
2. **Salience-ranked fallback** — when no lexical matches exist, return highest-salience cells across all scenes

This avoids vector embeddings entirely. The article uses **symbolic retrieval** (keyword/token matching + salience ranking) rather than embedding-based semantic search. This keeps the system simple and explainable.

## Scene Consolidation

```python
def consolidate_scene(self, scene):
```

- Gathers all cells for a given scene
- Uses LLM to summarize into ≤100 words
- Very low temperature (0.05) for stable, consistent summaries
- Runs incrementally after each insertion — scenes stay current
- Stored in `mem_scenes` table for fast retrieval

## Key Design Decisions

### Why SQLite (not a vector DB)?
- Full-text search via fts5 is sufficient for symbolic retrieval
- No dependency on external services
- Simple, portable, zero-config
- Salience scores provide numerical ranking without embeddings

### Why separate MemoryManager from WorkerAgent?
- Memory curation quality shouldn't depend on response generation
- Each component can be tuned independently (different temperatures, models)
- Clean separation of concerns

### Why compress content during extraction?
- Raw conversations are verbose
- Compressed cells are faster to retrieve and consume fewer tokens
- Forces the system to distill what actually matters

## What's NOT Implemented (Future Extensions)

The article explicitly mentions these as natural extensions:
- **Forgetting mechanisms** — pruning low-salience or outdated memories
- **Richer relational memory** — links between memory cells
- **Graph-based orchestration** — memory as a knowledge graph
- **Vector embeddings** — hybrid retrieval combining symbolic + semantic

## Core Libraries Used

- `sqlite3` — in-memory relational database
- `openai` — gpt-4o-mini for extraction, consolidation, and reasoning
- `json` — serialization for structured memory cells
- `datetime` — timestamping entries
- `re` — regex for query tokenization and code block cleaning

## Key Takeaways for This Project

1. **Three-component separation** — storage, memory management, and reasoning agent are independent modules
2. **Structured extraction over raw storage** — don't store conversations verbatim; extract typed, scored, compressed cells
3. **Scene-based grouping** — memories cluster by topic, not by time
4. **Salience scoring** — not all memories are equal; weight them at extraction time
5. **Consolidation keeps memory compact** — periodic summarization prevents unbounded growth
6. **Symbolic retrieval can work** — full-text search + salience ranking is a viable alternative to vector embeddings
7. **Low temperature for memory operations** — extraction (0.1) and consolidation (0.05) should be deterministic
8. **The loop is continuous** — every interaction feeds back into memory, making the agent smarter over time
9. **Start simple, extend later** — begin with SQLite + FTS, add vectors/graphs/forgetting as needed
