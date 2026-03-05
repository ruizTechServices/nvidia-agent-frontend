# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An AI agent frontend built with Python/Flask that interfaces with the Ollama API. The project implements a self-organizing agent memory system for long-term AI reasoning and agents with filesystem/bash capabilities.

**Target hardware**: Nvidia Jetson Orin Nano (4–8 GB shared RAM, ARM64, JetPack 6.2 / Ubuntu 22.04 L4T).

**Status**: Phase 1 complete — Ollama client layer implemented with mocked tests.

## Environments

| | **Dev** | **Production** |
|---|---|---|
| OS | Windows 11 (MINGW64 / Git Bash) | Ubuntu 22.04 L4T (JetPack 6.2) |
| Arch | x86_64 | ARM64 (aarch64) |
| RAM | Unconstrained | 4–8 GB shared CPU/GPU |
| Ollama | Native Windows build | ARM64 JetPack build (systemd) |
| Flask | `flask run` (dev server) | gunicorn + systemd + nginx |

All code must work on **both** environments. Use `sys.platform` or `platform.machine()` where behavior diverges (e.g., sandbox command whitelists).

## Tech Stack

- **Language**: Python 3.10+ (3.13 on dev, system Python on Orin Nano)
- **Web Framework**: Flask
- **AI Backend**: Ollama API (local models, no cloud dependency)
- **Database**: SQLite with FTS5 (full-text search)
- **Config**: python-dotenv
- **Testing**: pytest (all tests mock Ollama — no live server needed)

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pytest tests/ -v
```

## Key Directories

```
ollama_client/          # Ollama API wrapper + prompt templates
  client.py             # OllamaClient class (list_models, connect, chat, embed)
  prompts.py            # MEMORY_EXTRACTION_PROMPT, SCENE_CONSOLIDATION_PROMPT, AGENT_SYSTEM_PROMPT
memory/                 # Memory subsystem (db, manager, retrieval)
sandbox/                # Sandboxed command execution + filesystem ops
agents/                 # WorkerAgent reasoning loop + tool definitions
config/settings.py      # Env vars, temperatures, DB path
models.py               # Shared dataclasses (MemoryCell, ModelInfo, etc.)
exceptions.py           # Exception hierarchy (OllamaConnectionError, etc.)
context/                # Project planning documents and vision
tests/                  # Test suite (mirrors module structure)
deploy/                 # (future) systemd unit, nginx config, Orin Nano setup script
```

## Architecture Goals

From `context/project_vision.txt`:

- **Ollama API integration** — primary AI interaction layer
- **Self-organizing agent memory** — long-term reasoning capability (ref: marktechpost article on agent memory systems)
- **Filesystem & bash agents** — agents that can interact with files and execute commands (ref: Vercel blog on agents with filesystems)
- **Extreme modularization** — strict separation of concerns across distinct modules
- **Comprehensive logging, error handling, and monitoring** throughout all layers

## Orin Nano Constraints

Keep these in mind for every phase:

- **RAM is shared**: Ollama models + Python app + SQLite all compete for 4–8 GB. Keep the app's memory footprint minimal.
- **Small models only**: 4GB → phi3:mini, tinyllama. 8GB → llama3.2:3b, qwen2.5:7b (Q4_K_M quantization).
- **Inference is slow**: Don't block the user on secondary LLM calls (memory extraction, scene consolidation). Defer or run after response.
- **Thermal throttling**: Sustained inference at 25W (Super Mode) may throttle. Log performance metrics.
- **DB size matters**: Cap SQLite growth to avoid eating into shared RAM. Default MAX_DB_SIZE_MB = 256.
