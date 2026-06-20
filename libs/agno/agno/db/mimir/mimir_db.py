"""
MimirDb — persistent memory for Agno agents, backed by the real Mimir engine.

Integrates the Mimir binary (https://github.com/Perseus-Computing-LLC/mimir)
via MCP JSON-RPC 2.0 over stdio. Memory operations use Mimir's full engine:
FTS5 + hybrid vector search, AES-256-GCM encryption, confidence decay, journal,
and timeline. Session and infrastructure tables use SQLite for compatibility
with Agno's existing APIs.

Requires the Mimir binary. Install with:
    cargo install mimir
or download from https://github.com/Perseus-Computing-LLC/mimir/releases

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
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import time
import weakref
from contextlib import contextmanager
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process reaper — prevents zombie <defunct> mimir processes
# ---------------------------------------------------------------------------

def _reap_process(proc: subprocess.Popen | None) -> None:
    """Terminate and wait on a Mimir child process."""
    if proc is None:
        return
    if proc.poll() is not None:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        return
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 client for Mimir over stdio
# ---------------------------------------------------------------------------

class _MimirClient:
    """Lightweight JSON-RPC 2.0 client for the Mimir binary over stdio."""

    def __init__(self, binary: str, db_path: str, timeout: float = 30.0) -> None:
        self._binary = binary
        self._db_path = db_path
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._finalizer: weakref.finalize | None = None
        self._lock = threading.Lock()
        self._request_id = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Launch the Mimir binary and perform MCP handshake."""
        if self._proc is not None:
            return True

        try:
            self._proc = subprocess.Popen(
                [self._binary, "--db", self._db_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            logger.error("Mimir binary not found: %s", self._binary)
            return False
        except Exception as e:
            logger.error("Failed to start Mimir: %s", e)
            return False

        self._finalizer = weakref.finalize(self, _reap_process, self._proc)

        # MCP initialize handshake
        try:
            result = self._call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agno-mimir", "version": "0.1.0"},
            })
            if result is None:
                logger.error("Mimir initialize handshake failed")
                self.stop()
                return False
        except Exception as e:
            logger.error("Mimir initialize error: %s", e)
            self.stop()
            return False

        return True

    def stop(self) -> None:
        """Terminate the Mimir subprocess cleanly."""
        proc = self._proc
        self._proc = None
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None
        if proc is None:
            return
        _reap_process(proc)

    def is_running(self) -> bool:
        """Check if the Mimir subprocess is alive."""
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------------
    # JSON-RPC
    # ------------------------------------------------------------------

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call a Mimir MCP tool via tools/call and return the text result."""
        result = self._call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result is None:
            return json.dumps({"error": "Mimir MCP call failed"})

        content = result.get("content", [])
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return "\n".join(text_parts) if text_parts else json.dumps(result)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return available Mimir MCP tools."""
        result = self._call("tools/list", {})
        if result is None:
            return []
        return result.get("tools", [])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
        """Send JSON-RPC request and return the result."""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return None

            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }

            try:
                req_str = json.dumps(request) + "\n"
                self._proc.stdin.write(req_str)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                logger.warning("Mimir write failed: %s", e)
                return None

            try:
                line = self._proc.stdout.readline()
                if not line:
                    return None
                response = json.loads(line)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Mimir read failed: %s", e)
                return None

            if "error" in response:
                logger.warning("Mimir RPC error: %s", response["error"])
                return None

            return response.get("result")


# ---------------------------------------------------------------------------
# MimirDb — Agno BaseDb backed by real Mimir binary + SQLite
# ---------------------------------------------------------------------------

class MimirDb(BaseDb):
    """Persistent memory for Agno agents backed by the real Mimir engine.

    Memory operations (remember, recall, forget, search) route through the
    Mimir binary via MCP JSON-RPC 2.0, giving you FTS5 + hybrid vector search,
    AES-256-GCM encryption, confidence decay, journal, timeline, and more.

    Session, knowledge, eval, and trace tables use SQLite for compatibility
    with Agno's internal APIs.

    Args:
        db_path: Path to the Mimir SQLite database file. Created if missing.
        mimir_binary: Path to the Mimir binary. Auto-detected from PATH
            if not specified.
        session_table: Override session table name.
        memory_table: Override memory table name.
        **kwargs: Additional table name overrides passed to BaseDb.
    """

    # Category names used for Mimir entities
    MEMORY_CATEGORY = "agno_memory"

    def __init__(
        self,
        db_path: Optional[str] = None,
        mimir_binary: Optional[str] = None,
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

        # Mimir binary
        self._mimir_binary = mimir_binary or self._resolve_binary()
        self._mimir_client: _MimirClient | None = None
        self._mimir_available = False

        # SQLite for infrastructure tables
        self._local = threading.local()
        self._lock = threading.Lock()

        # Try to start Mimir
        if self._mimir_binary:
            self._start_mimir()

        # Always create SQLite tables for infrastructure
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Mimir lifecycle
    # ------------------------------------------------------------------

    def _resolve_binary(self) -> str | None:
        """Find the Mimir binary on the system."""
        which = shutil.which("mimir")
        if which:
            return which
        for candidate in [
            os.path.expanduser("~/.cargo/bin/mimir"),
            "/usr/local/bin/mimir",
            "/opt/mimir/mimir",
        ]:
            if os.path.isfile(candidate):
                return candidate
        return None

    def _start_mimir(self) -> None:
        """Start the Mimir binary and perform MCP handshake."""
        if self._mimir_client is not None:
            return

        if not self._mimir_binary:
            logger.warning("Mimir binary not found — memory operations will use SQLite fallback")
            return

        self._mimir_client = _MimirClient(self._mimir_binary, self.db_path)

        if not self._mimir_client.start():
            logger.warning("Mimir failed to start — memory operations will use SQLite fallback")
            self._mimir_client = None
            return

        self._mimir_available = True
        logger.info("Mimir memory engine ready — db=%s", self.db_path)

    def close(self) -> None:
        """Close database connections and terminate the Mimir subprocess."""
        if self._mimir_client:
            self._mimir_client.stop()
            self._mimir_client = None
            self._mimir_available = False
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------
    # SQLite connection (for infrastructure tables)
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection for non-memory tables."""
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
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Schema (SQLite — sessions, knowledge, evals, traces, etc.)
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """Create SQLite tables for non-memory infrastructure."""
        with self._tx() as conn:
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

            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.trace_table_name} (
                    trace_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    data TEXT,
                    created_at INTEGER
                )
            """)

            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.span_table_name} (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT,
                    data TEXT,
                    created_at INTEGER
                )
            """)

            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.versions_table_name} (
                    table_name TEXT PRIMARY KEY,
                    version TEXT NOT NULL
                )
            """)

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

            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.culture_table_name} (
                    id TEXT PRIMARY KEY,
                    data TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)

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

    # ------------------------------------------------------------------
    # Table existence & schema version
    # ------------------------------------------------------------------

    def table_exists(self, table_name: str) -> bool:
        if table_name == self.memory_table_name:
            # Memory is in Mimir — always "exists" if Mimir is running,
            # otherwise in the SQLite database
            return self._mimir_available or self._sqlite_table_exists(table_name)
        return self._sqlite_table_exists(table_name)

    def _sqlite_table_exists(self, table_name: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def get_latest_schema_version(self, table_name: str) -> str | None:
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

    # ==================================================================
    # MEMORY METHODS — routed through real Mimir MCP tools
    # ==================================================================

    def clear_memories(self) -> None:
        """Clear all Agno memories from Mimir."""
        if self._mimir_available and self._mimir_client:
            # Prune all entities in the agno_memory category
            self._mimir_client.call_tool("mimir_prune", {
                "category": self.MEMORY_CATEGORY,
            })
        else:
            with self._tx() as conn:
                conn.execute(f"DELETE FROM {self.memory_table_name}")

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        """Delete a memory via Mimir forget."""
        if self._mimir_available and self._mimir_client:
            self._mimir_client.call_tool("mimir_forget", {
                "category": self.MEMORY_CATEGORY,
                "key": memory_id,
            })
        else:
            with self._tx() as conn:
                conn.execute(
                    f"DELETE FROM {self.memory_table_name} WHERE memory_id=?",
                    (memory_id,),
                )

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        if not memory_ids:
            return
        for mid in memory_ids:
            self.delete_user_memory(mid, user_id=user_id)

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get distinct topics by scanning Mimir entities."""
        if self._mimir_available and self._mimir_client:
            # Recall all memories and extract topics
            result = self._mimir_client.call_tool("mimir_recall", {
                "query": "",
                "category": self.MEMORY_CATEGORY,
                "limit": 1000,
            })
            topics: set = set()
            try:
                data = json.loads(result)
                if isinstance(data, list):
                    for item in data:
                        body = item.get("body_json", "{}")
                        if isinstance(body, str):
                            body = json.loads(body)
                        mem_topics = body.get("topics", [])
                        if isinstance(mem_topics, list):
                            topics.update(mem_topics)
            except (json.JSONDecodeError, TypeError):
                pass
            return list(topics)

        # SQLite fallback
        conn = self._get_conn()
        rows = conn.execute(
            f"SELECT topics FROM {self.memory_table_name} WHERE topics IS NOT NULL"
        ).fetchall()
        topics = set()
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
        """Retrieve a single memory by ID from Mimir."""
        if self._mimir_available and self._mimir_client:
            result = self._mimir_client.call_tool("mimir_recall", {
                "query": memory_id,
                "category": self.MEMORY_CATEGORY,
                "limit": 10,
            })
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "items" in parsed:
                    data = parsed["items"]
                elif isinstance(parsed, list):
                    data = parsed
                else:
                    data = []
            except (json.JSONDecodeError, TypeError):
                return None

            if isinstance(data, list):
                for item in data:
                    if item.get("key") == memory_id:
                        return self._entity_to_memory(item, deserialize=deserialize)
            return None

        # SQLite fallback
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT * FROM {self.memory_table_name} WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
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
        """Search memories via Mimir's FTS5 + hybrid vector search."""
        if self._mimir_available and self._mimir_client:
            query = search_content or ""
            recall_limit = limit or 100

            # If filtering by user_id, include it in the search
            if user_id:
                query = f"{query} {user_id}"

            result = self._mimir_client.call_tool("mimir_recall", {
                "query": query,
                "category": self.MEMORY_CATEGORY,
                "limit": recall_limit + (page or 0) * (limit or 10) if page else recall_limit,
            })

            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "items" in parsed:
                    entities = parsed["items"]
                elif isinstance(parsed, list):
                    entities = parsed
                else:
                    entities = []
            except (json.JSONDecodeError, TypeError):
                entities = []

            memories = []
            for entity in entities:
                mem = self._entity_to_memory(entity, deserialize=False)
                if mem is None:
                    continue

                # Apply post-search filters
                if user_id and mem.get("user_id") != user_id:
                    continue
                if agent_id and mem.get("agent_id") != agent_id:
                    continue
                if team_id and mem.get("team_id") != team_id:
                    continue
                if topics:
                    mem_topics = mem.get("topics", [])
                    if not any(t in mem_topics for t in topics):
                        continue

                if deserialize:
                    memories.append(self._entity_to_memory(entity, deserialize=True))
                else:
                    memories.append(mem)

            total = len(memories)

            # Paginate
            if limit is not None and page is not None:
                offset = (page - 1) * limit
                memories = memories[offset : offset + limit]

            if not deserialize:
                return memories, total
            return memories

        # SQLite fallback
        return self._sqlite_get_user_memories(
            user_id=user_id, agent_id=agent_id, team_id=team_id,
            topics=topics, search_content=search_content,
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order,
            deserialize=deserialize,
        )

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        if self._mimir_available and self._mimir_client:
            result = self._mimir_client.call_tool("mimir_recall", {
                "query": user_id or "",
                "category": self.MEMORY_CATEGORY,
                "limit": 1000,
            })
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "items" in parsed:
                    entities = parsed["items"]
                elif isinstance(parsed, list):
                    entities = parsed
                else:
                    entities = []
            except (json.JSONDecodeError, TypeError):
                entities = []

            results = []
            for e in entities:
                mem = self._entity_to_memory(e, deserialize=False)
                if mem is not None:
                    results.append(mem)
            total = len(results)

            if limit:
                offset = ((page or 1) - 1) * limit
                results = results[offset : offset + limit]

            return results, total

        # SQLite fallback
        conn = self._get_conn()
        total = conn.execute(f"SELECT COUNT(*) as cnt FROM {self.memory_table_name}").fetchone()["cnt"]
        query = f"SELECT * FROM {self.memory_table_name} ORDER BY updated_at DESC"
        if limit:
            offset = ((page or 1) - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"
        rows = conn.execute(query).fetchall()
        return [self._row_to_memory_dict(dict(r)) for r in rows], total

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Store a memory via Mimir remember."""
        memory_id = memory.memory_id or str(uuid4())
        memory.memory_id = memory_id

        now = int(time.time())
        if not memory.created_at:
            memory.created_at = now
        if not memory.updated_at:
            memory.updated_at = now

        body = {
            "memory": memory.memory,
            "topics": memory.topics or [],
            "input": memory.input,
            "user_id": memory.user_id,
            "agent_id": memory.agent_id,
            "team_id": memory.team_id,
            "feedback": memory.feedback,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            "memory_id": memory_id,
        }

        if self._mimir_available and self._mimir_client:
            self._mimir_client.call_tool("mimir_remember", {
                "category": self.MEMORY_CATEGORY,
                "key": memory_id,
                "body_json": json.dumps(body),
                "type": "insight",
                "status": "active",
            })
        else:
            self._sqlite_upsert_memory(memory)

        if not deserialize:
            return body
        return memory

    def upsert_memories(
        self,
        memories: List[UserMemory],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        return [self.upsert_user_memory(m, deserialize=deserialize) for m in memories if m is not None]

    # ------------------------------------------------------------------
    # SQLite fallback for memory (when Mimir binary not available)
    # ------------------------------------------------------------------

    def _sqlite_ensure_memory_table(self) -> None:
        with self._tx() as conn:
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

    def _sqlite_upsert_memory(self, memory: UserMemory) -> None:
        self._sqlite_ensure_memory_table()
        topics_json = json.dumps(memory.topics) if memory.topics else None
        now = int(time.time())
        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.memory_table_name}
                (memory_id, memory, topics, input, user_id, agent_id, team_id,
                 feedback, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory.memory_id, memory.memory, topics_json,
                    memory.input, memory.user_id, memory.agent_id,
                    memory.team_id, memory.feedback,
                    memory.created_at or now, memory.updated_at or now,
                ),
            )

    def _sqlite_get_user_memories(
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
        self._sqlite_ensure_memory_table()
        conn = self._get_conn()
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
        if search_content:
            query += " AND (memory LIKE ? OR input LIKE ?)"
            params.extend([f"%{search_content}%", f"%{search_content}%"])
        if topics:
            for topic in topics:
                query += " AND topics LIKE ?"
                params.append(f"%{topic}%")

        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]

        sort_col = "created_at" if sort_by != "updated_at" else "updated_at"
        direction = "DESC" if not (sort_order and sort_order.upper() == "ASC") else "ASC"
        query += f" ORDER BY {sort_col} {direction}"

        if limit is not None:
            offset = ((page or 1) - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(query, params).fetchall()
        results = [self._row_to_memory(dict(r), deserialize=deserialize) for r in rows]

        if not deserialize:
            return results, total
        return results

    # ==================================================================
    # SESSION METHODS — SQLite
    # ==================================================================

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        with self._tx() as conn:
            if user_id:
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
            if user_id:
                conn.execute(
                    f"DELETE FROM {self.session_table_name} WHERE session_id IN ({placeholders}) AND user_id=?",
                    [*session_ids, user_id],
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
        if user_id:
            query += " AND user_id=?"
            params.append(user_id)
        if session_type:
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

        if user_id:
            query += " AND user_id=?"
            params.append(user_id)
        if session_type:
            query += " AND session_type=?"
            params.append(session_type.value)
        if component_id:
            query += " AND (agent_id=? OR team_id=? OR workflow_id=?)"
            params.extend([component_id, component_id, component_id])
        if start_timestamp:
            query += " AND created_at>=?"
            params.append(start_timestamp)
        if end_timestamp:
            query += " AND created_at<=?"
            params.append(end_timestamp)

        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]

        sort_col = "created_at" if sort_by != "updated_at" else "updated_at"
        direction = "DESC" if not (sort_order and sort_order.upper() == "ASC") else "ASC"
        query += f" ORDER BY {sort_col} {direction}"

        if limit:
            offset = ((page or 1) - 1) * limit
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
        data = self.get_session(session_id, session_type=session_type, user_id=user_id, deserialize=False)
        if data is None:
            return None
        data = dict(data)
        sd = json.loads(data["session_data"]) if isinstance(data.get("session_data"), str) else (data.get("session_data") or {})
        sd["session_name"] = session_name
        with self._tx() as conn:
            conn.execute(
                f"UPDATE {self.session_table_name} SET session_data=?, updated_at=? WHERE session_id=?",
                (json.dumps(sd), int(time.time()), session_id),
            )
        if not deserialize:
            data["session_data"] = sd
            return data
        return deserialize_session(session_type, data)

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        sd = session.to_dict()
        if isinstance(session, AgentSession):
            sd["session_type"] = SessionType.AGENT.value
        elif isinstance(session, TeamSession):
            sd["session_type"] = SessionType.TEAM.value
        elif isinstance(session, WorkflowSession):
            sd["session_type"] = SessionType.WORKFLOW.value

        now = int(time.time())
        sd["created_at"] = sd.get("created_at", now)
        sd["updated_at"] = now

        session_data = sd.pop("session_data", None)
        if isinstance(session_data, dict):
            session_data = json.dumps(session_data)

        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.session_table_name}
                (session_id, user_id, agent_id, team_id, workflow_id,
                 session_type, session_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sd.get("session_id", str(uuid4())), sd.get("user_id"),
                    sd.get("agent_id"), sd.get("team_id"), sd.get("workflow_id"),
                    sd.get("session_type"), session_data,
                    sd.get("created_at"), sd.get("updated_at"),
                ),
            )
        if not deserialize:
            return sd
        return session

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[Session, Dict[str, Any]]]:
        return [self.upsert_session(s, deserialize=deserialize) for s in sessions if s is not None]

    # ==================================================================
    # KNOWLEDGE, EVAL, TRACE, SPAN, CULTURE, LEARNING — SQLite
    # ==================================================================

    def delete_knowledge_content(self, id: str) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.knowledge_table_name} WHERE id=?", (id,))

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        conn = self._get_conn()
        row = conn.execute(f"SELECT * FROM {self.knowledge_table_name} WHERE id=?", (id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        return KnowledgeRow(
            id=data["id"], name=data.get("name") or "",
            description=data.get("description"), content=data.get("content"),
            metadata=json.loads(data["metadata"]) if data.get("metadata") else None,
            linked_to=data.get("linked_to"),
            created_at=data.get("created_at"), updated_at=data.get("updated_at"),
        )

    def get_knowledge_contents(
        self, limit: Optional[int] = None, page: Optional[int] = None,
        sort_by: Optional[str] = None, sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.knowledge_table_name} WHERE 1=1"
        params: list = []
        if linked_to:
            query += " AND linked_to=?"
            params.append(linked_to)
        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]
        query += " ORDER BY created_at DESC"
        if limit:
            offset = ((page or 1) - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            results.append(KnowledgeRow(
                id=data["id"], name=data.get("name") or "",
                description=data.get("description"), content=data.get("content"),
                metadata=json.loads(data["metadata"]) if data.get("metadata") else None,
                linked_to=data.get("linked_to"),
                created_at=data.get("created_at"), updated_at=data.get("updated_at"),
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
                    knowledge_row.id or str(uuid4()), knowledge_row.name,
                    knowledge_row.description, knowledge_row.content,
                    json.dumps(knowledge_row.metadata) if knowledge_row.metadata else None,
                    knowledge_row.linked_to,
                    knowledge_row.created_at or now, knowledge_row.updated_at or now,
                ),
            )
        return knowledge_row

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
                    now, now,
                ),
            )
        return eval_run

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        if not eval_run_ids:
            return
        with self._tx() as conn:
            placeholders = ",".join("?" * len(eval_run_ids))
            conn.execute(f"DELETE FROM {self.eval_table_name} WHERE eval_run_id IN ({placeholders})", eval_run_ids)

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        conn = self._get_conn()
        row = conn.execute(f"SELECT * FROM {self.eval_table_name} WHERE eval_run_id=?", (eval_run_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if deserialize:
            return EvalRunRecord.from_dict(data)
        return data

    def get_eval_runs(
        self, limit: Optional[int] = None, page: Optional[int] = None,
        sort_by: Optional[str] = None, sort_order: Optional[str] = None,
        agent_id: Optional[str] = None, team_id: Optional[str] = None,
        workflow_id: Optional[str] = None, model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_type: Optional[List[EvalType]] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.eval_table_name} WHERE 1=1"
        params: list = []
        for col, val in [("agent_id", agent_id), ("team_id", team_id), ("workflow_id", workflow_id), ("model_id", model_id)]:
            if val:
                query += f" AND {col}=?"
                params.append(val)
        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]
        query += " ORDER BY created_at DESC"
        if limit:
            offset = ((page or 1) - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"
        rows = conn.execute(query, params).fetchall()
        results = [EvalRunRecord.from_dict(dict(r)) if deserialize else dict(r) for r in rows]
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

    def upsert_trace(self, trace: "Trace") -> None:
        now = int(time.time() * 1000)
        with self._tx() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.trace_table_name} (trace_id, run_id, data, created_at) VALUES (?, ?, ?, ?)",
                (trace.trace_id, getattr(trace, "run_id", None), json.dumps(trace.to_dict()), now),
            )

    def get_trace(self, trace_id: Optional[str] = None, run_id: Optional[str] = None):
        conn = self._get_conn()
        row = None
        if trace_id:
            row = conn.execute(f"SELECT * FROM {self.trace_table_name} WHERE trace_id=?", (trace_id,)).fetchone()
        elif run_id:
            row = conn.execute(f"SELECT * FROM {self.trace_table_name} WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("data"):
            data["data"] = json.loads(data["data"])
        return data

    def get_traces(
        self, run_id: Optional[str] = None, session_id: Optional[str] = None,
        user_id: Optional[str] = None, agent_id: Optional[str] = None,
        team_id: Optional[str] = None, workflow_id: Optional[str] = None,
        status: Optional[str] = None, start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None, limit: Optional[int] = 20,
        page: Optional[int] = 1, filter_expr: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.trace_table_name} WHERE 1=1"
        params: list = []
        if run_id:
            query += " AND run_id=?"
            params.append(run_id)
        total = conn.execute(query.replace("SELECT *", "SELECT COUNT(*) as cnt"), params).fetchone()["cnt"]
        query += " ORDER BY created_at DESC"
        if limit:
            offset = ((page or 1) - 1) * limit
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
        self, user_id: Optional[str] = None, agent_id: Optional[str] = None,
        team_id: Optional[str] = None, workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None, end_time: Optional[datetime] = None,
        limit: Optional[int] = 20, page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        return [], 0

    def create_span(self, span: "Span") -> None:
        now = int(time.time() * 1000)
        with self._tx() as conn:
            conn.execute(
                f"INSERT INTO {self.span_table_name} (span_id, trace_id, data, created_at) VALUES (?, ?, ?, ?)",
                (span.span_id, span.trace_id, json.dumps(span.to_dict()), now),
            )

    def create_spans(self, spans: List) -> None:
        for span in spans:
            self.create_span(span)

    def get_span(self, span_id: str):
        conn = self._get_conn()
        row = conn.execute(f"SELECT * FROM {self.span_table_name} WHERE span_id=?", (span_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("data"):
            data["data"] = json.loads(data["data"])
        return data

    def get_spans(
        self, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> List:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.span_table_name} WHERE 1=1"
        params: list = []
        if trace_id:
            query += " AND trace_id=?"
            params.append(trace_id)
        query += " ORDER BY created_at ASC"
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_metrics(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        return [], None

    def calculate_metrics(self) -> Optional[Any]:
        return None

    def clear_cultural_knowledge(self) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.culture_table_name}")

    def delete_cultural_knowledge(self, id: str) -> None:
        with self._tx() as conn:
            conn.execute(f"DELETE FROM {self.culture_table_name} WHERE id=?", (id,))

    def get_cultural_knowledge(self, id: str) -> Optional[CulturalKnowledge]:
        conn = self._get_conn()
        row = conn.execute(f"SELECT * FROM {self.culture_table_name} WHERE id=?", (id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if data.get("data"):
            data["data"] = json.loads(data["data"])
        return CulturalKnowledge.from_dict(data)

    def get_all_cultural_knowledge(
        self, name: Optional[str] = None, limit: Optional[int] = None,
        page: Optional[int] = None, sort_by: Optional[str] = None,
        sort_order: Optional[str] = None, agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[List[CulturalKnowledge]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.culture_table_name}"
        if limit:
            offset = ((page or 1) - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"
        rows = conn.execute(query).fetchall()
        return [CulturalKnowledge.from_dict(dict(r)) for r in rows]

    def upsert_cultural_knowledge(self, cultural_knowledge: CulturalKnowledge) -> Optional[CulturalKnowledge]:
        now = int(time.time())
        data_dict = cultural_knowledge.to_dict() if hasattr(cultural_knowledge, "to_dict") else {}
        with self._tx() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.culture_table_name} (id, data, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cultural_knowledge.id or str(uuid4()), json.dumps(data_dict), now, now),
            )
        return cultural_knowledge

    def get_learning(
        self, learning_type: str, user_id: Optional[str] = None,
        agent_id: Optional[str] = None, team_id: Optional[str] = None,
        session_id: Optional[str] = None, namespace: Optional[str] = None,
        entity_id: Optional[str] = None, entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.learnings_table_name} WHERE learning_type=?"
        params: list = [learning_type]
        for col, val in [("user_id", user_id), ("agent_id", agent_id), ("team_id", team_id),
                          ("session_id", session_id), ("namespace", namespace),
                          ("entity_id", entity_id), ("entity_type", entity_type)]:
            if val:
                query += f" AND {col}=?"
                params.append(val)
        query += " ORDER BY updated_at DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        data = dict(row)
        for k in ("content", "metadata"):
            if data.get(k):
                data[k] = json.loads(data[k])
        return data

    def upsert_learning(
        self, id: str, learning_type: str, content: Dict[str, Any],
        user_id: Optional[str] = None, agent_id: Optional[str] = None,
        team_id: Optional[str] = None, session_id: Optional[str] = None,
        namespace: Optional[str] = None, entity_id: Optional[str] = None,
        entity_type: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = int(time.time())
        with self._tx() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.learnings_table_name}
                (id, learning_type, content, user_id, agent_id, team_id, session_id,
                 namespace, entity_id, entity_type, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (id, learning_type, json.dumps(content),
                 user_id, agent_id, team_id, session_id,
                 namespace, entity_id, entity_type,
                 json.dumps(metadata) if metadata else None, now, now),
            )

    def delete_learning(self, id: str) -> bool:
        with self._tx() as conn:
            cur = conn.execute(f"DELETE FROM {self.learnings_table_name} WHERE id=?", (id,))
            return cur.rowcount > 0

    def get_learnings(
        self, learning_type: Optional[str] = None, user_id: Optional[str] = None,
        agent_id: Optional[str] = None, team_id: Optional[str] = None,
        session_id: Optional[str] = None, namespace: Optional[str] = None,
        entity_id: Optional[str] = None, entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        query = f"SELECT * FROM {self.learnings_table_name} WHERE 1=1"
        params: list = []
        for col, val in [("learning_type", learning_type), ("user_id", user_id),
                          ("agent_id", agent_id), ("team_id", team_id),
                          ("session_id", session_id), ("namespace", namespace),
                          ("entity_id", entity_id), ("entity_type", entity_type)]:
            if val:
                query += f" AND {col}=?"
                params.append(val)
        query += " ORDER BY updated_at DESC"
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            for k in ("content", "metadata"):
                if data.get(k):
                    data[k] = json.loads(data[k])
            results.append(data)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _entity_to_memory(
        self, entity: Dict[str, Any], deserialize: bool = True
    ) -> Union[UserMemory, Dict[str, Any], None]:
        """Convert a Mimir entity to an Agno UserMemory."""
        body = entity.get("body_json", "{}")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return None

        topics = body.get("topics", [])
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except json.JSONDecodeError:
                topics = []

        data = {
            "memory_id": body.get("memory_id") or entity.get("key"),
            "memory": body.get("memory", ""),
            "topics": topics,
            "input": body.get("input"),
            "user_id": body.get("user_id"),
            "agent_id": body.get("agent_id"),
            "team_id": body.get("team_id"),
            "feedback": body.get("feedback"),
            "created_at": body.get("created_at"),
            "updated_at": body.get("updated_at"),
        }

        if not deserialize:
            return data

        return UserMemory(**data)

    def _row_to_memory(
        self, data: Dict[str, Any], deserialize: bool = True
    ) -> Union[UserMemory, Dict[str, Any]]:
        if isinstance(data.get("topics"), str):
            try:
                data["topics"] = json.loads(data["topics"])
            except (json.JSONDecodeError, TypeError):
                data["topics"] = []
        if not deserialize:
            return data
        return UserMemory(**{k: v for k, v in data.items() if v is not None or k == "memory"})

    def _row_to_memory_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
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
            "mimir_binary": self._mimir_binary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MimirDb":
        return cls(
            db_path=data.get("db_path"),
            mimir_binary=data.get("mimir_binary"),
            session_table=data.get("session_table"),
            memory_table=data.get("memory_table"),
            id=data.get("id"),
        )
