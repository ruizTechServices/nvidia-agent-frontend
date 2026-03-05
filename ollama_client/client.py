"""Ollama API client wrapper.

Wraps the ollama pip library with logging and project-specific
error translation.
"""

import logging
import time
from typing import Optional

import httpx
import ollama

from config.settings import OLLAMA_HOST
from exceptions import OllamaConnectionError, OllamaTimeoutError
from models import ModelInfo

logger = logging.getLogger(__name__)


class OllamaClient:
    """High-level wrapper around ollama.Client."""

    def __init__(self, host: Optional[str] = None):
        self._client = ollama.Client(host=host or OLLAMA_HOST)

    def list_models(self) -> list[ModelInfo]:
        """List all locally available Ollama models with tool-support detection."""
        try:
            response = self._client.list()
        except (ConnectionError, httpx.ConnectError) as exc:
            raise OllamaConnectionError(f"Cannot reach Ollama: {exc}") from exc

        models: list[ModelInfo] = []
        for m in response.models:
            supports_tools = False
            try:
                detail = self._client.show(m.model)
                capabilities = getattr(detail, "capabilities", None)
                if capabilities and "tools" in capabilities:
                    supports_tools = True
            except Exception:
                pass

            size_str = self._format_size(getattr(m, "size", 0))
            models.append(ModelInfo(
                name=m.model,
                size=size_str,
                supports_tools=supports_tools,
            ))

        logger.info("Listed %d model(s)", len(models))
        return models

    def connect(self, model_name: str) -> None:
        """Verify that Ollama is running and the given model is available."""
        try:
            self._client.show(model_name)
            logger.info("Connected to model %s", model_name)
        except ollama.ResponseError as exc:
            logger.error("Model not found or Ollama error: %s", exc)
            raise OllamaConnectionError(
                f"Cannot connect to model '{model_name}': {exc}"
            ) from exc
        except (ConnectionError, httpx.ConnectError) as exc:
            logger.error("Ollama unreachable: %s", exc)
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {OLLAMA_HOST}: {exc}"
            ) from exc

    def chat(
        self,
        model: str,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Send a single prompt and return the response content string."""
        logger.debug("chat prompt length=%d model=%s", len(prompt), model)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        start = time.monotonic()
        try:
            response = self._client.chat(
                model=model,
                messages=messages,
                options=options if options else None,
            )
        except (ConnectionError, httpx.ConnectError) as exc:
            raise OllamaConnectionError(f"Cannot reach Ollama: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(f"Ollama request timed out: {exc}") from exc
        except ollama.ResponseError as exc:
            raise OllamaConnectionError(f"Ollama error: {exc}") from exc

        elapsed = time.monotonic() - start
        logger.info("chat response in %.2fs model=%s", elapsed, model)
        return response.message.content

    def chat_with_tools(self, model: str, messages: list[dict], tools: list[dict]):
        """Call Ollama with tool definitions. Returns the full ChatResponse."""
        try:
            response = self._client.chat(
                model=model,
                messages=messages,
                tools=tools,
            )
        except (ConnectionError, httpx.ConnectError) as exc:
            raise OllamaConnectionError(f"Cannot reach Ollama: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(f"Ollama request timed out: {exc}") from exc
        except ollama.ResponseError as exc:
            raise OllamaConnectionError(f"Ollama error: {exc}") from exc

        return response

    def embed(self, model: str, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        logger.debug("embed text length=%d model=%s", len(text), model)
        try:
            response = self._client.embed(model=model, input=text)
        except (ConnectionError, httpx.ConnectError) as exc:
            raise OllamaConnectionError(f"Cannot reach Ollama: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(f"Ollama request timed out: {exc}") from exc
        except ollama.ResponseError as exc:
            raise OllamaConnectionError(f"Ollama error: {exc}") from exc

        return response.embeddings[0]

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format byte count as a human-readable string."""
        if size_bytes >= 1_000_000_000:
            return f"{size_bytes / 1_000_000_000:.1f}GB"
        if size_bytes >= 1_000_000:
            return f"{size_bytes / 1_000_000:.1f}MB"
        return f"{size_bytes}B"
