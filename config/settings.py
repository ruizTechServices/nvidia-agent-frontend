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

# LLM temperature constants
EXTRACTION_TEMPERATURE: float = 0.1
CONSOLIDATION_TEMPERATURE: float = 0.05
