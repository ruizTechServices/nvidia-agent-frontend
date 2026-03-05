"""Shared type contracts for the nvidia-agent-frontend project.

All modules import their data structures from here to ensure
consistent interfaces across the codebase.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class CellType(str, Enum):
    """The six memory cell categories."""
    FACT = "fact"
    PLAN = "plan"
    PREFERENCE = "preference"
    DECISION = "decision"
    TASK = "task"
    RISK = "risk"


@dataclass
class MemoryCell:
    """A single unit of agent long-term memory."""
    scene: str
    cell_type: CellType
    salience: float
    content: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: Optional[int] = None

    def __post_init__(self):
        if not 0.0 <= self.salience <= 1.0:
            raise ValueError(f"salience must be 0.0–1.0, got {self.salience}")
        if isinstance(self.cell_type, str):
            self.cell_type = CellType(self.cell_type)


@dataclass
class SceneSummary:
    """Compressed summary of all memory cells within a scene."""
    scene: str
    summary: str
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionResult:
    """Result from a sandboxed command execution."""
    stdout: str
    stderr: str
    returncode: int


@dataclass
class ChatMessage:
    """A single message in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    model_used: Optional[str] = None

    def __post_init__(self):
        if self.role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {self.role!r}")


@dataclass
class ModelInfo:
    """Metadata about an available Ollama model."""
    name: str
    size: str
    supports_tools: Optional[bool] = None
