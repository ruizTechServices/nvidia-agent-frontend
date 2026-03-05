# Gaps and Open Questions

Identified during context review. Resolved decisions are marked with **RESOLVED**.

---

## 1. No Ollama model specified — RESOLVED
**Affects: Phase 1 and everything downstream**

The vision says "Ollama API" but never names which model. Local models vary wildly in capability.

**Decision:** No single model is hardcoded. The system will **scan available Ollama models at startup** and present them to the user in the Flask UI. The user selects which model to use. This means:
- `ollama/client.py` needs a `list_models()` function that queries the Ollama API
- The Flask frontend needs a model selector (dropdown or similar)
- The system must handle models that lack tool-calling support gracefully (see gap #2)

---

## 2. Tool-calling support is assumed, not verified — OPEN
**Affects: Phase 1, Phase 6**

The WorkerAgent design assumes Ollama models support tool-calling (function calling). Not all models do. Since the user chooses from whatever models are installed, some selected models may not support tool-calling at all.

**Still needed:** A capability detection or graceful fallback strategy. Options:
- Probe the model with a test tool-call during selection and flag models that don't respond correctly
- Fall back to prompt-based tool invocation (ask the model to output a JSON action instead of using native tool-calling)
- Warn the user in the UI that certain models have limited capabilities

---

## 3. No interface contracts between modules — RESOLVED
**Affects: All phases**

Without shared type definitions, modules will make conflicting assumptions about data shapes.

**Decision:** Create a shared `types.py` with Python dataclasses in Phase 0 scaffolding. All modules import from this single source of truth. Defines at minimum:
- `MemoryCell` — scene, cell_type, salience, content, created_at, id (optional, post-insert)
- `SceneSummary` — scene, summary, updated_at
- `ExecutionResult` — stdout, stderr, returncode
- `ChatMessage` — role, content, timestamp
- `ModelInfo` — name, size, supports_tools (populated by model scan)

---

## 4. Sandbox threat model — RESOLVED
**Affects: Phase 5**

**Decision:** The sandbox protects against **the agent only** (LLM hallucinating dangerous commands). The user is trusted. This means:
- Command whitelist defends against the model issuing destructive commands (rm, sudo, etc.)
- Path restriction confines the agent to its workspace directory (no traversal above it)
- No need for Docker-level isolation initially — `subprocess` with restricted cwd and command validation is sufficient
- The user can point the agent at any local path they choose (they're trusted)

---

## 5. No defined data domain for the filesystem agent — RESOLVED
**Affects: Phase 5, Phase 6**

**Decision:** Two data domains:
1. **Conversation history** — the agent can explore and search its own past interactions (aligned with the memory article's approach)
2. **User-uploaded and user-pointed files** — the agent navigates files and folders the user provides, either via:
   - **File upload** through the Flask UI (stored in the agent's workspace)
   - **Path-based exploration** where the user gives a local directory path and the agent explores it in place

This means `sandbox/filesystem.py` must support both: a managed workspace (for uploads) and pass-through access (for user-specified paths, since the user is trusted per gap #4).

---

## 6. Local model JSON reliability is a known risk — OPEN
**Affects: Phase 3**

Local Ollama models produce less reliable structured JSON than OpenAI. This is worse now that the user can select any installed model (gap #1 decision), including small or older ones.

**Still needed:** A robust JSON parsing layer in `memory/manager.py` with:
- Code fence stripping (`\`\`\`json ... \`\`\``)
- Preamble/postamble removal (text before/after the JSON)
- JSON repair attempts (trailing commas, unquoted keys)
- Defined failure mode: skip extraction for this interaction, log the failure, still return the response to the user

---

## 7. No error recovery in the agent loop — OPEN
**Affects: Phase 6**

The agent loop describes only the happy path. Failure scenarios are unaddressed.

**Still needed:** Error boundaries for each step. Guiding principle per gap #8 decision (logging from Phase 0): every failure is logged, and the response always reaches the user. Proposed boundaries:
- Memory retrieval fails → proceed without context, log warning
- Tool execution fails → return error description to the LLM, let it decide how to proceed
- Memory extraction fails → skip storage for this interaction, log error
- Ollama unreachable → return error to user via Flask, don't crash the server

---

## 8. Cross-cutting concerns deferred to last phase — RESOLVED
**Affects: All phases**

**Decision:** Build logging and error handling into every module from Phase 0. Specifically:
- Phase 0 sets up: logging config (structured, per-module loggers), base exception hierarchy (in `types.py` or a dedicated `exceptions.py`)
- Every subsequent phase uses them from the start
- Phase 8 is repurposed as "audit, harden, and add monitoring endpoints" rather than "add from scratch"

---

## 9. FTS5 availability on Windows not validated — OPEN
**Affects: Phase 2**

This project runs on Windows (MINGW64_NT). SQLite FTS5 may not be available on all Python Windows distributions.

**Still needed:** Validate early in Phase 2 by running:
```python
import sqlite3
conn = sqlite3.connect(":memory:")
conn.execute("CREATE VIRTUAL TABLE test USING fts5(content)")
```
If this fails, fall back to LIKE queries with manual tokenization.

---

## 10. No conversation history management — RESOLVED
**Affects: Phase 6, Phase 7**

Memory cells are lossy compressions, not the raw chat. The user expects to see actual messages.

**Decision:** Persist raw conversation history to SQLite. Add a `conversations` table to MemoryDB:
- Schema: `(id, user_msg, assistant_msg, model_used, timestamp)`
- Flask frontend reads from this for chat display
- MemoryManager reads from this for extraction
- Survives server restarts

This table is defined in Phase 2 (MemoryDB schema) alongside the memory tables.
