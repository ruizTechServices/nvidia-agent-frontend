"""Worker agent reasoning loop.

Orchestrates the Ollama client, memory retrieval, sandboxed execution,
and memory persistence into a tool-calling conversation loop.
"""

import logging

from config.settings import MAX_TOOL_ITERATIONS
from exceptions import OllamaConnectionError, OllamaTimeoutError
from memory.db import MemoryDB
from memory.manager import MemoryManager
from memory.retrieval import MemoryRetriever
from ollama_client.client import OllamaClient
from ollama_client.prompts import AGENT_SYSTEM_PROMPT
from sandbox.executor import SandboxExecutor

from agents.tools import ALL_TOOLS, ToolDispatcher

logger = logging.getLogger(__name__)


class WorkerAgent:
    """Tool-calling agent that ties together LLM, memory, and sandbox.

    Args:
        client: OllamaClient for LLM interaction.
        db: MemoryDB for conversation and memory persistence.
        executor: SandboxExecutor for command execution.
        model: Ollama model name to use.
    """

    def __init__(
        self,
        client: OllamaClient,
        db: MemoryDB,
        executor: SandboxExecutor,
        model: str,
    ) -> None:
        self._client = client
        self._db = db
        self._model = model
        self._retriever = MemoryRetriever(db)
        self._manager = MemoryManager(client, db, model)
        self._dispatcher = ToolDispatcher(executor, self._retriever)

    def run(self, user_message: str) -> str:
        """Execute the agent reasoning loop for a user message.

        Returns the final text response. Never raises — all errors
        are caught and returned as user-friendly strings.
        """
        logger.info("WorkerAgent.run: model=%s msg_len=%d", self._model, len(user_message))

        try:
            return self._run_inner(user_message)
        except OllamaConnectionError as exc:
            logger.error("Ollama unreachable: %s", exc)
            return "I'm unable to reach the AI model right now. Please check that Ollama is running."
        except OllamaTimeoutError as exc:
            logger.error("Ollama timed out: %s", exc)
            return "The AI model request timed out. The model may be too large for available memory."

    def _run_inner(self, user_message: str) -> str:
        """Core loop, may raise OllamaConnectionError or OllamaTimeoutError."""
        # 1. Retrieve memory context
        memory_context = ""
        try:
            memory_context = self._retriever.build_context_block(user_message)
        except Exception as exc:
            logger.warning("Memory retrieval failed, proceeding without context: %s", exc)

        # 2. Build initial messages
        system_content = AGENT_SYSTEM_PROMPT
        if memory_context:
            system_content += f"\n\n## Memory Context\n{memory_context}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_message},
        ]

        # 3. Tool loop
        response_text = ""
        for iteration in range(MAX_TOOL_ITERATIONS):
            logger.debug("Tool loop iteration %d/%d", iteration + 1, MAX_TOOL_ITERATIONS)

            response = self._client.chat_with_tools(self._model, messages, ALL_TOOLS)

            tool_calls = getattr(response.message, "tool_calls", None)
            if not tool_calls:
                response_text = response.message.content or ""
                break

            # Append assistant message with tool calls
            messages.append({"role": "assistant", "content": response.message.content or "", "tool_calls": tool_calls})

            # Execute each tool call
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments
                logger.info("Tool call: %s(%s)", tool_name, tool_args)

                result = self._dispatcher.dispatch(tool_name, tool_args)
                messages.append({"role": "tool", "content": result})

            response_text = response.message.content or ""
        else:
            logger.warning("Tool iteration cap (%d) reached", MAX_TOOL_ITERATIONS)

        # 4. Store conversation
        if response_text:
            try:
                self._db.insert_conversation(user_message, response_text, self._model)
            except Exception as exc:
                logger.error("Failed to store conversation: %s", exc)

        # 5. Defer memory processing
        if response_text:
            try:
                self._manager.process_interaction(user_message, response_text)
            except Exception as exc:
                logger.error("Memory processing failed: %s", exc)

        return response_text
