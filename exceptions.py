"""Exception hierarchy for the nvidia-agent-frontend project.

All custom exceptions inherit from AgentError so callers can
catch the base class for broad error handling.
"""


class AgentError(Exception):
    """Base exception for all agent-related errors."""


class OllamaConnectionError(AgentError):
    """Failed to connect to the Ollama API."""


class OllamaTimeoutError(AgentError):
    """Ollama API request timed out."""


class MemoryExtractionError(AgentError):
    """Failed to extract or process memory cells."""


class SandboxSecurityError(AgentError):
    """A sandboxed operation violated security constraints."""


class SandboxTimeoutError(AgentError):
    """A sandboxed operation exceeded its time limit."""
