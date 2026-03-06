"""Tests for memory.retrieval — two-tier retrieval and context assembly."""

import os
import sys
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import MemoryDBError
from memory.db import MemoryDB
from memory.retrieval import MemoryRetriever
from models import CellType, MemoryCell


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_db():
    """In-memory MemoryDB for fast tests."""
    return MemoryDB(":memory:")


@pytest.fixture
def retriever(memory_db):
    """MemoryRetriever wired to in-memory DB."""
    return MemoryRetriever(memory_db)


def _make_cell(scene="test_scene", cell_type=CellType.FACT,
               salience=0.8, content="test content"):
    return MemoryCell(scene=scene, cell_type=cell_type,
                      salience=salience, content=content)


def _seed_cells(db, cells):
    """Insert multiple cells into the DB and return their IDs."""
    return [db.insert_cell(c) for c in cells]


# ---------------------------------------------------------------------------
# retrieve() tests
# ---------------------------------------------------------------------------

class TestRetrieve:
    def test_retrieve_fts_hit(self, memory_db, retriever):
        """FTS finds matching cells by content."""
        _seed_cells(memory_db, [
            _make_cell(content="Flask web application"),
            _make_cell(content="User prefers dark mode"),
        ])
        results = retriever.retrieve("Flask")
        assert len(results) >= 1
        assert any("Flask" in c.content for c in results)

    def test_retrieve_salience_fallback(self, memory_db, retriever):
        """When FTS returns nothing, falls back to top salient cells."""
        _seed_cells(memory_db, [
            _make_cell(content="important fact", salience=0.95),
            _make_cell(content="minor detail", salience=0.3),
        ])
        # Query that won't match any content via FTS
        results = retriever.retrieve("xyznonexistent")
        assert len(results) >= 1
        # Should return salience-ordered: highest first
        assert results[0].salience >= results[-1].salience

    def test_retrieve_empty_db(self, retriever):
        """Empty DB returns empty list."""
        results = retriever.retrieve("anything")
        assert results == []

    def test_retrieve_respects_limit(self, memory_db, retriever):
        """Limit parameter caps the number of returned cells."""
        _seed_cells(memory_db, [
            _make_cell(content=f"fact number {i}", salience=round(0.5 + i * 0.01, 2))
            for i in range(20)
        ])
        results = retriever.retrieve("fact", limit=5)
        assert len(results) <= 5

    def test_retrieve_db_error(self, memory_db, retriever):
        """DB failure returns empty list, no crash."""
        with patch.object(memory_db, "search_fts", side_effect=MemoryDBError("boom")):
            results = retriever.retrieve("test")
            assert results == []


# ---------------------------------------------------------------------------
# build_context_block() tests
# ---------------------------------------------------------------------------

class TestBuildContextBlock:
    def test_build_context_block_with_cells(self, memory_db, retriever):
        """Formatted string contains cell content and metadata."""
        _seed_cells(memory_db, [
            _make_cell(content="User is building a Flask app", salience=0.90),
        ])
        block = retriever.build_context_block("Flask")
        assert "## Relevant Memories" in block
        assert "Flask app" in block
        assert "[fact]" in block
        assert "(0.90)" in block

    def test_build_context_block_with_summaries(self, memory_db, retriever):
        """Scene summaries are included in the context block."""
        memory_db.upsert_scene_summary("project_setup", "Project uses Flask with SQLite")
        # Need at least one cell or summary to produce output
        block = retriever.build_context_block("setup")
        assert "## Scene Summaries" in block
        assert "project_setup" in block
        assert "Flask with SQLite" in block

    def test_build_context_block_both(self, memory_db, retriever):
        """Block includes both cells and summaries."""
        _seed_cells(memory_db, [
            _make_cell(content="dark mode preference", salience=0.70),
        ])
        memory_db.upsert_scene_summary("ui", "User prefers dark themes")
        block = retriever.build_context_block("dark")
        assert "## Relevant Memories" in block
        assert "## Scene Summaries" in block

    def test_build_context_block_empty(self, retriever):
        """No memories returns empty string."""
        block = retriever.build_context_block("anything")
        assert block == ""

    def test_build_context_block_truncation(self, memory_db):
        """Output capped at max_context_chars."""
        retriever = MemoryRetriever(memory_db, max_context_chars=50)
        _seed_cells(memory_db, [
            _make_cell(content="A very long memory content that should cause truncation " * 5),
        ])
        block = retriever.build_context_block("long")
        assert len(block) <= 50
        assert block.endswith("...")

    def test_build_context_block_db_error(self, memory_db):
        """DB failure returns empty string, no crash."""
        retriever = MemoryRetriever(memory_db)
        with patch.object(
            memory_db, "search_fts", side_effect=MemoryDBError("db down")
        ), patch.object(
            memory_db, "get_all_scene_summaries",
            side_effect=MemoryDBError("db down"),
        ):
            block = retriever.build_context_block("test")
            assert block == ""

    def test_build_context_block_unexpected_error(self, memory_db):
        """Unexpected exception returns empty string, no crash."""
        retriever = MemoryRetriever(memory_db)
        with patch.object(
            memory_db, "search_fts", side_effect=RuntimeError("surprise")
        ):
            block = retriever.build_context_block("test")
            assert block == ""


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_max_context_chars(self, memory_db):
        """Retriever uses settings.MAX_CONTEXT_CHARS by default."""
        from config import settings
        retriever = MemoryRetriever(memory_db)
        assert retriever.max_context_chars == settings.MAX_CONTEXT_CHARS

    def test_custom_max_context_chars(self, memory_db):
        """Custom max_context_chars overrides default."""
        retriever = MemoryRetriever(memory_db, max_context_chars=500)
        assert retriever.max_context_chars == 500
