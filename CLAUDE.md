# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An AI agent frontend built with Python/Flask that interfaces with the Ollama API. The project implements a self-organizing agent memory system for long-term AI reasoning and agents with filesystem/bash capabilities.

**Status**: Early initialization phase — project vision and requirements documented, no source code implemented yet.

## Planned Tech Stack

- **Language**: Python
- **Web Framework**: Flask
- **AI Backend**: Ollama API
- **Config**: python-dotenv

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

## Architecture Goals

From `context/project_vision.txt`:

- **Ollama API integration** — primary AI interaction layer
- **Self-organizing agent memory** — long-term reasoning capability (ref: marktechpost article on agent memory systems)
- **Filesystem & bash agents** — agents that can interact with files and execute commands (ref: Vercel blog on agents with filesystems)
- **Extreme modularization** — strict separation of concerns across distinct modules
- **Comprehensive logging, error handling, and monitoring** throughout all layers

## Key Directories

- `context/` — project planning documents and vision
- `requirements.txt` — dependency list (currently placeholder comments, needs real package specs)
