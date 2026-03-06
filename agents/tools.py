"""Tool definitions and dispatch for the worker agent.

Defines Ollama-compatible tool schemas and a dispatcher that
routes tool calls to the sandbox executor or memory retriever.
"""

import logging
import sys

from memory.retrieval import MemoryRetriever
from sandbox.executor import SandboxExecutor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schema constants (Ollama tool-calling format)
# ---------------------------------------------------------------------------

BASH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a shell command in a sandboxed environment.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
    },
}

MEMORY_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "memory_search",
        "description": "Search long-term memory for relevant past context.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query for memory retrieval.",
                },
            },
            "required": ["query"],
        },
    },
}

SYSTEM_STATUS_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "system_status",
        "description": "Check system resource status (GPU, disk, memory).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

ALL_TOOLS: list[dict] = [BASH_TOOL, MEMORY_SEARCH_TOOL, SYSTEM_STATUS_TOOL]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

class ToolDispatcher:
    """Routes tool calls to the appropriate executor.

    All dispatch calls return a string result. Errors are caught and
    returned as error strings so the LLM can adapt — dispatch never raises.
    """

    def __init__(self, executor: SandboxExecutor, retriever: MemoryRetriever) -> None:
        self._executor = executor
        self._retriever = retriever

    def dispatch(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool by name and return the result string."""
        logger.debug("dispatch: tool=%s args=%s", tool_name, arguments)
        try:
            if tool_name == "bash":
                return self._dispatch_bash(arguments)
            if tool_name == "memory_search":
                return self._dispatch_memory_search(arguments)
            if tool_name == "system_status":
                return self._dispatch_system_status()
            return f"Error: Unknown tool '{tool_name}'"
        except Exception as exc:
            logger.error("Tool dispatch failed: tool=%s error=%s", tool_name, exc)
            return f"Error executing {tool_name}: {exc}"

    def _dispatch_bash(self, arguments: dict) -> str:
        command = arguments.get("command", "")
        if not command:
            return "Error: No command provided"
        result = self._executor.execute(command)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"

    def _dispatch_memory_search(self, arguments: dict) -> str:
        query = arguments.get("query", "")
        if not query:
            return "Error: No query provided"
        cells = self._retriever.retrieve(query)
        if not cells:
            return "No matching memories found."
        lines = []
        for cell in cells:
            lines.append(
                f"- [{cell.cell_type.value}] ({cell.salience:.2f}) {cell.content}"
            )
        return "\n".join(lines)

    def _dispatch_system_status(self) -> str:
        parts = []
        if sys.platform == "linux":
            gpu_result = self._executor.execute("nvidia-smi")
            parts.append(gpu_result.stdout or gpu_result.stderr or "nvidia-smi unavailable")
        else:
            parts.append("System status: running (non-Linux platform)")
        try:
            df_result = self._executor.execute("df -h" if sys.platform != "win32" else "echo disk info not available")
            parts.append(df_result.stdout or df_result.stderr)
        except Exception as exc:
            parts.append(f"Disk info unavailable: {exc}")
        return "\n".join(parts)
