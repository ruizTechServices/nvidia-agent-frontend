# TODO

## Environments

| | **Dev (Windows)** | **Production (Nvidia Jetson Orin Nano)** |
|---|---|---|
| **OS** | Windows 11 (MINGW64/Git Bash) | Ubuntu 22.04 L4T (JetPack 6.2) |
| **Arch** | x86_64 | ARM64 (aarch64) |
| **RAM** | Plenty | 4–8 GB LPDDR5 (shared CPU/GPU) |
| **Storage** | Local SSD | NVMe SSD recommended (microSD fallback) |
| **Python** | 3.13 (.venv) | System Python 3.10+ (.venv) |
| **Ollama** | Native Windows build | ARM64 JetPack build (systemd service) |
| **Models** | Any size | 4GB: phi3:mini, tinyllama / 8GB: llama3.2:3b, qwen3:8b (Q4_K_M) |
| **Flask** | `flask run` (dev server) | gunicorn + systemd + optional nginx reverse proxy |
| **Power** | Unconstrained | 7–25W TDP, active cooling recommended for sustained inference |

---

## Phase 0: Project Scaffolding
- [x] Initialize git repository
- [x] Create virtual environment (.venv)
- [x] Populate requirements.txt with pinned versions (ollama, flask, python-dotenv, pytest)
- [x] Create .gitignore (venv, __pycache__, .env, *.db)
- [x] Create .env.example with placeholder keys (OLLAMA_HOST, FLASK_SECRET_KEY, etc.)
- [x] Create config/settings.py — load env vars, define temperatures, DB path
- [x] Create models.py (renamed from types.py to avoid stdlib conflict) — shared dataclasses used by all modules:
  - [x] `MemoryCell` — scene, cell_type, salience, content, created_at, id (optional)
  - [x] `SceneSummary` — scene, summary, updated_at
  - [x] `ExecutionResult` — stdout, stderr, returncode
  - [x] `ChatMessage` — role, content, timestamp
  - [x] `ModelInfo` — name, size, supports_tools
- [x] Create exceptions.py — base exception hierarchy:
  - [x] `OllamaConnectionError`, `OllamaTimeoutError`
  - [x] `MemoryExtractionError` (invalid JSON from LLM)
  - [x] `SandboxSecurityError` (blocked command), `SandboxTimeoutError`
- [x] Set up logging config — structured, per-module loggers (used from Phase 1 onward)
- [x] Scaffold directory structure:
  ```
  app.py
  models.py
  exceptions.py
  config/settings.py
  ollama_client/client.py
  ollama_client/prompts.py
  memory/db.py
  memory/manager.py
  memory/retrieval.py
  sandbox/executor.py
  sandbox/filesystem.py
  agents/worker.py
  agents/tools.py
  templates/
  static/
  tests/
  ```
- [x] Add __init__.py files to each package

## Phase 1: Ollama Client (`ollama_client/`)
> Leaf dependency — nothing else works without this.
- [x] ollama_client/client.py — wrapper around the ollama Python library
  - [x] list_models() → List[ModelInfo] — scan system for all available Ollama models
  - [x] connect(model_name) — verify Ollama is running and model is available
  - [x] chat(prompt, temperature, max_tokens) — single prompt/response call
  - [x] chat_with_tools(prompt, tools) — tool-calling variant for agent loop
  - [x] embed(text) — generate embeddings (for future use)
- [x] ollama_client/prompts.py — prompt templates stored as strings/functions
  - [x] MEMORY_EXTRACTION_PROMPT — instruct model to produce typed JSON cells
  - [x] SCENE_CONSOLIDATION_PROMPT — instruct model to summarize scene in ≤100 words
  - [x] AGENT_SYSTEM_PROMPT — base system prompt for the WorkerAgent
- [x] Write test: tests/test_ollama_client.py — verify connectivity, model listing, basic response
- [x] Use logging and custom exceptions from Phase 0 in all functions

## Phase 2: Memory Database (`memory/db.py`)
> Leaf dependency — pure storage, no LLM calls.
> **Cross-platform note**: Must work on both Windows (dev) and ARM64 Ubuntu L4T (Orin Nano).
- [ ] Validate FTS5 availability on **both** environments:
  ```python
  import sqlite3
  conn = sqlite3.connect(":memory:")
  conn.execute("CREATE VIRTUAL TABLE test USING fts5(content)")
  ```
  If it fails on either platform, implement LIKE-based fallback with manual tokenization.
  FTS5 is expected to work on both (standard CPython includes it), but verify on the Orin Nano's system Python.
- [ ] memory/db.py — SQLite wrapper with schema management
  - [ ] init_db(path) — create tables if not exist:
    - `mem_cells` (id, scene, cell_type, salience, content, created_at)
    - `mem_scenes` (scene, summary, updated_at)
    - `mem_cells_fts` — FTS5 virtual table on mem_cells.content (with LIKE fallback)
    - `conversations` (id, user_msg, assistant_msg, model_used, timestamp)
  - [ ] insert_cell(MemoryCell) → cell_id
  - [ ] get_cells_by_scene(scene) → List[MemoryCell]
  - [ ] search_fts(query, limit) → List[MemoryCell]
  - [ ] get_top_salient(limit) → List[MemoryCell] — fallback retrieval
  - [ ] upsert_scene_summary(scene, summary)
  - [ ] get_scene_summary(scene) → SceneSummary
  - [ ] get_all_scene_summaries() → List[SceneSummary]
  - [ ] insert_conversation(user_msg, assistant_msg, model_used) → conversation_id
  - [ ] get_conversations(limit, offset) → List[ChatMessage]
- [ ] **Orin Nano constraint**: DB size cap or pruning hook — with 4–8 GB shared RAM, avoid unbounded DB growth eating into memory available for Ollama models
  - [ ] Add `get_db_size_bytes()` utility for monitoring
  - [ ] Add `MAX_DB_SIZE_MB` setting in config/settings.py (default: 256 MB)
- [ ] Write tests: tests/test_memory_db.py — insert, query, FTS search, salience ranking, conversation CRUD
- [ ] Use logging and custom exceptions from Phase 0

## Phase 3: Memory Manager (`memory/manager.py`)
> Depends on: Phase 1 (ollama client) + Phase 2 (memory db).
> **Orin Nano note**: Extraction and consolidation are secondary LLM calls. On constrained hardware, these compete with the main chat inference for shared RAM. Keep prompts short and consider batching or deferring consolidation.
- [ ] memory/manager.py — extraction and consolidation logic
  - [ ] extract_cells(user_msg, assistant_msg) → List[MemoryCell]
    - Calls ollama client with MEMORY_EXTRACTION_PROMPT
    - Robust JSON parsing layer:
      - Strip markdown code fences
      - Remove preamble/postamble text around JSON
      - Attempt JSON repair (trailing commas, unquoted keys)
      - On failure: log error, return empty list (don't crash)
    - Validate cell_type is one of: fact, plan, preference, decision, task, risk
    - Validate salience is float 0.0–1.0
  - [ ] store_cells(cells) — insert each cell into db, then consolidate affected scenes
  - [ ] consolidate_scene(scene) — summarize all cells for a scene via LLM (temp 0.05)
  - [ ] process_interaction(user_msg, assistant_msg) — full pipeline: extract → store → consolidate
  - [ ] **Orin Nano**: Make extraction/consolidation async-friendly so it can run after the response is returned to the user (don't block the chat response on memory processing)
- [ ] Write tests: tests/test_memory_manager.py — extraction parsing, malformed JSON handling, consolidation, full cycle

## Phase 4: Memory Retrieval (`memory/retrieval.py`)
> Depends on: Phase 2 (memory db).
- [ ] memory/retrieval.py — two-tier retrieval strategy
  - [ ] retrieve(query, limit) → List[MemoryCell]
    - Tier 1: FTS search on tokenized query
    - Tier 2 (fallback): salience-ranked cells if FTS returns nothing
  - [ ] build_context_block(query) → str — assemble retrieved memories + scene summaries into a prompt-ready string
  - [ ] **Orin Nano**: Cap context block size to respect smaller model context windows (e.g., 2048–4096 tokens for small quantized models)
- [ ] Write tests: tests/test_memory_retrieval.py — FTS hits, salience fallback, context assembly

## Phase 5: Sandbox (`sandbox/`)
> Independent of memory. Can be built in parallel with Phases 3–4.
> Threat model: protect against agent (LLM) only. User is trusted.
> **Cross-platform note**: Dev runs on Windows (Git Bash/MINGW64), production runs on ARM64 Ubuntu. Shell commands and paths differ.
- [ ] sandbox/executor.py — isolated command execution via subprocess
  - [ ] execute(command, cwd, timeout) → ExecutionResult
  - [ ] **Platform-aware command whitelist**:
    - Linux (Orin Nano): ls, grep, cat, find, head, tail, wc, awk, df, free, nvidia-smi, jtop
    - Windows (dev): dir, findstr, type, where (or rely on Git Bash providing Unix equivalents)
    - Detect platform at startup and load appropriate whitelist
  - [ ] Block dangerous commands: rm -rf, sudo, chmod, chown, network tools, shutdown, reboot
  - [ ] **Orin Nano additions to blocklist**: jetson_clocks, nvpmodel (power/clock manipulation)
  - [ ] Path validation: prevent traversal above the workspace root
  - [ ] Enforce timeout to prevent hanging processes (especially important on Orin Nano — a stuck inference + stuck subprocess = OOM)
  - [ ] Raise SandboxSecurityError / SandboxTimeoutError from exceptions.py
- [ ] sandbox/filesystem.py — workspace management
  - [ ] create_workspace(name) → path — create a managed directory for uploads
  - [ ] register_path(user_path) → path — validate and register a user-specified local path for exploration
  - [ ] list_workspace(path) → directory listing
  - [ ] handle_upload(file) → path — save uploaded file into managed workspace
  - [ ] cleanup_workspace(path) — remove temporary workspaces
  - [ ] **Orin Nano**: Respect storage constraints — check available disk space before accepting uploads
- [ ] Write tests: tests/test_sandbox.py — allowed commands, blocked commands, path traversal rejection, timeout, upload handling
  - [ ] Test both Linux and Windows whitelists (mock `sys.platform`)

## Phase 6: Worker Agent (`agents/`)
> Depends on: All previous phases. This is the orchestrator.
- [ ] agents/tools.py — tool definitions the agent can invoke
  - [ ] Define bash_tool — schema describing the bash command tool for Ollama tool-calling
  - [ ] Define memory_search_tool — schema for querying memory
  - [ ] **Orin Nano**: Define system_status_tool — query GPU temp, RAM usage, power mode via nvidia-smi / jtop
  - [ ] Tool dispatch: route tool calls to sandbox.executor or memory.retrieval
- [ ] agents/worker.py — the reasoning loop
  - [ ] run(user_message, model_name) → str
    1. Retrieve memory context via memory.retrieval.build_context_block()
    2. Build prompt: system prompt + memory context + user message
    3. Call ollama client with tools available
    4. If tool call returned → execute tool → feed result back → re-call LLM
    5. Repeat tool loop until LLM returns final text response (max iterations cap to prevent runaway loops on small models)
    6. Store raw conversation via memory.db.insert_conversation()
    7. Pass (user_message, response) to memory.manager.process_interaction() (non-blocking on Orin Nano)
    8. Return response
  - [ ] Error boundaries:
    - Memory retrieval fails → proceed without context, log warning
    - Tool execution fails → return error to LLM, let it adapt
    - Memory extraction fails → skip storage, log error, still return response
    - Ollama unreachable → return error message to user, don't crash
    - **Orin Nano**: OOM from Ollama → catch, log, suggest smaller model or fewer concurrent requests
  - [ ] Handle multi-turn tool calls (agent may need several bash commands in sequence)
  - [ ] **Orin Nano**: Cap tool-call iterations (default: 5) to avoid exhausting RAM on long chains
- [ ] Write tests: tests/test_worker_agent.py — single turn, multi-tool turn, memory integration, error recovery

## Phase 7: Flask Frontend (`app.py`)
> Depends on: Phase 6 (worker agent).
> **Orin Nano deployment**: Production uses gunicorn (2 workers max) behind optional nginx, managed via systemd.
- [ ] app.py — Flask application
  - [ ] GET / — serve chat UI with model selector dropdown
  - [ ] GET /models — return list of available Ollama models (calls ollama_client.client.list_models())
  - [ ] POST /chat — accept user message + selected model, call worker.run(), return response
  - [ ] POST /upload — accept file upload, store via sandbox.filesystem.handle_upload()
  - [ ] POST /explore — accept a local directory path, register via sandbox.filesystem.register_path()
  - [ ] GET /history — return conversation history from DB
  - [ ] GET /memory — debug endpoint showing current memory state (scenes, cells)
  - [ ] GET /health — health check: Ollama reachable, DB initialized, system resources
    - [ ] **Orin Nano**: Include GPU temp, RAM usage, power mode, disk space in health response
  - [ ] GET /system — **Orin Nano**: Jetson system info (JetPack version, CUDA version, power mode, thermal state)
- [ ] templates/ — HTML/JS chat interface
  - [ ] chat.html — model selector, message input, response display, scrollable history, file upload
  - [ ] **Orin Nano**: Display system resource indicators in the UI (RAM bar, GPU temp badge)
- [ ] static/ — CSS/JS assets
- [ ] Write tests: tests/test_app.py — route responses, chat round-trip, upload handling
- [ ] **Deployment artifacts**:
  - [ ] `deploy/nvidia-agent.service` — systemd unit file for gunicorn
  - [ ] `deploy/nginx.conf` — optional nginx reverse proxy config
  - [ ] `deploy/setup_orin.sh` — one-shot setup script: install deps, create venv, enable service

## Phase 8: Audit and Harden
> Logging and error handling already built in from Phase 0. This phase audits coverage.
- [ ] Audit logging — verify every module logs at appropriate levels
  - [ ] Every Ollama call logs: prompt length, response time, model used
  - [ ] Every memory operation logs: cells extracted, scenes consolidated
  - [ ] Every sandbox command logs: command, exit code, duration
- [ ] Audit error handling — verify all exceptions are caught and surfaced correctly
- [ ] Monitoring — expose metrics via /health or /metrics endpoint
  - [ ] Memory cell count, scene count, DB size on disk
  - [ ] Average response time
  - [ ] Ollama model availability
  - [ ] **Orin Nano**: GPU temperature, RAM headroom, power mode, thermal throttle state
- [ ] **Orin Nano stress testing**:
  - [ ] Sustained chat session (50+ turns) — verify RAM stays stable, DB doesn't bloat
  - [ ] Concurrent requests (2–3) — verify OOM doesn't crash the system
  - [ ] Long-running uptime test — verify no memory leaks over 24+ hours
- [ ] **Cross-platform validation**:
  - [ ] All tests pass on Windows (dev)
  - [ ] All tests pass on ARM64 Ubuntu (Orin Nano)
  - [ ] FTS5 works on both platforms
  - [ ] Sandbox whitelists correct per platform

## Open Questions (resolve during implementation)
- [ ] **Gap #2**: Tool-calling detection — how to identify which Ollama models support tool-calling? Probe at startup or maintain a known-good list? (Especially relevant on Orin Nano where only small models fit)
- [ ] **Gap #6**: JSON parsing robustness — test extraction prompts against the actual models the user has installed; tune prompts if needed. Small quantized models (phi3:mini, tinyllama) may produce worse JSON than larger models.
- [ ] **Gap #9**: Validate FTS5 on both Windows and Orin Nano's system Python early in Phase 2
- [ ] **Orin Nano model recommendations**: Curate a tested list of models that fit in 4GB / 8GB shared RAM with acceptable quality for memory extraction and tool-calling. Candidates:
  - 4GB: phi3:mini (Q4_K_M, ~2.3GB), tinyllama (Q4_K_M, ~0.7GB)
  - 8GB: llama3.2:3b (Q4_K_M, ~2.0GB), qwen2.5:7b (Q4_K_M, ~4.4GB)
- [ ] **Orin Nano power mode**: Should the app auto-detect or let the user configure 7W / 15W / 25W (Super Mode) power profiles? Higher wattage = faster inference but more heat.

## Future Extensions (Not for initial build)
- [ ] Forgetting mechanism — prune low-salience or stale memories (important on Orin Nano for DB size control)
- [ ] Relational memory — links between memory cells
- [ ] Vector embeddings — hybrid retrieval (symbolic + semantic) using Ollama embeddings
- [ ] Graph-based memory orchestration
- [ ] Docker/container-based sandbox for true isolation (containers work on JetPack)
- [ ] Multi-user support with per-user memory stores
- [ ] WebSocket streaming for real-time chat responses (reduces perceived latency on slow Orin Nano inference)
- [ ] **Orin Nano GPU monitoring dashboard** — real-time tegrastats / jtop integration in the web UI
- [ ] **Model hot-swapping** — unload one model and load another without restarting Ollama (critical when only 4–8GB available)
- [ ] **Remote dev workflow** — SSH + VS Code Remote from Windows dev machine to Orin Nano for on-device testing
