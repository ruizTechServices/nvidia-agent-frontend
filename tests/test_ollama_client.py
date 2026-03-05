"""Tests for ollama_client — all Ollama calls are mocked."""

import sys
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import OllamaConnectionError
from models import ModelInfo
from ollama_client.client import OllamaClient
from ollama_client.prompts import (
    AGENT_SYSTEM_PROMPT,
    MEMORY_EXTRACTION_PROMPT,
    SCENE_CONSOLIDATION_PROMPT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ollama_client():
    """Return an OllamaClient with its internal _client mocked."""
    with patch("ollama_client.client.ollama.Client") as MockCls:
        mock_inner = MagicMock()
        MockCls.return_value = mock_inner
        client = OllamaClient(host="http://test:11434")
        yield client, mock_inner


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

def test_list_models(mock_ollama_client):
    client, inner = mock_ollama_client

    model_obj = SimpleNamespace(model="llama3:latest", size=4_000_000_000)
    inner.list.return_value = SimpleNamespace(models=[model_obj])
    inner.show.return_value = SimpleNamespace(capabilities=None)

    result = client.list_models()

    assert len(result) == 1
    assert isinstance(result[0], ModelInfo)
    assert result[0].name == "llama3:latest"
    assert result[0].size == "4.0GB"
    assert result[0].supports_tools is False


def test_list_models_tool_support(mock_ollama_client):
    client, inner = mock_ollama_client

    model_obj = SimpleNamespace(model="qwen2.5:7b", size=7_000_000_000)
    inner.list.return_value = SimpleNamespace(models=[model_obj])
    inner.show.return_value = SimpleNamespace(capabilities=["tools", "completion"])

    result = client.list_models()

    assert result[0].supports_tools is True


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

def test_connect_success(mock_ollama_client):
    client, inner = mock_ollama_client
    inner.show.return_value = SimpleNamespace()

    client.connect("llama3:latest")  # should not raise
    inner.show.assert_called_once_with("llama3:latest")


def test_connect_failure(mock_ollama_client):
    client, inner = mock_ollama_client
    import httpx
    inner.show.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaConnectionError, match="Cannot reach Ollama"):
        client.connect("llama3:latest")


def test_connect_model_not_found(mock_ollama_client):
    client, inner = mock_ollama_client
    import ollama as ollama_lib
    inner.show.side_effect = ollama_lib.ResponseError("model not found")

    with pytest.raises(OllamaConnectionError, match="Cannot connect to model"):
        client.connect("nonexistent:latest")


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------

def test_chat(mock_ollama_client):
    client, inner = mock_ollama_client

    inner.chat.return_value = SimpleNamespace(
        message=SimpleNamespace(content="Hello back!")
    )

    result = client.chat("llama3:latest", "Hello")

    assert result == "Hello back!"
    call_kwargs = inner.chat.call_args
    messages = call_kwargs.kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_chat_with_system_prompt(mock_ollama_client):
    client, inner = mock_ollama_client

    inner.chat.return_value = SimpleNamespace(
        message=SimpleNamespace(content="OK")
    )

    client.chat("llama3:latest", "Hi", system="Be helpful")

    call_kwargs = inner.chat.call_args
    messages = call_kwargs.kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Be helpful"
    assert messages[1]["role"] == "user"


def test_chat_connection_error(mock_ollama_client):
    client, inner = mock_ollama_client
    import httpx
    inner.chat.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaConnectionError):
        client.chat("llama3:latest", "Hello")


# ---------------------------------------------------------------------------
# chat_with_tools
# ---------------------------------------------------------------------------

def test_chat_with_tools(mock_ollama_client):
    client, inner = mock_ollama_client

    tool_call = SimpleNamespace(
        function=SimpleNamespace(name="bash", arguments={"command": "ls"})
    )
    inner.chat.return_value = SimpleNamespace(
        message=SimpleNamespace(content="", tool_calls=[tool_call])
    )

    tools = [{"type": "function", "function": {"name": "bash"}}]
    messages = [{"role": "user", "content": "List files"}]
    response = client.chat_with_tools("llama3:latest", messages, tools)

    assert len(response.message.tool_calls) == 1
    assert response.message.tool_calls[0].function.name == "bash"


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------

def test_embed(mock_ollama_client):
    client, inner = mock_ollama_client

    inner.embed.return_value = SimpleNamespace(
        embeddings=[[0.1, 0.2, 0.3, 0.4]]
    )

    result = client.embed("llama3:latest", "test text")

    assert isinstance(result, list)
    assert len(result) == 4
    assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def test_prompts_not_empty():
    assert isinstance(MEMORY_EXTRACTION_PROMPT, str) and len(MEMORY_EXTRACTION_PROMPT) > 0
    assert isinstance(SCENE_CONSOLIDATION_PROMPT, str) and len(SCENE_CONSOLIDATION_PROMPT) > 0
    assert isinstance(AGENT_SYSTEM_PROMPT, str) and len(AGENT_SYSTEM_PROMPT) > 0
