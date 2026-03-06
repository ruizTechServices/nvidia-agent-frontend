"""Tests for memory.manager — memory extraction and consolidation."""

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import MemoryDBError, MemoryExtractionError, OllamaConnectionError
from memory.db import MemoryDB
from memory.manager import MemoryManager
from models import CellType, MemoryCell


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_db():
    """In-memory MemoryDB for fast tests."""
    return MemoryDB(":memory:")


@pytest.fixture
def mock_client():
    """MagicMock standing in for OllamaClient."""
    return MagicMock()


@pytest.fixture
def manager(mock_client, memory_db):
    """MemoryManager wired to mock_client + memory_db."""
    return MemoryManager(client=mock_client, db=memory_db, model="test-model")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CELLS_JSON = json.dumps([
    {
        "scene": "project_setup",
        "cell_type": "fact",
        "salience": 0.9,
        "content": "User is building a Flask app",
    },
    {
        "scene": "user_preferences",
        "cell_type": "preference",
        "salience": 0.7,
        "content": "User prefers dark mode",
    },
])


# ===========================================================================
# Extraction — happy path
# ===========================================================================

class TestExtractCellsHappyPath:

    def test_extract_cells_valid_json(self, manager, mock_client):
        """Clean JSON array → correct MemoryCell list."""
        mock_client.chat.return_value = VALID_CELLS_JSON

        cells = manager.extract_cells("hello", "hi there")

        assert len(cells) == 2
        assert cells[0].scene == "project_setup"
        assert cells[0].cell_type == CellType.FACT
        assert cells[0].salience == 0.9
        assert cells[0].content == "User is building a Flask app"
        assert cells[1].cell_type == CellType.PREFERENCE

    def test_extract_cells_with_fences(self, manager, mock_client):
        """```json wrapped response → still parses."""
        mock_client.chat.return_value = f"```json\n{VALID_CELLS_JSON}\n```"

        cells = manager.extract_cells("hello", "hi there")

        assert len(cells) == 2
        assert cells[0].scene == "project_setup"

    def test_extract_cells_with_preamble(self, manager, mock_client):
        """Text before/after JSON → still parses."""
        mock_client.chat.return_value = (
            "Here are the extracted memories:\n"
            f"{VALID_CELLS_JSON}\n"
            "I hope that helps!"
        )

        cells = manager.extract_cells("hello", "hi there")

        assert len(cells) == 2

    def test_extract_cells_empty_array(self, manager, mock_client):
        """[] → empty list (nothing to remember)."""
        mock_client.chat.return_value = "[]"

        cells = manager.extract_cells("what time is it", "I don't know")

        assert cells == []


# ===========================================================================
# Extraction — error handling
# ===========================================================================

class TestExtractCellsErrorHandling:

    def test_extract_cells_invalid_json(self, manager, mock_client):
        """Garbled text → empty list, no crash."""
        mock_client.chat.return_value = "this is not json at all {{{}"

        cells = manager.extract_cells("hello", "hi")

        assert cells == []

    def test_extract_cells_trailing_comma(self, manager, mock_client):
        """[{...},] → repaired and parsed."""
        json_with_comma = '[{"scene": "test", "cell_type": "fact", "salience": 0.5, "content": "something"},]'
        mock_client.chat.return_value = json_with_comma

        cells = manager.extract_cells("hello", "hi")

        assert len(cells) == 1
        assert cells[0].scene == "test"

    def test_extract_cells_invalid_cell_type(self, manager, mock_client):
        """Unknown cell_type → that cell skipped."""
        mock_client.chat.return_value = json.dumps([
            {"scene": "s1", "cell_type": "fact", "salience": 0.8, "content": "valid"},
            {"scene": "s2", "cell_type": "unknown_type", "salience": 0.5, "content": "invalid"},
        ])

        cells = manager.extract_cells("hello", "hi")

        assert len(cells) == 1
        assert cells[0].scene == "s1"

    def test_extract_cells_invalid_salience(self, manager, mock_client):
        """Salience > 1.0 → that cell skipped."""
        mock_client.chat.return_value = json.dumps([
            {"scene": "s1", "cell_type": "fact", "salience": 0.8, "content": "valid"},
            {"scene": "s2", "cell_type": "task", "salience": 1.5, "content": "too salient"},
        ])

        cells = manager.extract_cells("hello", "hi")

        assert len(cells) == 1
        assert cells[0].scene == "s1"

    def test_extract_cells_missing_field(self, manager, mock_client):
        """Missing required field → that cell skipped."""
        mock_client.chat.return_value = json.dumps([
            {"scene": "s1", "cell_type": "fact", "salience": 0.8, "content": "valid"},
            {"scene": "s2", "cell_type": "plan"},  # missing salience and content
        ])

        cells = manager.extract_cells("hello", "hi")

        assert len(cells) == 1
        assert cells[0].scene == "s1"

    def test_extract_cells_ollama_error(self, manager, mock_client):
        """OllamaConnectionError → empty list, no crash."""
        mock_client.chat.side_effect = OllamaConnectionError("unreachable")

        cells = manager.extract_cells("hello", "hi")

        assert cells == []


# ===========================================================================
# Store
# ===========================================================================

class TestStoreCells:

    def test_store_cells(self, manager, memory_db):
        """Cells inserted, returns list of IDs."""
        cells = [
            MemoryCell(scene="s1", cell_type=CellType.FACT, salience=0.8, content="fact 1"),
            MemoryCell(scene="s2", cell_type=CellType.PLAN, salience=0.6, content="plan 1"),
        ]

        ids = manager.store_cells(cells)

        assert len(ids) == 2
        assert all(isinstance(i, int) for i in ids)
        # Verify they're actually in the DB
        assert len(memory_db.get_cells_by_scene("s1")) == 1
        assert len(memory_db.get_cells_by_scene("s2")) == 1

    def test_store_cells_empty(self, manager):
        """Empty list → empty list of IDs."""
        ids = manager.store_cells([])

        assert ids == []


# ===========================================================================
# Consolidation
# ===========================================================================

class TestConsolidateScene:

    def test_consolidate_scene(self, manager, mock_client, memory_db):
        """LLM called with correct prompt, summary upserted."""
        # Pre-populate DB with cells
        memory_db.insert_cell(
            MemoryCell(scene="project", cell_type=CellType.FACT,
                       salience=0.9, content="Using Flask")
        )
        memory_db.insert_cell(
            MemoryCell(scene="project", cell_type=CellType.DECISION,
                       salience=0.8, content="Chose SQLite")
        )
        mock_client.chat.return_value = "Project uses Flask with SQLite storage."

        manager.consolidate_scene("project")

        # Verify LLM was called
        mock_client.chat.assert_called_once()
        call_args = mock_client.chat.call_args
        assert "project" in call_args[0][1]  # prompt contains scene name

        # Verify summary was upserted
        summary = memory_db.get_scene_summary("project")
        assert summary is not None
        assert summary.summary == "Project uses Flask with SQLite storage."

    def test_consolidate_scene_ollama_error(self, manager, mock_client, memory_db):
        """LLM failure → no crash, summary not updated."""
        memory_db.insert_cell(
            MemoryCell(scene="s1", cell_type=CellType.FACT,
                       salience=0.9, content="test")
        )
        mock_client.chat.side_effect = OllamaConnectionError("down")

        # Should not raise
        manager.consolidate_scene("s1")

        # Summary should not exist
        assert memory_db.get_scene_summary("s1") is None


# ===========================================================================
# Full pipeline
# ===========================================================================

class TestProcessInteraction:

    def test_process_interaction(self, manager, mock_client, memory_db):
        """extract → store → consolidate all called in sequence."""
        # First call: extraction
        mock_client.chat.side_effect = [
            VALID_CELLS_JSON,                          # extract_cells
            "Summary for project_setup scene.",        # consolidate project_setup
            "Summary for user_preferences scene.",     # consolidate user_preferences
        ]

        cells = manager.process_interaction("hello", "hi there")

        assert len(cells) == 2
        # Verify cells stored in DB
        assert len(memory_db.get_cells_by_scene("project_setup")) == 1
        assert len(memory_db.get_cells_by_scene("user_preferences")) == 1
        # Verify consolidation called (3 total LLM calls)
        assert mock_client.chat.call_count == 3

    def test_process_interaction_extraction_fails(self, manager, mock_client):
        """Returns empty list, no crash."""
        mock_client.chat.side_effect = OllamaConnectionError("unreachable")

        cells = manager.process_interaction("hello", "hi")

        assert cells == []
