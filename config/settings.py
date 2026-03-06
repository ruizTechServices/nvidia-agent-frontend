"""Application settings loaded from environment variables.

Uses python-dotenv to load a .env file if present.
"""

import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")
FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
DB_PATH: str = os.getenv("DB_PATH", "memory.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")

# Orin Nano DB size constraint — cap SQLite growth to avoid eating shared RAM
MAX_DB_SIZE_MB: int = int(os.getenv("MAX_DB_SIZE_MB", "256"))

# Memory retrieval context cap — ~500 tokens, conservative for small models
MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "2000"))

# Sandbox settings
SANDBOX_TIMEOUT: int = int(os.getenv("SANDBOX_TIMEOUT", "30"))
SANDBOX_WORKSPACE_DIR: str = os.getenv("SANDBOX_WORKSPACE_DIR", "workspaces")
SANDBOX_MAX_UPLOAD_MB: int = int(os.getenv("SANDBOX_MAX_UPLOAD_MB", "100"))

# LLM temperature constants
EXTRACTION_TEMPERATURE: float = 0.1
CONSOLIDATION_TEMPERATURE: float = 0.05
