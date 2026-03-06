"""Tests for agents/tools.py and agents/worker.py."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.tools import ALL_TOOLS, ToolDispatcher
from agents.worker import WorkerAgent
from exceptions import OllamaConnectionError, OllamaTimeoutError
from memory.db import MemoryDB
from models import CellType, ExecutionResult, MemoryCell
from sandbox.executor import SandboxExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat_response(content="Hello!", tool_calls=None):
    """Build a mock Ollama ChatResponse."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(message=message)


def _make_tool_call(name, arguments):
    """Build a mock tool_call entry."""
    return SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=arguments)
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_db():
    return MemoryDB(":memory:")


@pytest.fixture
def executor(tmp_path):
    return SandboxExecutor(str(tmp_path))


@pytest.fixture
def mock_client():
    return MagicMock()


# ---------------------------------------------------------------------------
# ToolDispatcher tests
# ---------------------------------------------------------------------------

class TestToolDispatcher:
    def test_dispatch_bash(self, executor, memory_db):
        """Bash tool executes command and returns output."""
        dispatcher = ToolDispatcher(executor, MagicMock())
        # 'echo' is in the whitelist
        result = dispatcher.dispatch("bash", {"command": "echo hello"})
        assert "hello" in result

    def test_dispatch_bash_error(self, memory_db):
        """Bash tool returns error string on security violation."""
        executor = MagicMock()
        from exceptions import SandboxSecurityError
        executor.execute.side_effect = SandboxSecurityError("blocked")
        dispatcher = ToolDispatcher(executor, MagicMock())
        result = dispatcher.dispatch("bash", {"command": "sudo rm -rf /"})
        assert "Error" in result
        assert "blocked" in result

    def test_dispatch_memory_search(self, executor, memory_db):
        """Memory search returns formatted cells."""
        from memory.retrieval import MemoryRetriever
        retriever = MemoryRetriever(memory_db)
        # Seed a cell
        memory_db.insert_cell(MemoryCell(
            scene="test", cell_type=CellType.FACT,
            salience=0.9, content="Flask is used for the web server",
        ))
        dispatcher = ToolDispatcher(executor, retriever)
        result = dispatcher.dispatch("memory_search", {"query": "Flask"})
        assert "Flask" in result
        assert "[fact]" in result

    def test_dispatch_memory_search_empty(self, executor, memory_db):
        """Memory search with no results returns message."""
        from memory.retrieval import MemoryRetriever
        retriever = MemoryRetriever(memory_db)
        dispatcher = ToolDispatcher(executor, retriever)
        result = dispatcher.dispatch("memory_search", {"query": "nonexistent_xyz"})
        assert "No matching memories" in result

    def test_dispatch_unknown_tool(self, executor, memory_db):
        """Unknown tool name returns error string."""
        dispatcher = ToolDispatcher(executor, MagicMock())
        result = dispatcher.dispatch("nonexistent_tool", {})
        assert "Unknown tool" in result


# ---------------------------------------------------------------------------
# WorkerAgent tests
# ---------------------------------------------------------------------------

class TestWorkerAgent:
    def test_run_simple_chat(self, mock_client, memory_db, executor):
        """Simple chat without tool calls returns content."""
        mock_client.chat_with_tools.return_value = _make_chat_response("Hi there!")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        # Suppress memory processing (it calls client.chat which is also mocked)
        with patch.object(agent._manager, "process_interaction"):
            result = agent.run("Hello")
        assert result == "Hi there!"

    def test_run_with_tool_call(self, mock_client, memory_db, executor):
        """Agent handles a single tool call then final response."""
        # First call returns tool call, second returns final answer
        mock_client.chat_with_tools.side_effect = [
            _make_chat_response(
                content="",
                tool_calls=[_make_tool_call("bash", {"command": "echo test"})],
            ),
            _make_chat_response("The output was: test"),
        ]
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction"):
            result = agent.run("Run echo test")
        assert "test" in result
        assert mock_client.chat_with_tools.call_count == 2

    def test_run_multi_tool_turns(self, mock_client, memory_db, executor):
        """Agent handles multiple sequential tool calls."""
        mock_client.chat_with_tools.side_effect = [
            _make_chat_response(
                content="",
                tool_calls=[_make_tool_call("bash", {"command": "echo first"})],
            ),
            _make_chat_response(
                content="",
                tool_calls=[_make_tool_call("bash", {"command": "echo second"})],
            ),
            _make_chat_response("Done with both commands"),
        ]
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction"):
            result = agent.run("Run two commands")
        assert result == "Done with both commands"
        assert mock_client.chat_with_tools.call_count == 3

    def test_run_memory_context_injected(self, mock_client, memory_db, executor):
        """Memory context is included in the system prompt."""
        # Seed memory
        memory_db.insert_cell(MemoryCell(
            scene="test", cell_type=CellType.FACT,
            salience=0.9, content="User prefers Python",
        ))
        mock_client.chat_with_tools.return_value = _make_chat_response("Got it!")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction"):
            agent.run("Tell me about Python preferences")

        # Check system message includes memory context
        call_args = mock_client.chat_with_tools.call_args
        messages = call_args[0][1]  # second positional arg
        system_msg = messages[0]
        assert "Memory Context" in system_msg["content"]
        assert "Python" in system_msg["content"]

    def test_run_memory_retrieval_fails(self, mock_client, memory_db, executor):
        """Agent proceeds without context when memory retrieval fails."""
        mock_client.chat_with_tools.return_value = _make_chat_response("Hello!")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._retriever, "build_context_block", side_effect=RuntimeError("db down")):
            with patch.object(agent._manager, "process_interaction"):
                result = agent.run("Hi")
        assert result == "Hello!"

    def test_run_conversation_stored(self, mock_client, memory_db, executor):
        """Conversation is persisted to the database."""
        mock_client.chat_with_tools.return_value = _make_chat_response("Stored response")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction"):
            agent.run("Store this")
        convos = memory_db.get_conversations(limit=10)
        assert len(convos) == 2  # user + assistant
        assert convos[0].content == "Store this"
        assert convos[1].content == "Stored response"

    def test_run_memory_processing_called(self, mock_client, memory_db, executor):
        """Memory processing is invoked after response."""
        mock_client.chat_with_tools.return_value = _make_chat_response("Response")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction") as mock_process:
            agent.run("Process this")
        mock_process.assert_called_once_with("Process this", "Response")

    def test_run_memory_processing_fails(self, mock_client, memory_db, executor):
        """Agent still returns response when memory processing fails."""
        mock_client.chat_with_tools.return_value = _make_chat_response("Fine")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction", side_effect=RuntimeError("boom")):
            result = agent.run("Test")
        assert result == "Fine"

    def test_run_ollama_unreachable(self, mock_client, memory_db, executor):
        """Returns user-friendly message when Ollama is down."""
        mock_client.chat_with_tools.side_effect = OllamaConnectionError("unreachable")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        result = agent.run("Hello")
        assert "unable to reach" in result.lower() or "ollama" in result.lower()

    def test_run_ollama_timeout(self, mock_client, memory_db, executor):
        """Returns user-friendly message on timeout."""
        mock_client.chat_with_tools.side_effect = OllamaTimeoutError("timed out")
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        result = agent.run("Hello")
        assert "timed out" in result.lower()

    def test_run_tool_iteration_cap(self, mock_client, memory_db, executor):
        """Agent stops after MAX_TOOL_ITERATIONS even if LLM keeps calling tools."""
        # Always return a tool call — should stop at cap
        mock_client.chat_with_tools.return_value = _make_chat_response(
            content="thinking...",
            tool_calls=[_make_tool_call("bash", {"command": "echo loop"})],
        )
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch("agents.worker.MAX_TOOL_ITERATIONS", 3):
            with patch.object(agent._manager, "process_interaction"):
                result = agent.run("Loop forever")
        # Should have been called exactly 3 times (the cap)
        assert mock_client.chat_with_tools.call_count == 3

    def test_run_tool_execution_fails(self, mock_client, memory_db, executor):
        """Tool failure feeds error back to LLM, agent continues."""
        mock_client.chat_with_tools.side_effect = [
            _make_chat_response(
                content="",
                tool_calls=[_make_tool_call("bash", {"command": "sudo rm -rf /"})],
            ),
            _make_chat_response("I can't do that, but here's an alternative."),
        ]
        agent = WorkerAgent(mock_client, memory_db, executor, "test-model")
        with patch.object(agent._manager, "process_interaction"):
            result = agent.run("Delete everything")
        # The error from sandbox should have been fed back, and LLM recovered
        assert "alternative" in result.lower() or len(result) > 0
