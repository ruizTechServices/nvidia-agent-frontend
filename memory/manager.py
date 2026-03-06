"""Memory lifecycle manager.

Coordinates extraction of memory cells from conversations,
salience scoring, scene consolidation, and decay/pruning.
"""

import json
import logging
import re
from typing import Optional

from config.settings import CONSOLIDATION_TEMPERATURE, EXTRACTION_TEMPERATURE
from exceptions import MemoryDBError, MemoryExtractionError
from models import CellType, MemoryCell
from ollama_client.prompts import (
    MEMORY_EXTRACTION_PROMPT,
    SCENE_CONSOLIDATION_PROMPT,
)

logger = logging.getLogger(__name__)


class MemoryManager:
    """Bridge between OllamaClient and MemoryDB.

    Uses LLM calls to extract structured memory cells from conversations
    and consolidate scene summaries.  Every public method is designed to
    fail gracefully — a failed extraction or consolidation never crashes
    the main chat flow.

    Args:
        client: An OllamaClient instance for LLM calls.
        db: A MemoryDB instance for persistence.
        model: The Ollama model name to use for extraction/consolidation.
    """

    def __init__(self, client, db, model: str) -> None:
        self._client = client
        self._db = db
        self._model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_cells(self, user_msg: str, assistant_msg: str) -> list[MemoryCell]:
        """Extract memory cells from a conversation turn.

        Calls the LLM with ``MEMORY_EXTRACTION_PROMPT``, parses the JSON
        response, validates each cell, and returns the valid ones.

        Returns an empty list on any failure (never raises).
        """
        logger.debug("extract_cells: user_msg=%d chars, assistant_msg=%d chars",
                      len(user_msg), len(assistant_msg))
        try:
            prompt = MEMORY_EXTRACTION_PROMPT.format(
                user_message=user_msg,
                assistant_message=assistant_msg,
            )
            raw_response = self._client.chat(
                self._model, prompt, temperature=EXTRACTION_TEMPERATURE,
            )
            raw_dicts = self._parse_json_response(raw_response)
            cells = []
            for raw in raw_dicts:
                cell = self._validate_cell(raw)
                if cell is not None:
                    cells.append(cell)
            logger.info("extract_cells: %d valid cell(s) extracted", len(cells))
            return cells
        except Exception as exc:
            logger.error("extract_cells failed: %s", exc)
            return []

    def store_cells(self, cells: list[MemoryCell]) -> list[int]:
        """Insert cells into the database.

        Skips individual cells that fail insertion and continues with
        the rest.  Returns a list of row IDs for successfully stored cells.
        """
        logger.debug("store_cells: %d cell(s) to store", len(cells))
        ids: list[int] = []
        for cell in cells:
            try:
                row_id = self._db.insert_cell(cell)
                ids.append(row_id)
            except MemoryDBError as exc:
                logger.warning("store_cells: skipping cell (scene=%s): %s",
                               cell.scene, exc)
        logger.info("store_cells: stored %d/%d cell(s)", len(ids), len(cells))
        return ids

    def consolidate_scene(self, scene: str) -> None:
        """Consolidate all cells for *scene* into a summary via LLM.

        Fetches all cells for the scene, calls the LLM with
        ``SCENE_CONSOLIDATION_PROMPT``, and upserts the resulting summary.

        Fails silently on any error (logs but does not raise).
        """
        logger.debug("consolidate_scene: scene=%s", scene)
        try:
            cells = self._db.get_cells_by_scene(scene)
            if not cells:
                logger.info("consolidate_scene: no cells for scene=%s, skipping", scene)
                return

            cells_text = "\n".join(
                f"- [{c.cell_type.value}] (salience {c.salience:.2f}) {c.content}"
                for c in cells
            )
            prompt = SCENE_CONSOLIDATION_PROMPT.format(
                scene=scene, cells=cells_text,
            )
            summary = self._client.chat(
                self._model, prompt, temperature=CONSOLIDATION_TEMPERATURE,
            )
            self._db.upsert_scene_summary(scene, summary.strip())
            logger.info("consolidate_scene: updated summary for scene=%s", scene)
        except Exception as exc:
            logger.error("consolidate_scene failed for scene=%s: %s", scene, exc)

    def process_interaction(self, user_msg: str, assistant_msg: str) -> list[MemoryCell]:
        """Full pipeline: extract → store → consolidate.

        Returns the extracted cells.  On total failure, returns an empty list.
        """
        logger.debug("process_interaction: starting pipeline")
        try:
            cells = self.extract_cells(user_msg, assistant_msg)
            if not cells:
                logger.info("process_interaction: no cells extracted")
                return []

            self.store_cells(cells)

            scenes = {c.scene for c in cells}
            for scene in scenes:
                self.consolidate_scene(scene)

            logger.info("process_interaction: completed — %d cell(s), %d scene(s)",
                        len(cells), len(scenes))
            return cells
        except Exception as exc:
            logger.error("process_interaction failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_json_response(self, text: str) -> list[dict]:
        """Multi-layer JSON parsing with fence stripping and repair.

        Raises ``MemoryExtractionError`` only when JSON is completely
        unparseable (caught by ``extract_cells``).
        """
        cleaned = self._strip_fences(text)

        # Strip preamble/postamble — find first '[' and last ']'
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

        # Primary parse attempt
        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
            return []
        except json.JSONDecodeError:
            pass

        # Repair attempt
        repaired = self._repair_json(cleaned)
        try:
            result = json.loads(repaired)
            if isinstance(result, list):
                logger.info("_parse_json_response: parsed after repair")
                return result
            return []
        except json.JSONDecodeError as exc:
            raise MemoryExtractionError(
                f"Cannot parse LLM response as JSON: {exc}"
            ) from exc

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove ```json ... ``` markdown wrappers."""
        # Match ```json or ``` at start and ``` at end
        pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1)
        return text

    @staticmethod
    def _repair_json(text: str) -> str:
        """Attempt to fix common JSON issues from LLM output."""
        # Remove trailing commas before ] or }
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # Replace single quotes with double quotes
        text = text.replace("'", '"')
        # Strip control characters (except newline, tab)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        return text

    @staticmethod
    def _validate_cell(raw: dict) -> Optional[MemoryCell]:
        """Validate a raw dict and coerce to MemoryCell.

        Returns None if the dict is invalid (missing fields, bad types, etc.).
        """
        try:
            scene = raw.get("scene")
            cell_type = raw.get("cell_type")
            salience = raw.get("salience")
            content = raw.get("content")

            if not all([scene, cell_type, content]):
                logger.warning("_validate_cell: missing required field in %s", raw)
                return None
            if salience is None:
                logger.warning("_validate_cell: missing salience in %s", raw)
                return None

            # Validate cell_type against enum
            try:
                ct = CellType(cell_type)
            except ValueError:
                logger.warning("_validate_cell: invalid cell_type=%r", cell_type)
                return None

            # Validate salience range
            sal = float(salience)
            if not 0.0 <= sal <= 1.0:
                logger.warning("_validate_cell: salience out of range: %s", sal)
                return None

            return MemoryCell(
                scene=str(scene),
                cell_type=ct,
                salience=sal,
                content=str(content),
            )
        except Exception as exc:
            logger.warning("_validate_cell: unexpected error: %s", exc)
            return None
