"""SQLite persistence layer for agent memory.

Stores memory cells, scene summaries, and conversations.
Supports FTS5 full-text search with transparent LIKE fallback.
Uses WAL mode for concurrent reads/writes and connection-per-operation
to minimize RAM on constrained hardware (Orin Nano).
"""

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from config import settings
from exceptions import MemoryDBError
from models import CellType, ChatMessage, MemoryCell, SceneSummary

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS mem_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scene TEXT NOT NULL,
    cell_type TEXT NOT NULL CHECK(cell_type IN ('fact','plan','preference','decision','task','risk')),
    salience REAL NOT NULL CHECK(salience >= 0.0 AND salience <= 1.0),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(scene, content)
);
CREATE INDEX IF NOT EXISTS idx_cells_scene ON mem_cells(scene);
CREATE INDEX IF NOT EXISTS idx_cells_salience ON mem_cells(salience DESC);

CREATE TABLE IF NOT EXISTS mem_scenes (
    scene TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_msg TEXT NOT NULL,
    assistant_msg TEXT NOT NULL,
    model_used TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC);
"""

_FTS5_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS mem_cells_fts USING fts5(
    content,
    content_rowid=id,
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS mem_cells_ai AFTER INSERT ON mem_cells BEGIN
    INSERT INTO mem_cells_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS mem_cells_au AFTER UPDATE ON mem_cells BEGIN
    UPDATE mem_cells_fts SET content = new.content WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS mem_cells_ad AFTER DELETE ON mem_cells BEGIN
    DELETE FROM mem_cells_fts WHERE rowid = old.id;
END;
"""


class MemoryDB:
    """SQLite wrapper for agent memory persistence.

    Args:
        db_path: Path to the SQLite database file, or ``":memory:"``
                 for an in-memory database. Defaults to ``config.settings.DB_PATH``.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path if db_path is not None else settings.DB_PATH
        # Each :memory: instance gets a unique shared-cache name so that
        # multiple MemoryDB(":memory:") instances are isolated from each other
        # while still sharing data across connection-per-operation calls.
        self._mem_uri: Optional[str] = None
        if self.db_path == ":memory:":
            name = uuid.uuid4().hex
            self._mem_uri = f"file:{name}?mode=memory&cache=shared"
        # For shared-cache in-memory DBs, keep one connection alive so the
        # database isn't destroyed when per-operation connections close.
        self._keepalive: Optional[sqlite3.Connection] = None
        if self._mem_uri is not None:
            self._keepalive = sqlite3.connect(
                self._mem_uri, uri=True, check_same_thread=False,
            )
        logger.debug("MemoryDB init: db_path=%s", self.db_path)
        self._fts_available = self._check_fts5()
        logger.info("FTS5 available: %s", self._fts_available)
        self.init_db()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "MemoryDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._keepalive is not None:
            self._keepalive.close()
            self._keepalive = None

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a new connection with WAL mode and recommended pragmas.

        For ``:memory:`` databases a shared-cache URI is used so that
        every connection returned by this method sees the same data.
        """
        if self._mem_uri is not None:
            conn = sqlite3.connect(
                self._mem_uri,
                uri=True,
                check_same_thread=False,
            )
        else:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _check_fts5() -> bool:
        """Return True if the runtime SQLite supports FTS5."""
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(content)")
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create all tables, indexes, and (optionally) FTS5 objects."""
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
            if self._fts_available:
                conn.executescript(_FTS5_SQL)
            conn.commit()
            logger.info("Database initialized: %s", self.db_path)
        except sqlite3.Error as exc:
            raise MemoryDBError(f"Failed to initialize database: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Datetime helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_db_datetime(dt: datetime) -> str:
        return dt.isoformat()

    @staticmethod
    def _from_db_datetime(text: str) -> datetime:
        return datetime.fromisoformat(text)

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_cell(row: tuple) -> MemoryCell:
        """Map a (id, scene, cell_type, salience, content, created_at) row."""
        return MemoryCell(
            id=row[0],
            scene=row[1],
            cell_type=CellType(row[2]),
            salience=row[3],
            content=row[4],
            created_at=MemoryDB._from_db_datetime(row[5]),
        )

    # ------------------------------------------------------------------
    # Memory cells
    # ------------------------------------------------------------------

    def insert_cell(self, cell: MemoryCell) -> int:
        """Insert a memory cell. Returns its row ID.

        If a cell with the same ``(scene, content)`` already exists the
        existing row ID is returned instead (duplicate-safe).
        """
        logger.debug("insert_cell: scene=%s type=%s salience=%.2f",
                      cell.scene, cell.cell_type.value, cell.salience)
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO mem_cells (scene, cell_type, salience, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (cell.scene, cell.cell_type.value, cell.salience,
                 cell.content, self._to_db_datetime(cell.created_at)),
            )
            conn.commit()
            row_id = cur.lastrowid
            logger.info("Inserted cell id=%d", row_id)
            return row_id
        except sqlite3.IntegrityError:
            # Duplicate (scene, content) — return the existing row's ID
            cur = conn.execute(
                "SELECT id FROM mem_cells WHERE scene = ? AND content = ?",
                (cell.scene, cell.content),
            )
            row = cur.fetchone()
            existing_id = row[0] if row else -1
            logger.debug("Duplicate cell, returning existing id=%d", existing_id)
            return existing_id
        except sqlite3.Error as exc:
            raise MemoryDBError(f"insert_cell failed: {exc}") from exc
        finally:
            conn.close()

    def get_cells_by_scene(self, scene: str) -> list[MemoryCell]:
        """Return all cells for *scene*, sorted by salience DESC."""
        logger.debug("get_cells_by_scene: scene=%s", scene)
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, scene, cell_type, salience, content, created_at "
                "FROM mem_cells WHERE scene = ? ORDER BY salience DESC",
                (scene,),
            )
            cells = [self._row_to_cell(r) for r in cur.fetchall()]
            logger.info("get_cells_by_scene: %d cells for scene=%s", len(cells), scene)
            return cells
        except sqlite3.Error as exc:
            raise MemoryDBError(f"get_cells_by_scene failed: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Full-text search
    # ------------------------------------------------------------------

    def search_fts(self, query: str, limit: int = 10) -> list[MemoryCell]:
        """Search cells by content. Uses FTS5 if available, else LIKE."""
        logger.debug("search_fts: query=%r limit=%d fts5=%s",
                      query, limit, self._fts_available)
        if self._fts_available:
            return self._search_fts5(query, limit)
        return self._search_like(query, limit)

    def _search_fts5(self, query: str, limit: int) -> list[MemoryCell]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT m.id, m.scene, m.cell_type, m.salience, m.content, m.created_at "
                "FROM mem_cells_fts f "
                "JOIN mem_cells m ON f.rowid = m.id "
                "WHERE mem_cells_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?",
                (query, limit),
            )
            cells = [self._row_to_cell(r) for r in cur.fetchall()]
            logger.info("FTS5 search: %d results for %r", len(cells), query)
            return cells
        except sqlite3.Error as exc:
            raise MemoryDBError(f"FTS5 search failed: {exc}") from exc
        finally:
            conn.close()

    def _search_like(self, query: str, limit: int) -> list[MemoryCell]:
        conn = self._connect()
        try:
            tokens = query.split()
            if not tokens:
                return []
            clauses = " AND ".join(["content LIKE ?"] * len(tokens))
            params: list = [f"%{t}%" for t in tokens]
            params.append(limit)
            cur = conn.execute(
                f"SELECT id, scene, cell_type, salience, content, created_at "
                f"FROM mem_cells WHERE {clauses} "
                f"ORDER BY salience DESC LIMIT ?",
                params,
            )
            cells = [self._row_to_cell(r) for r in cur.fetchall()]
            logger.info("LIKE search: %d results for %r", len(cells), query)
            return cells
        except sqlite3.Error as exc:
            raise MemoryDBError(f"LIKE search failed: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Salience ranking
    # ------------------------------------------------------------------

    def get_top_salient(self, limit: int = 10) -> list[MemoryCell]:
        """Return the top *limit* cells globally, ranked by salience DESC."""
        logger.debug("get_top_salient: limit=%d", limit)
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, scene, cell_type, salience, content, created_at "
                "FROM mem_cells ORDER BY salience DESC LIMIT ?",
                (limit,),
            )
            cells = [self._row_to_cell(r) for r in cur.fetchall()]
            logger.info("get_top_salient: %d cells", len(cells))
            return cells
        except sqlite3.Error as exc:
            raise MemoryDBError(f"get_top_salient failed: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Scene summaries
    # ------------------------------------------------------------------

    def upsert_scene_summary(self, scene: str, summary: str) -> None:
        """Insert or update a scene summary."""
        logger.debug("upsert_scene_summary: scene=%s", scene)
        now = self._to_db_datetime(datetime.now(timezone.utc))
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO mem_scenes (scene, summary, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(scene) DO UPDATE SET summary=excluded.summary, "
                "updated_at=excluded.updated_at",
                (scene, summary, now),
            )
            conn.commit()
            logger.info("Upserted scene summary: scene=%s", scene)
        except sqlite3.Error as exc:
            raise MemoryDBError(f"upsert_scene_summary failed: {exc}") from exc
        finally:
            conn.close()

    def get_scene_summary(self, scene: str) -> Optional[SceneSummary]:
        """Return the summary for *scene*, or None if not found."""
        logger.debug("get_scene_summary: scene=%s", scene)
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT scene, summary, updated_at FROM mem_scenes WHERE scene = ?",
                (scene,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return SceneSummary(
                scene=row[0],
                summary=row[1],
                updated_at=self._from_db_datetime(row[2]),
            )
        except sqlite3.Error as exc:
            raise MemoryDBError(f"get_scene_summary failed: {exc}") from exc
        finally:
            conn.close()

    def get_all_scene_summaries(self) -> list[SceneSummary]:
        """Return all scene summaries, sorted by updated_at DESC."""
        logger.debug("get_all_scene_summaries")
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT scene, summary, updated_at FROM mem_scenes "
                "ORDER BY updated_at DESC"
            )
            summaries = [
                SceneSummary(
                    scene=r[0],
                    summary=r[1],
                    updated_at=self._from_db_datetime(r[2]),
                )
                for r in cur.fetchall()
            ]
            logger.info("get_all_scene_summaries: %d summaries", len(summaries))
            return summaries
        except sqlite3.Error as exc:
            raise MemoryDBError(f"get_all_scene_summaries failed: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def insert_conversation(self, user_msg: str, assistant_msg: str,
                            model_used: Optional[str] = None) -> int:
        """Store a conversation turn. Returns the row ID."""
        logger.debug("insert_conversation: model=%s", model_used)
        now = self._to_db_datetime(datetime.now(timezone.utc))
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO conversations (user_msg, assistant_msg, model_used, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (user_msg, assistant_msg, model_used, now),
            )
            conn.commit()
            row_id = cur.lastrowid
            logger.info("Inserted conversation id=%d", row_id)
            return row_id
        except sqlite3.Error as exc:
            raise MemoryDBError(f"insert_conversation failed: {exc}") from exc
        finally:
            conn.close()

    def get_conversations(self, limit: int = 50,
                          offset: int = 0) -> list[ChatMessage]:
        """Return conversation history as ChatMessage pairs, newest first.

        Each stored row yields two ChatMessage objects (user, then assistant).
        """
        logger.debug("get_conversations: limit=%d offset=%d", limit, offset)
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT user_msg, assistant_msg, model_used, timestamp "
                "FROM conversations ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            messages: list[ChatMessage] = []
            for row in cur.fetchall():
                ts = self._from_db_datetime(row[3])
                messages.append(ChatMessage(
                    role="user", content=row[0],
                    timestamp=ts, model_used=row[2],
                ))
                messages.append(ChatMessage(
                    role="assistant", content=row[1],
                    timestamp=ts, model_used=row[2],
                ))
            logger.info("get_conversations: %d messages", len(messages))
            return messages
        except sqlite3.Error as exc:
            raise MemoryDBError(f"get_conversations failed: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Size monitoring (Orin Nano constraint)
    # ------------------------------------------------------------------

    def get_db_size_bytes(self) -> int:
        """Return the database file size in bytes. Returns 0 for :memory:."""
        if self.db_path == ":memory:":
            return 0
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0

    def check_size_limit(self) -> None:
        """Warn at 80% of MAX_DB_SIZE_MB; raise MemoryDBError if exceeded."""
        size = self.get_db_size_bytes()
        max_bytes = settings.MAX_DB_SIZE_MB * 1024 * 1024
        if size > max_bytes:
            raise MemoryDBError(
                f"Database size {size} bytes exceeds limit "
                f"{settings.MAX_DB_SIZE_MB} MB"
            )
        if size > max_bytes * 0.8:
            logger.warning(
                "Database at %.0f%% of %d MB limit (%d bytes)",
                (size / max_bytes) * 100, settings.MAX_DB_SIZE_MB, size,
            )
