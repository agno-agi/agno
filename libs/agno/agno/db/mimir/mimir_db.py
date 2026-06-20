"""
MimirDb — Mimir-compatible persistent memory for Agno agents.

Uses SQLite + FTS5 (matching Mimir's core architecture) for durable,
sub-millisecond memory operations with full-text search. Zero external
dependencies beyond Python's stdlib sqlite3 module.

Usage:
    from agno.db.mimir import MimirDb

    agent = Agent(
        model=OpenAI(id="gpt-4o"),
        db=MimirDb(db_path="./agno_memory.db"),
        tools=[...]
    )
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, ComponentType, SessionType
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import deserialize_session, deserialize_sessions
from agno.run.base import RunStatus
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_warning

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace


class MimirDb(BaseDb):
    """Persistent memory database for Agno agents backed by SQLite + FTS5.

    Matches Mimir's architecture: embedded SQLite, FTS5 full-text search,
    single-file database, no external services required.

    Args:
        db_path: Path to the SQLite database file. Created if missing.
            Defaults to ``./agno_memory.db``.
        session_table: Override session table name.
        memory_table: Override memory table name.
        **kwargs: Additional table name overrides passed to BaseDb.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            session_table=session_table,
            memory_table=memory_table,
            **kwargs,
        )

        self.db_path = str(Path(db_path or "./agno_memory.db").resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._lock = threading.Lock()

        self._ensure_tables()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _tx(self):
        """Context manager for transactions with auto-commit."""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the thread-local database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """Create all tables and indexes if they don't exist."""
        with self._tx() as conn:
            # --- Sessions ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.session_table_name} (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    agent_id TEXT,
                    team_id TEXT,
                    workflow_id TEXT,
                    session_type TEXT,
                    session_data TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_sessions_user
                ON {self.session_table_name}(user_id)
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_sessions_type
                ON {self.session_table_name}(session_type)
            """)

            # --- Memories ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.memory_table_name} (
                    memory_id TEXT PRIMARY KEY,
                    memory TEXT,
                    topics TEXT,
                    input TEXT,
                    user_id TEXT,
                    agent_id TEXT,
                    team_id TEXT,
                    feedback TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_memories_user
                ON {self.memory_table_name}(user_id)
            """)

            # FTS5 virtual table for full-text search on memories
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {self.memory_table_name}_fts
                USING fts5(
                    memory_id UNINDEXED,
                    memory,
                    input,
                    topics,
                    content='{self.memory_table_name}',
                    content_rowid='rowid'
                )
            """)

            # Triggers to keep FTS5 in sync
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {self.memory_table_name}_ai
                AFTER INSERT ON {self.memory_table_name} BEGIN
                    INSERT INTO {self.memory_table_name}_fts(rowid, memory_id, memory, input, topics)
                    VALUES (new.rowid, new.memory_id, new.memory, new.input, new.topics);
                END
            """)
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {self.memory_table_name}_ad
                AFTER DELETE ON {self.memory_table_name} BEGIN
                    INSERT INTO {self.memory_table_name}_fts({self.memory_table_name}_fts, rowid, memory_id, memory, input, topics)
                    VALUES ('delete', old.rowid, old.memory_id, old.memory, old.input, old.topics);
                END
            """)
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {self.memory_table_name}_au
                AFTER UPDATE ON {self.memory_table_name} BEGIN
                    INSERT INTO {self.memory_table_name}_fts({self.memory_table_name}_fts, rowid, memory_id, memory, input, topics)
                    VALUES ('delete', old.rowid, old.memory_id, old.memory, old.input, old.topics);
                    INSERT INTO {self.memory_table_name}_fts(rowid, memory_id, memory, input, topics)
                    VALUES (new.rowid, new.memory_id, new.memory, new.input, new.topics);
                END
            """)

            # --- Knowledge ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.knowledge_table_name} (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    content TEXT,
                    metadata TEXT,
                    linked_to TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)

            # --- Evals ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.eval_table_name} (
                    eval_run_id TEXT PRIMARY KEY,
                    eval_type TEXT,
                    name TEXT,
                    agent_id TEXT,
                    team_id TEXT,
                    workflow_id TEXT,
                    model_id TEXT,
                    user_id TEXT,
                    data TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)

            # --- Traces ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.trace_table_name} (
                    trace_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    data TEXT,
                    created_at INTEGER
                )
            """)

            # --- Spans ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.span_table_name} (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT,
                    data TEXT,
                    created_at INTEGER
                )
            """)

            # --- Schema versions ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.versions_table_name} (
                    table_name TEXT PRIMARY KEY,
                    version TEXT NOT NULL
                )
            """)

            # --- Metrics ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.metrics_table_name} (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    user_id TEXT,
                    agent_id TEXT,
                    team_id TEXT,
                    data TEXT,
                    created_at INTEGER
                )
            """)

            # --- Culture ---
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.culture_table_name} (
                    id TEXT PRIMARY KEY,
                    data TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)

    # ------------------------------------------------------------------
    # Table existence & schema version
    # ------------------------------------------------------------------

    def table_exists(self, table_name: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def get_latest_schema_version(self, table_name: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT version FROM {self.versions_table_name} WHERE table_name=?",
            (table_name,),
        ).fetchone()
        return row["version"] if row else None

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        with self._tx() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.versions_table_name} (table_name, version) VALUES (?, ?)",
                (table_name, version),
            )

    # ------------------------------------------------------------------
    # Session methods
    # ------------------------------------------------------------------

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        with self._tx() as conn:
            if user_id is not None:
                cur = conn.execute(
                    f"DELETE FROM {self.session_table_name} WHERE session_id=? AND user_id=?",
                    (session_id, user_id),
                )
            else:
                cur = conn.execute(
                    f"DELETE FROM {self.session_table_name} WHERE session_id=?",
                    (session_id,),
                )
            return cur.rowcount > 0

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        if not session_ids:
            return
        with self._tx() as conn:
            placeholders = ",".join("?" * len(session_ids))
            if user_id is not None:
                params = [*session_ids, user_id]
                conn.execute(
                    f"DELETE FROM {self.session_table_name} WHERE session_id IN ({placeholders}) AND user_id=?",
                    params,
                )
            else:
                conn.execute(
                    f"DELETE FROM {self.session_table_name} WHERE session_id IN ({placeholders})",
                    session_ids,
                )

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.session_table_name} WHERE session_id=?"
        params: list = [session_id]

        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if session_type is not None:
            query += " AND session_type=?"
            params.append(session_type.value)

        row = conn.execute(query, params).fetchone()
        if row is None:
            return None

        data = dict(row)
        if data.get("session_data"):
            data["session_data"] = json.loads(data["session_data"])

        if not deserialize:
            return data

        return deserialize_session(session_type, data)

    def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.session_table_name} WHERE 1=1"
        params: list = []

        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if session_type is not None:
            query += " AND session_type=?"
            params.append(session_type.value)
        if component_id is not None:
            query += " AND (agent_id=? OR team_id=? OR workflow_id=?)"
            params.extend([component_id, component_id, component_id])
        if start_timestamp is not None:
            query += " AND created_at>=?"
            params.append(start_timestamp)
        if end_timestamp is not None:
            query += " AND created_at<=?"
            params.append(end_timestamp)

        # Count first
        count_query = query.replace("SELECT *", "SELECT COUNT(*) as cnt")
        total = conn.execute(count_query, params).fetchone()["cnt"]

        # Sort
        sort_col = "created_at"
        if sort_by == "updated_at":
            sort_col = "updated_at"
        direction = "DESC" if sort_order and sort_order.upper() == "ASC" else "DESC"
        query += f" ORDER BY {sort_col} {direction}"

        # Paginate
        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get("session_data"):
                data["session_data"] = json.loads(data["session_data"])
            results.append(data)

        if not deserialize:
            return results, total

        return deserialize_sessions(session_type, results)

    def rename_session(
        self,
        session_id: str,
        session_type: Optional[SessionType],
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.session_table_name} WHERE session_id=?"
        params: list = [session_id]
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if session_type is not None:
            query += " AND session_type=?"
            params.append(session_type.value)

        row = conn.execute(query, params).fetchone()
        if row is None:
            return None

        data = dict(row)
        session_data = json.loads(data["session_data"]) if data.get("session_data") else {}
        session_data["session_name"] = session_name
        data["session_data"] = json.dumps(session_data)

        with self._tx() as txn:
            txn.execute(
                f"UPDATE {self.session_table_name} SET session_data=?, updated_at=? WHERE session_id=?",
                (json.dumps(session_data), int(time.time()), session_id),
            )

        if not deserialize:
            return data

        data["session_data"] = session_data
        return deserialize_session(session_type, data)

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        session_dict = session.to_dict()

        if isinstance(session, AgentSession):
            session_dict["session_type"] = SessionType.AGENT.value
        elif isinstance(session, TeamSession):
            session_dict["session_type"] = SessionType.TEAM.value
        elif isinstance(session, WorkflowSession):
            session_dict["session_type"] = SessionType.WORKFLOW.value

        now = int(time.time())
        session_dict["created_at"] = session_dict.get("created_at", now)
        session_dict["updated_at"] = now

        session_data = session_dict.pop("session_data", None)
        if isinstance(session_data, dict):
            session_data = json.dumps(session_data)

        columns = [
            "session_id", "user_id", "agent_id", "team_id", "workflow_id",
            "session_type", "session_data", "created_at", "updated_at",
        ]
        values = [
            session_dict.get("session_id", str(uuid4())),
            session_dict.get("user_id"),
            session_dict.get("agent_id"),
            session_dict.get("team_id"),
            session_dict.get("workflow_id"),
            session_dict.get("session_type"),
            session_data,
            session_dict.get("created_at"),
            session_dict.get("updated_at"),
        ]

        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.session_table_name}
                ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})""",
                values,
            )

        if not deserialize:
            return dict(zip(columns, values))

        return session

    def upsert_sessions(
        self,
        sessions: List[Session],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[Session, Dict[str, Any]]]:
        return [self.upsert_session(s, deserialize=deserialize) for s in sessions if s is not None]

    # ------------------------------------------------------------------
    # Memory methods (with FTS5 full-text search)
    # ------------------------------------------------------------------

    def clear_memories(self) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.memory_table_name}")

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        with self._tx() as conn:
            if user_id is not None:
                conn.execute(
                    f"DELETE FROM {self.memory_table_name} WHERE memory_id=? AND user_id=?",
                    (memory_id, user_id),
                )
            else:
                conn.execute(
                    f"DELETE FROM {self.memory_table_name} WHERE memory_id=?",
                    (memory_id,),
                )

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        if not memory_ids:
            return
        with self._tx() as conn:
            placeholders = ",".join("?" * len(memory_ids))
            if user_id is not None:
                params = [*memory_ids, user_id]
                conn.execute(
                    f"DELETE FROM {self.memory_table_name} WHERE memory_id IN ({placeholders}) AND user_id=?",
                    params,
                )
            else:
                conn.execute(
                    f"DELETE FROM {self.memory_table_name} WHERE memory_id IN ({placeholders})",
                    memory_ids,
                )

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        conn = self._get_conn()
        if user_id is not None:
            rows = conn.execute(
                f"SELECT DISTINCT topics FROM {self.memory_table_name} WHERE user_id=? AND topics IS NOT NULL",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT DISTINCT topics FROM {self.memory_table_name} WHERE topics IS NOT NULL"
            ).fetchall()

        topics: set = set()
        for row in rows:
            try:
                parsed = json.loads(row["topics"])
                if isinstance(parsed, list):
                    topics.update(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        return list(topics)

    def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.memory_table_name} WHERE memory_id=?"
        params: list = [memory_id]
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)

        row = conn.execute(query, params).fetchone()
        if row is None:
            return None

        return self._row_to_memory(dict(row), deserialize=deserialize)

    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        conn = self._get_conn()

        # If search_content is provided, use FTS5
        if search_content:
            return self._fts_search_memories(
                conn=conn,
                search_content=search_content,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=deserialize,
            )

        # Standard query
        query = f"SELECT * FROM {self.memory_table_name} WHERE 1=1"
        params: list = []

        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if agent_id is not None:
            query += " AND agent_id=?"
            params.append(agent_id)
        if team_id is not None:
            query += " AND team_id=?"
            params.append(team_id)
        if topics:
            topic_clauses = []
            for topic in topics:
                topic_clauses.append("topics LIKE ?")
                params.append(f"%{topic}%")
            query += f" AND ({' OR '.join(topic_clauses)})"

        # Count
        count_query = query.replace("SELECT *", "SELECT COUNT(*) as cnt")
        total = conn.execute(count_query, params).fetchone()["cnt"]

        # Sort
        sort_col = "created_at"
        if sort_by == "updated_at":
            sort_col = "updated_at"
        direction = "DESC" if sort_order and sort_order.upper() == "ASC" else "DESC"
        query += f" ORDER BY {sort_col} {direction}"

        # Paginate
        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = [self._row_to_memory(dict(r), deserialize=deserialize) for r in rows]

        if not deserialize:
            return results, total

        return results

    def _fts_search_memories(
        self,
        conn: sqlite3.Connection,
        search_content: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        """Use FTS5 full-text search for memory content lookup."""
        # Build FTS5 query — quote the terms for phrase matching
        fts_query = f'"{search_content}"'

        try:
            rows = conn.execute(
                f"""
                SELECT m.* FROM {self.memory_table_name}_fts f
                JOIN {self.memory_table_name} m ON f.rowid = m.rowid
                WHERE {self.memory_table_name}_fts MATCH ?
                ORDER BY rank
                """,
                (fts_query,),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS5 may fail on special chars — fall back to LIKE
            rows = conn.execute(
                f"""
                SELECT * FROM {self.memory_table_name}
                WHERE memory LIKE ? OR input LIKE ?
                ORDER BY updated_at DESC
                """,
                (f"%{search_content}%", f"%{search_content}%"),
            ).fetchall()

        # Apply filters post-FTS
        results = []
        for row in rows:
            data = dict(row)
            if user_id is not None and data.get("user_id") != user_id:
                continue
            if agent_id is not None and data.get("agent_id") != agent_id:
                continue
            if team_id is not None and data.get("team_id") != team_id:
                continue
            if topics:
                try:
                    mem_topics = json.loads(data.get("topics") or "[]")
                    if not any(t in mem_topics for t in topics):
                        continue
                except json.JSONDecodeError:
                    continue
            results.append(data)

        total = len(results)

        # Sort
        sort_col = "created_at"
        if sort_by == "updated_at":
            sort_col = "updated_at"
        reverse = not (sort_order and sort_order.upper() == "ASC")
        results.sort(key=lambda r: r.get(sort_col, 0) or 0, reverse=reverse)

        # Paginate
        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            results = results[offset : offset + limit]

        output = [self._row_to_memory(r, deserialize=deserialize) for r in results]

        if not deserialize:
            return output, total

        return output

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        conn = self._get_conn()
        if user_id is not None:
            total = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {self.memory_table_name} WHERE user_id=?",
                (user_id,),
            ).fetchone()["cnt"]
            query = f"SELECT * FROM {self.memory_table_name} WHERE user_id=? ORDER BY updated_at DESC"
            params: list = [user_id]
        else:
            total = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {self.memory_table_name}"
            ).fetchone()["cnt"]
            query = f"SELECT * FROM {self.memory_table_name} ORDER BY updated_at DESC"
            params = []

        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = [self._row_to_memory_dict(dict(r)) for r in rows]
        return results, total

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        memory_id = memory.memory_id or str(uuid4())
        memory.memory_id = memory_id

        now = int(time.time())
        if not memory.created_at:
            memory.created_at = now
        if not memory.updated_at:
            memory.updated_at = now

        topics_json = json.dumps(memory.topics) if memory.topics else None

        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.memory_table_name}
                (memory_id, memory, topics, input, user_id, agent_id, team_id,
                 feedback, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory.memory_id,
                    memory.memory,
                    topics_json,
                    memory.input,
                    memory.user_id,
                    memory.agent_id,
                    memory.team_id,
                    memory.feedback,
                    memory.created_at,
                    memory.updated_at,
                ),
            )

        if not deserialize:
            return memory.to_dict()

        return memory

    def upsert_memories(
        self,
        memories: List[UserMemory],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        return [self.upsert_user_memory(m, deserialize=deserialize) for m in memories if m is not None]

    # ------------------------------------------------------------------
    # Knowledge methods
    # ------------------------------------------------------------------

    def delete_knowledge_content(self, id: str) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.knowledge_table_name} WHERE id=?", (id,))

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT * FROM {self.knowledge_table_name} WHERE id=?", (id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        return KnowledgeRow(
            id=data["id"],
            name=data.get("name") or "",
            description=data.get("description"),
            content=data.get("content"),
            metadata=json.loads(data["metadata"]) if data.get("metadata") else None,
            linked_to=data.get("linked_to"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.knowledge_table_name} WHERE 1=1"
        params: list = []

        if linked_to is not None:
            query += " AND linked_to=?"
            params.append(linked_to)

        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]

        sort_col = "created_at"
        if sort_by:
            sort_col = sort_by
        direction = "DESC" if sort_order and sort_order.upper() == "DESC" else "ASC"
        query += f" ORDER BY {sort_col} {direction}"

        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            results.append(KnowledgeRow(
                id=data["id"],
                name=data.get("name") or "",
                description=data.get("description"),
                content=data.get("content"),
                metadata=json.loads(data["metadata"]) if data.get("metadata") else None,
                linked_to=data.get("linked_to"),
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
            ))
        return results, total

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow) -> Optional[KnowledgeRow]:
        now = int(time.time())
        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.knowledge_table_name}
                (id, name, description, content, metadata, linked_to, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    knowledge_row.id or str(uuid4()),
                    knowledge_row.name,
                    knowledge_row.description,
                    knowledge_row.content,
                    json.dumps(knowledge_row.metadata) if knowledge_row.metadata else None,
                    knowledge_row.linked_to,
                    knowledge_row.created_at or now,
                    knowledge_row.updated_at or now,
                ),
            )
        return knowledge_row

    # ------------------------------------------------------------------
    # Eval methods
    # ------------------------------------------------------------------

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        now = int(time.time())
        with self._tx() as conn:
            conn.execute(
                f"""INSERT INTO {self.eval_table_name}
                (eval_run_id, eval_type, name, agent_id, team_id, workflow_id, model_id,
                 user_id, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    eval_run.eval_run_id or str(uuid4()),
                    eval_run.eval_type.value if eval_run.eval_type else None,
                    getattr(eval_run, "name", None),
                    getattr(eval_run, "agent_id", None),
                    getattr(eval_run, "team_id", None),
                    getattr(eval_run, "workflow_id", None),
                    getattr(eval_run, "model_id", None),
                    getattr(eval_run, "user_id", None),
                    json.dumps(eval_run.to_dict()) if hasattr(eval_run, "to_dict") else None,
                    now,
                    now,
                ),
            )
        return eval_run

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        if not eval_run_ids:
            return
        with self._tx() as conn:
            placeholders = ",".join("?" * len(eval_run_ids))
            conn.execute(
                f"DELETE FROM {self.eval_table_name} WHERE eval_run_id IN ({placeholders})",
                eval_run_ids,
            )

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT * FROM {self.eval_table_name} WHERE eval_run_id=?", (eval_run_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        if deserialize:
            from agno.db.schemas.evals import EvalRunRecord
            return EvalRunRecord.from_dict(data)
        return data

    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_type: Optional[List[EvalType]] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.eval_table_name} WHERE 1=1"
        params: list = []

        if agent_id is not None:
            query += " AND agent_id=?"
            params.append(agent_id)
        if team_id is not None:
            query += " AND team_id=?"
            params.append(team_id)
        if workflow_id is not None:
            query += " AND workflow_id=?"
            params.append(workflow_id)
        if model_id is not None:
            query += " AND model_id=?"
            params.append(model_id)

        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]

        query += " ORDER BY created_at DESC"

        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if deserialize:
                from agno.db.schemas.evals import EvalRunRecord
                results.append(EvalRunRecord.from_dict(data))
            else:
                results.append(data)

        if deserialize:
            return results
        return results, total

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        with self._tx() as conn:
            conn.execute(
                f"UPDATE {self.eval_table_name} SET updated_at=? WHERE eval_run_id=?",
                (int(time.time()), eval_run_id),
            )
        return self.get_eval_run(eval_run_id, deserialize=deserialize)

    # ------------------------------------------------------------------
    # Trace methods
    # ------------------------------------------------------------------

    def upsert_trace(self, trace: "Trace") -> None:
        now = int(time.time() * 1000)
        with self._tx() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.trace_table_name} (trace_id, run_id, data, created_at) VALUES (?, ?, ?, ?)",
                (trace.trace_id, getattr(trace, "run_id", None), json.dumps(trace.to_dict()), now),
            )

    def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        conn = self._get_conn()
        if trace_id:
            row = conn.execute(
                f"SELECT * FROM {self.trace_table_name} WHERE trace_id=?", (trace_id,)
            ).fetchone()
        elif run_id:
            row = conn.execute(
                f"SELECT * FROM {self.trace_table_name} WHERE run_id=?", (run_id,)
            ).fetchone()
        else:
            return None

        if row is None:
            return None
        data = dict(row)
        if data.get("data"):
            data["data"] = json.loads(data["data"])
        return data

    def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.trace_table_name} WHERE 1=1"
        params: list = []

        if run_id is not None:
            query += " AND run_id=?"
            params.append(run_id)

        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]

        query += " ORDER BY created_at DESC"
        if limit is not None:
            offset = (page - 1) * limit if page else 0
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get("data"):
                data["data"] = json.loads(data["data"])
            results.append(data)
        return results, total

    def get_trace_stats(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        return [], 0

    # ------------------------------------------------------------------
    # Span methods
    # ------------------------------------------------------------------

    def create_span(self, span: "Span") -> None:
        now = int(time.time() * 1000)
        with self._tx() as conn:
            conn.execute(
                f"INSERT INTO {self.span_table_name} (span_id, trace_id, data, created_at) VALUES (?, ?, ?, ?)",
                (span.span_id, span.trace_id, json.dumps(span.to_dict()), now),
            )

    # ------------------------------------------------------------------
    # Metrics methods
    # ------------------------------------------------------------------

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        return [], None

    def calculate_metrics(self) -> Optional[Any]:
        return None

    # ------------------------------------------------------------------
    # Cultural Knowledge methods
    # ------------------------------------------------------------------

    def clear_cultural_knowledge(self) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.culture_table_name}")

    def delete_cultural_knowledge(self, id: str) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.culture_table_name} WHERE id=?", (id,))

    def get_cultural_knowledge(self, id: str) -> Optional[CulturalKnowledge]:
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT * FROM {self.culture_table_name} WHERE id=?", (id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("data"):
            data["data"] = json.loads(data["data"])
        return CulturalKnowledge.from_dict(data)

    def get_all_cultural_knowledge(
        self,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[List[CulturalKnowledge]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.culture_table_name} WHERE 1=1"
        params: list = []

        if limit is not None:
            offset = 0
            if page is not None:
                offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get("data"):
                data["data"] = json.loads(data["data"])
            results.append(CulturalKnowledge.from_dict(data))
        return results

    def upsert_cultural_knowledge(self, cultural_knowledge: CulturalKnowledge) -> Optional[CulturalKnowledge]:
        now = int(time.time())
        data_dict = cultural_knowledge.to_dict() if hasattr(cultural_knowledge, "to_dict") else {}
        data_json = json.dumps(data_dict)
        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.culture_table_name}
                (id, data, created_at, updated_at) VALUES (?, ?, ?, ?)""",
                (cultural_knowledge.id or str(uuid4()), data_json, now, now),
            )
        return cultural_knowledge

    # ------------------------------------------------------------------
    # Additional Span methods
    # ------------------------------------------------------------------

    def create_spans(self, spans: List) -> None:
        for span in spans:
            self.create_span(span)

    def get_span(self, span_id: str):
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT * FROM {self.span_table_name} WHERE span_id=?", (span_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("data"):
            data["data"] = json.loads(data["data"])
        return data

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.span_table_name} WHERE 1=1"
        params: list = []

        if trace_id is not None:
            query += " AND trace_id=?"
            params.append(trace_id)

        query += " ORDER BY created_at ASC"
        if limit is not None:
            query += f" LIMIT {limit}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get("data"):
                data["data"] = json.loads(data["data"])
            results.append(data)
        return results

    # ------------------------------------------------------------------
    # Learning methods
    # ------------------------------------------------------------------

    def _ensure_learnings_table(self) -> None:
        with self._tx() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.learnings_table_name} (
                    id TEXT PRIMARY KEY,
                    learning_type TEXT NOT NULL,
                    content TEXT,
                    user_id TEXT,
                    agent_id TEXT,
                    team_id TEXT,
                    session_id TEXT,
                    namespace TEXT,
                    entity_id TEXT,
                    entity_type TEXT,
                    metadata TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)

    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._ensure_learnings_table()
        conn = self._get_conn()
        query = f"SELECT * FROM {self.learnings_table_name} WHERE learning_type=?"
        params: list = [learning_type]

        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if agent_id is not None:
            query += " AND agent_id=?"
            params.append(agent_id)
        if team_id is not None:
            query += " AND team_id=?"
            params.append(team_id)
        if session_id is not None:
            query += " AND session_id=?"
            params.append(session_id)
        if namespace is not None:
            query += " AND namespace=?"
            params.append(namespace)
        if entity_id is not None:
            query += " AND entity_id=?"
            params.append(entity_id)
        if entity_type is not None:
            query += " AND entity_type=?"
            params.append(entity_type)

        query += " ORDER BY updated_at DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("content"):
            data["content"] = json.loads(data["content"])
        if data.get("metadata"):
            data["metadata"] = json.loads(data["metadata"])
        return data

    def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._ensure_learnings_table()
        now = int(time.time())
        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.learnings_table_name}
                (id, learning_type, content, user_id, agent_id, team_id, session_id,
                 namespace, entity_id, entity_type, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    id, learning_type, json.dumps(content),
                    user_id, agent_id, team_id, session_id,
                    namespace, entity_id, entity_type,
                    json.dumps(metadata) if metadata else None,
                    now, now,
                ),
            )

    def delete_learning(self, id: str) -> bool:
        self._ensure_learnings_table()
        with self._tx() as conn:
            cur = conn.execute(
                f"DELETE FROM {self.learnings_table_name} WHERE id=?", (id,)
            )
            return cur.rowcount > 0

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_learnings_table()
        conn = self._get_conn()
        query = f"SELECT * FROM {self.learnings_table_name} WHERE 1=1"
        params: list = []

        if learning_type is not None:
            query += " AND learning_type=?"
            params.append(learning_type)
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        if agent_id is not None:
            query += " AND agent_id=?"
            params.append(agent_id)
        if team_id is not None:
            query += " AND team_id=?"
            params.append(team_id)
        if session_id is not None:
            query += " AND session_id=?"
            params.append(session_id)
        if namespace is not None:
            query += " AND namespace=?"
            params.append(namespace)
        if entity_id is not None:
            query += " AND entity_id=?"
            params.append(entity_id)
        if entity_type is not None:
            query += " AND entity_type=?"
            params.append(entity_type)

        query += " ORDER BY updated_at DESC"
        if limit is not None:
            query += f" LIMIT {limit}"

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            if data.get("content"):
                data["content"] = json.loads(data["content"])
            if data.get("metadata"):
                data["metadata"] = json.loads(data["metadata"])
            results.append(data)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _row_to_memory(
        self,
        data: Dict[str, Any],
        deserialize: bool = True,
    ) -> Union[UserMemory, Dict[str, Any]]:
        """Convert a DB row dict to a UserMemory or dict."""
        if isinstance(data.get("topics"), str):
            try:
                data["topics"] = json.loads(data["topics"])
            except (json.JSONDecodeError, TypeError):
                data["topics"] = []

        if not deserialize:
            return data

        mem = UserMemory(
            memory=data.get("memory", ""),
            memory_id=data.get("memory_id"),
            topics=data.get("topics"),
            user_id=data.get("user_id"),
            input=data.get("input"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            feedback=data.get("feedback"),
            agent_id=data.get("agent_id"),
            team_id=data.get("team_id"),
        )
        return mem

    def _row_to_memory_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a DB row to a clean dict."""
        if isinstance(data.get("topics"), str):
            try:
                data["topics"] = json.loads(data["topics"])
            except (json.JSONDecodeError, TypeError):
                data["topics"] = []
        return {k: v for k, v in data.items() if v is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "db_path": self.db_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MimirDb":
        return cls(
            db_path=data.get("db_path"),
            session_table=data.get("session_table"),
            memory_table=data.get("memory_table"),
            metrics_table=data.get("metrics_table"),
            eval_table=data.get("eval_table"),
            knowledge_table=data.get("knowledge_table"),
            traces_table=data.get("traces_table"),
            spans_table=data.get("spans_table"),
            versions_table=data.get("versions_table"),
            id=data.get("id"),
        )
