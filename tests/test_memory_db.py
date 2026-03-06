"""Tests for memory.db — SQLite memory persistence layer."""

import os
import sys
import tempfile

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import MemoryDBError
from memory.db import MemoryDB
from models import CellType, MemoryCell


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_db():
    """In-memory MemoryDB for fast tests."""
    return MemoryDB(":memory:")


@pytest.fixture
def temp_db(tmp_path):
    """File-backed MemoryDB for size-related tests."""
    db_path = str(tmp_path / "test_memory.db")
    return MemoryDB(db_path)


def _make_cell(scene="test_scene", cell_type=CellType.FACT,
               salience=0.8, content="test content"):
    return MemoryCell(scene=scene, cell_type=cell_type,
                      salience=salience, content=content)


# ---------------------------------------------------------------------------
# Schema / init tests
# ---------------------------------------------------------------------------

class TestInitDB:
    def test_init_db_creates_tables(self, memory_db):
        """mem_cells, mem_scenes, conversations tables exist."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        # Use the actual DB's connection
        conn = memory_db._connect()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('mem_cells', 'mem_scenes', 'conversations')"
        )
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        assert tables == {"mem_cells", "mem_scenes", "conversations"}

    def test_init_db_fts5_available(self, memory_db):
        """mem_cells_fts exists if FTS5 is supported."""
        if not memory_db._fts_available:
            pytest.skip("FTS5 not available on this platform")
        conn = memory_db._connect()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'mem_cells_fts'"
        )
        assert cur.fetchone() is not None
        conn.close()


# ---------------------------------------------------------------------------
# Memory cell CRUD
# ---------------------------------------------------------------------------

class TestInsertCell:
    def test_insert_cell(self, memory_db):
        """insert_cell returns a positive integer ID."""
        cell = _make_cell()
        row_id = memory_db.insert_cell(cell)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_insert_cell_duplicate_ignored(self, memory_db):
        """Inserting the same (scene, content) returns the same ID."""
        cell = _make_cell()
        id1 = memory_db.insert_cell(cell)
        id2 = memory_db.insert_cell(cell)
        assert id1 == id2

    def test_insert_cell_all_types(self, memory_db):
        """All six CellType values insert successfully."""
        for ct in CellType:
            cell = _make_cell(cell_type=ct, content=f"content for {ct.value}")
            row_id = memory_db.insert_cell(cell)
            assert row_id > 0


class TestGetCellsByScene:
    def test_get_cells_by_scene(self, memory_db):
        """Filters correctly and sorts by salience DESC."""
        memory_db.insert_cell(_make_cell(scene="s1", salience=0.3, content="low"))
        memory_db.insert_cell(_make_cell(scene="s1", salience=0.9, content="high"))
        memory_db.insert_cell(_make_cell(scene="s2", salience=1.0, content="other"))

        cells = memory_db.get_cells_by_scene("s1")
        assert len(cells) == 2
        assert cells[0].salience >= cells[1].salience
        assert all(c.scene == "s1" for c in cells)

    def test_get_cells_by_scene_empty(self, memory_db):
        """Nonexistent scene returns empty list."""
        assert memory_db.get_cells_by_scene("nonexistent") == []


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------

class TestSearchFTS:
    def test_search_fts_single_word(self, memory_db):
        """Finds a cell matching a single search term."""
        memory_db.insert_cell(_make_cell(content="python programming language"))
        memory_db.insert_cell(_make_cell(content="java virtual machine"))

        results = memory_db.search_fts("python")
        assert len(results) >= 1
        assert any("python" in c.content.lower() for c in results)

    def test_search_fts_multi_word(self, memory_db):
        """Multi-token search works."""
        memory_db.insert_cell(_make_cell(content="machine learning algorithms"))
        memory_db.insert_cell(_make_cell(content="deep learning neural networks"))

        results = memory_db.search_fts("machine learning")
        assert len(results) >= 1

    def test_search_fts_no_results(self, memory_db):
        """No match returns empty list."""
        memory_db.insert_cell(_make_cell(content="hello world"))
        results = memory_db.search_fts("xyznonexistent")
        assert results == []

    def test_search_fts_limit(self, memory_db):
        """Respects the limit parameter."""
        for i in range(5):
            memory_db.insert_cell(_make_cell(content=f"searchable item number {i}"))

        results = memory_db.search_fts("searchable", limit=2)
        assert len(results) <= 2


# ---------------------------------------------------------------------------
# Salience ranking
# ---------------------------------------------------------------------------

class TestGetTopSalient:
    def test_get_top_salient(self, memory_db):
        """Returns top N cells by salience."""
        memory_db.insert_cell(_make_cell(salience=0.1, content="low"))
        memory_db.insert_cell(_make_cell(salience=0.5, content="mid"))
        memory_db.insert_cell(_make_cell(salience=0.9, content="high"))

        cells = memory_db.get_top_salient(limit=2)
        assert len(cells) == 2
        assert cells[0].salience >= cells[1].salience
        assert cells[0].salience == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Scene summaries
# ---------------------------------------------------------------------------

class TestSceneSummaries:
    def test_upsert_scene_summary_insert(self, memory_db):
        """New scene creates a summary retrievable by get_scene_summary."""
        memory_db.upsert_scene_summary("s1", "First summary")
        s = memory_db.get_scene_summary("s1")
        assert s is not None
        assert s.scene == "s1"
        assert s.summary == "First summary"

    def test_upsert_scene_summary_update(self, memory_db):
        """Existing scene updates its summary text."""
        memory_db.upsert_scene_summary("s1", "Original")
        memory_db.upsert_scene_summary("s1", "Updated")
        s = memory_db.get_scene_summary("s1")
        assert s.summary == "Updated"

    def test_get_scene_summary_not_found(self, memory_db):
        """Missing scene returns None."""
        assert memory_db.get_scene_summary("missing") is None

    def test_get_all_scene_summaries(self, memory_db):
        """Returns all summaries."""
        memory_db.upsert_scene_summary("a", "Summary A")
        memory_db.upsert_scene_summary("b", "Summary B")
        summaries = memory_db.get_all_scene_summaries()
        assert len(summaries) == 2
        scenes = {s.scene for s in summaries}
        assert scenes == {"a", "b"}


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class TestConversations:
    def test_insert_conversation(self, memory_db):
        """insert_conversation returns a positive integer ID."""
        row_id = memory_db.insert_conversation("Hello", "Hi there", "llama3")
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_get_conversations(self, memory_db):
        """Returns user+assistant ChatMessage pairs."""
        memory_db.insert_conversation("Q1", "A1", "model1")
        messages = memory_db.get_conversations()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Q1"
        assert messages[1].role == "assistant"
        assert messages[1].content == "A1"

    def test_get_conversations_pagination(self, memory_db):
        """Limit and offset work correctly."""
        for i in range(5):
            memory_db.insert_conversation(f"Q{i}", f"A{i}")

        # limit=2 → 2 conversations → 4 messages
        page = memory_db.get_conversations(limit=2, offset=0)
        assert len(page) == 4

        # offset=3 → skip 3 conversations, get remaining 2 → 4 messages
        page2 = memory_db.get_conversations(limit=10, offset=3)
        assert len(page2) == 4  # 2 remaining conversations × 2 messages


# ---------------------------------------------------------------------------
# Size monitoring
# ---------------------------------------------------------------------------

class TestSizeMonitoring:
    def test_get_db_size_bytes(self, temp_db):
        """File-backed DB has size > 0."""
        # Insert data to ensure file is written
        temp_db.insert_cell(_make_cell())
        size = temp_db.get_db_size_bytes()
        assert size > 0

    def test_get_db_size_bytes_memory(self, memory_db):
        """:memory: DB returns 0."""
        assert memory_db.get_db_size_bytes() == 0

    def test_check_size_limit_ok(self, temp_db):
        """No error when under limit."""
        temp_db.check_size_limit()  # should not raise

    def test_check_size_limit_exceeded(self, temp_db):
        """Raises MemoryDBError when over limit."""
        import config.settings as cfg
        original = cfg.MAX_DB_SIZE_MB
        try:
            cfg.MAX_DB_SIZE_MB = 0  # 0 MB limit — any file exceeds it
            temp_db.insert_cell(_make_cell())
            with pytest.raises(MemoryDBError):
                temp_db.check_size_limit()
        finally:
            cfg.MAX_DB_SIZE_MB = original


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager(self):
        """with MemoryDB() as db: works and db is usable."""
        with MemoryDB(":memory:") as db:
            row_id = db.insert_cell(_make_cell())
            assert row_id > 0
