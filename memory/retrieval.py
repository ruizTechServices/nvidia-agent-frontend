"""Memory retrieval and context assembly.

Implements two-tier retrieval (FTS → salience fallback) and
context window assembly for LLM prompts. Caps output to
respect small model context windows on constrained hardware.
"""

import logging

from config import settings
from exceptions import MemoryDBError
from memory.db import MemoryDB
from models import MemoryCell

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Retrieves stored memories and assembles prompt-ready context blocks.

    Args:
        db: The MemoryDB instance to query.
        max_context_chars: Maximum characters for the assembled context block.
            Defaults to ``settings.MAX_CONTEXT_CHARS``.
    """

    def __init__(self, db: MemoryDB, max_context_chars: int | None = None) -> None:
        self.db = db
        self.max_context_chars = (
            max_context_chars if max_context_chars is not None
            else settings.MAX_CONTEXT_CHARS
        )
        logger.debug(
            "MemoryRetriever init: max_context_chars=%d", self.max_context_chars
        )

    def retrieve(self, query: str, limit: int = 10) -> list[MemoryCell]:
        """Two-tier retrieval: FTS first, salience fallback if empty.

        Args:
            query: Search query string.
            limit: Maximum number of cells to return.

        Returns:
            List of matching MemoryCell objects, or ``[]`` on error.
        """
        logger.debug("retrieve: query=%r limit=%d", query, limit)
        try:
            cells = self.db.search_fts(query, limit)
            if cells:
                logger.info("retrieve: %d FTS results for %r", len(cells), query)
                return cells
            # Tier 2: salience fallback
            cells = self.db.get_top_salient(limit)
            logger.info(
                "retrieve: FTS empty, %d salience fallback results", len(cells)
            )
            return cells
        except MemoryDBError as exc:
            logger.error("retrieve failed: %s", exc)
            return []

    def build_context_block(self, query: str, limit: int = 10) -> str:
        """Assemble retrieved memories into a prompt-ready string.

        Combines relevant memory cells and scene summaries into a
        formatted block, truncated to ``max_context_chars``.

        Args:
            query: Search query for memory retrieval.
            limit: Maximum number of cells to retrieve.

        Returns:
            Formatted context string, or ``""`` on error or if empty.
        """
        logger.debug("build_context_block: query=%r limit=%d", query, limit)
        try:
            cells = self.retrieve(query, limit)
            summaries = self.db.get_all_scene_summaries()

            if not cells and not summaries:
                logger.info("build_context_block: no memories found")
                return ""

            parts: list[str] = []

            if cells:
                parts.append("## Relevant Memories")
                for cell in cells:
                    parts.append(
                        f"- [{cell.cell_type.value}] ({cell.salience:.2f}) "
                        f"{cell.content}"
                    )

            if summaries:
                parts.append("")
                parts.append("## Scene Summaries")
                for s in summaries:
                    parts.append(f"- {s.scene}: {s.summary}")

            block = "\n".join(parts)

            if len(block) > self.max_context_chars:
                block = block[: self.max_context_chars - 3] + "..."
                logger.debug(
                    "build_context_block: truncated to %d chars",
                    self.max_context_chars,
                )

            logger.info("build_context_block: %d chars", len(block))
            return block
        except Exception as exc:
            logger.error("build_context_block failed: %s", exc)
            return ""
