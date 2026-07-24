"""DbFileSystem — the database backend for AgentFS (Postgres + SQLite).

Standalone storage component in the VectorDb family: ``db_url``/``db_engine``
constructor, owns its ``Table``, creates it lazily on first use. Deliberately
not on the ``BaseDb`` contract — AgentFS is a pure tool component, not platform
state. Natively full: every operation is implemented, append and move are
atomic, and rows are versioned.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional, Sequence, Set

from agno.fs._paths import build_chunk, path_sort_key
from agno.fs.base import FileSystem, _extract_snippet
from agno.fs.errors import QuotaExceededError, VersionConflictError
from agno.fs.types import FileMeta, NamespaceUsage, SearchMatch
from agno.utils.log import log_debug

try:
    from sqlalchemy import (
        BigInteger,
        Column,
        MetaData,
        String,
        Table,
        Text,
        and_,
        case,
        delete,
        func,
        literal,
        or_,
        true,
        update,
    )
    from sqlalchemy import text as sql_text
    from sqlalchemy.engine import Engine, create_engine, make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.sql import select
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install 'agno[sql]'`")

SUPPORTED_DIALECTS = ("postgresql", "sqlite")


class DbFileSystem(FileSystem):
    """Database-backed file storage: one row per ``(namespace_id, path)``.

    Safe for multi-worker deployments — all coordination happens in the
    database: writes are atomic upserts (last-writer-wins, or CAS via
    ``expected_version``), appends serialize on the row lock behind a guarded
    upsert that enforces the per-file cap in the same statement, and moves are
    a single UPDATE. SQLite is for dev, Postgres for production.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        *,
        table_name: str = "agno_agent_fs",
        db_schema: Optional[str] = "ai",
    ) -> None:
        if db_engine is None and db_url is None:
            raise ValueError("One of db_url or db_engine must be provided")
        if db_engine is not None:
            self.db_engine: Engine = db_engine
        else:
            backend_name = make_url(db_url).get_backend_name()  # type: ignore[arg-type]
            if backend_name not in SUPPORTED_DIALECTS:
                raise ValueError(
                    f"DbFileSystem supports dialects {SUPPORTED_DIALECTS}, got {backend_name!r}. "
                    "Use a postgresql or sqlite db_url/db_engine."
                )
            self.db_engine = create_engine(db_url)  # type: ignore[arg-type]
        self.dialect: str = self.db_engine.dialect.name
        if self.dialect not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"DbFileSystem supports dialects {SUPPORTED_DIALECTS}, got {self.dialect!r}. "
                "Use a postgresql or sqlite db_url/db_engine."
            )
        self.table_name = table_name
        self.db_schema = db_schema if self.dialect == "postgresql" else None
        self.metadata = MetaData(schema=self.db_schema)
        self.table = Table(
            self.table_name,
            self.metadata,
            Column("namespace_id", String, primary_key=True),
            Column("path", String, primary_key=True),
            Column("content", Text, nullable=False),
            Column("size_bytes", BigInteger, nullable=False),
            Column("version", BigInteger, nullable=False),
            Column("created_at", BigInteger, nullable=False),
            Column("updated_at", BigInteger, nullable=True),
        )
        self._table_ready = False
        self._table_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        if self._table_ready:
            return
        with self._table_lock:
            if self._table_ready:
                return
            if self.db_schema is not None:
                with self.db_engine.begin() as conn:
                    conn.execute(sql_text(f'CREATE SCHEMA IF NOT EXISTS "{self.db_schema}"'))
            self.metadata.create_all(self.db_engine, tables=[self.table], checkfirst=True)
            log_debug(f"DbFileSystem table ready: {self.table.fullname}")
            self._table_ready = True

    def _insert(self):
        if self.dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            return pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert

    def _directory_predicate(self, directory: str):
        t = self.table
        if not directory:
            return true()
        # Segment-boundary matching; autoescape is load-bearing — % and _ are
        # legal in segments, and an unescaped LIKE turns them into wildcards.
        return or_(t.c.path == directory, t.c.path.startswith(directory + "/", autoescape=True))

    def _tail_expression(self):
        t = self.table
        if self.dialect == "postgresql":
            return func.right(t.c.content, 1)
        return func.substr(t.c.content, -1)

    # ------------------------------------------------------------------
    # Required core
    # ------------------------------------------------------------------

    def read(self, namespace: str, path: str) -> Optional[str]:
        self._ensure_table()
        t = self.table
        with self.db_engine.begin() as conn:
            row = conn.execute(select(t.c.content).where(and_(t.c.namespace_id == namespace, t.c.path == path))).first()
        return None if row is None else row[0]

    def write(self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None) -> FileMeta:
        self._ensure_table()
        t = self.table
        now = int(time.time())
        size_bytes = len(content.encode("utf-8"))
        if expected_version is not None:
            stmt = (
                update(t)
                .where(and_(t.c.namespace_id == namespace, t.c.path == path, t.c.version == expected_version))
                .values(content=content, size_bytes=size_bytes, version=t.c.version + 1, updated_at=now)
                .returning(t.c.version, t.c.size_bytes)
            )
            with self.db_engine.begin() as conn:
                row = conn.execute(stmt).first()
                if row is None:
                    actual = conn.execute(
                        select(t.c.version).where(and_(t.c.namespace_id == namespace, t.c.path == path))
                    ).scalar()
                    raise VersionConflictError(
                        f"version conflict on {path}: expected {expected_version}, actual {actual}",
                        expected=expected_version,
                        actual=actual,
                    )
            return FileMeta(path=path, size_bytes=row[1], version=row[0], updated_at=now)
        insert = self._insert()
        stmt = insert(t).values(
            namespace_id=namespace,
            path=path,
            content=content,
            size_bytes=size_bytes,
            version=1,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[t.c.namespace_id, t.c.path],
            set_={
                "content": stmt.excluded.content,
                "size_bytes": stmt.excluded.size_bytes,
                "version": t.c.version + 1,
                "updated_at": now,
            },
        ).returning(t.c.version, t.c.size_bytes)
        with self.db_engine.begin() as conn:
            row = conn.execute(stmt).first()
        return FileMeta(path=path, size_bytes=row[1], version=row[0], updated_at=now)  # type: ignore[index]

    def list(self, namespace: str, directory: str = "") -> List[FileMeta]:
        self._ensure_table()
        t = self.table
        stmt = select(t.c.path, t.c.size_bytes, t.c.version, t.c.updated_at).where(
            and_(t.c.namespace_id == namespace, self._directory_predicate(directory))
        )
        with self.db_engine.begin() as conn:
            rows = conn.execute(stmt).all()
        return [FileMeta(path=r[0], size_bytes=r[1], version=r[2], updated_at=r[3]) for r in rows]

    def delete(self, namespace: str, path: str) -> bool:
        self._ensure_table()
        t = self.table
        with self.db_engine.begin() as conn:
            result = conn.execute(delete(t).where(and_(t.c.namespace_id == namespace, t.c.path == path)))
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # Native implementations
    # ------------------------------------------------------------------

    def _stat(self, namespace: str, path: str) -> Optional[FileMeta]:
        self._ensure_table()
        t = self.table
        with self.db_engine.begin() as conn:
            row = conn.execute(
                select(t.c.size_bytes, t.c.version, t.c.updated_at).where(
                    and_(t.c.namespace_id == namespace, t.c.path == path)
                )
            ).first()
        if row is None:
            return None
        return FileMeta(path=path, size_bytes=row[0], version=row[1], updated_at=row[2])

    def append(self, namespace: str, path: str, content: str, *, max_file_bytes: Optional[int] = None) -> FileMeta:
        """Guarded atomic append: one upsert enforces the per-file cap and appends.

        Concurrent appends serialize on the row lock; all land; none lost. The
        guard is detected via ``RETURNING`` — never ``result.rowcount``, which is
        ``-1`` on psycopg3 for a guarded upsert whether it blocked or not.
        """
        self._ensure_table()
        chunk = build_chunk(content)
        if not chunk:
            existing = self._stat(namespace, path)
            if existing is not None:
                return existing
            return FileMeta(path=path, size_bytes=0, version=None, updated_at=None)
        chunk_bytes = len(chunk.encode("utf-8"))
        # New-file inserts take the VALUES arm, which the WHERE guard does not
        # cover — pre-check the chunk alone client-side (exact: content is fully known).
        if max_file_bytes is not None and chunk_bytes > max_file_bytes:
            raise QuotaExceededError(
                f"{path} would be {chunk_bytes} bytes (limit {max_file_bytes} per file)",
                scope="file",
                current=chunk_bytes,
                limit=max_file_bytes,
            )
        t = self.table
        now = int(time.time())
        tail = self._tail_expression()
        # The content != '' arm is load-bearing: without it every new-from-empty
        # file starts with a blank line while size_bytes stays exact.
        needs_sep = and_(t.c.content != "", tail != "\n")
        sep = case((needs_sep, literal("\n")), else_=literal(""))
        sep_len = case((needs_sep, literal(1)), else_=literal(0))

        insert = self._insert()
        stmt = insert(t).values(
            namespace_id=namespace,
            path=path,
            content=chunk,
            size_bytes=chunk_bytes,
            version=1,
            created_at=now,
            updated_at=now,
        )
        new_size = t.c.size_bytes + sep_len + stmt.excluded.size_bytes
        set_ = {
            "content": t.c.content + sep + stmt.excluded.content,
            "size_bytes": new_size,
            "version": t.c.version + 1,
            "updated_at": now,
        }
        if max_file_bytes is not None:
            stmt = stmt.on_conflict_do_update(
                index_elements=[t.c.namespace_id, t.c.path], set_=set_, where=(new_size <= max_file_bytes)
            )
        else:
            stmt = stmt.on_conflict_do_update(index_elements=[t.c.namespace_id, t.c.path], set_=set_)
        stmt = stmt.returning(t.c.version, t.c.size_bytes)

        with self.db_engine.begin() as conn:
            row = conn.execute(stmt).first()
            if row is None:
                # Guard blocked the update. Fetch the current tail to report the
                # exact size the file would have reached.
                blocked = conn.execute(
                    select(t.c.size_bytes, tail).where(and_(t.c.namespace_id == namespace, t.c.path == path))
                ).first()
                if blocked is not None:
                    separator_len = 1 if blocked[0] > 0 and blocked[1] != "\n" else 0
                    would_be = blocked[0] + separator_len + chunk_bytes
                else:
                    would_be = chunk_bytes
                raise QuotaExceededError(
                    f"{path} would be {would_be} bytes (limit {max_file_bytes} per file)",
                    scope="file",
                    current=would_be,
                    limit=max_file_bytes if max_file_bytes is not None else 0,
                )
        return FileMeta(path=path, size_bytes=row[1], version=row[0], updated_at=now)

    def move(self, namespace: str, src: str, dst: str, *, overwrite: bool = False) -> FileMeta:
        """Atomic move: a single UPDATE of ``path``. A destination collision
        surfaces as ``IntegrityError`` inside a SAVEPOINT (so the transaction is
        not poisoned on Postgres) and re-raises as ``FileExistsError``."""
        self._ensure_table()
        t = self.table
        now = int(time.time())
        stmt = (
            update(t)
            .where(and_(t.c.namespace_id == namespace, t.c.path == src))
            .values(path=dst, version=t.c.version + 1, updated_at=now)
            .returning(t.c.version, t.c.size_bytes)
        )
        with self.db_engine.begin() as conn:
            if overwrite and src != dst:
                conn.execute(delete(t).where(and_(t.c.namespace_id == namespace, t.c.path == dst)))
            try:
                with conn.begin_nested():
                    row = conn.execute(stmt).first()
            except IntegrityError:
                raise FileExistsError(f"file exists: {dst}") from None
            if row is None:
                raise FileNotFoundError(f"file not found: {src}")
        return FileMeta(path=dst, size_bytes=row[1], version=row[0], updated_at=now)

    def contains(self, namespace: str, lines: Sequence[str], directory: str = "") -> Set[str]:
        """Exact-line membership via the padded LIKE predicate as a row prefilter,
        with Python owning the final per-line attribution (byte-exact, and always
        in agreement with the base emulation)."""
        self._ensure_table()
        remaining = set(lines)
        found: Set[str] = set()
        if not remaining:
            return found
        t = self.table
        padded = literal("\n") + t.c.content + literal("\n")
        line_predicates = [padded.contains("\n" + line + "\n", autoescape=True) for line in lines]
        stmt = select(t.c.content).where(
            and_(t.c.namespace_id == namespace, self._directory_predicate(directory), or_(*line_predicates))
        )
        with self.db_engine.begin() as conn:
            rows = conn.execute(stmt)
            for row in rows:
                hit = remaining & set(row[0].split("\n"))
                found |= hit
                remaining -= hit
                if not remaining:
                    break
        return found

    def search(self, namespace: str, query: str, directory: str = "", limit: int = 10) -> List[SearchMatch]:
        """Case-insensitive substring search. Correctness is owned by Python; on
        Postgres ILIKE prefilters candidate rows, on SQLite every in-scope row is
        scanned (SQLite's LIKE folds ASCII only, which would miss non-ASCII case
        variants)."""
        self._ensure_table()
        if not query:
            return []
        t = self.table
        conditions = [t.c.namespace_id == namespace, self._directory_predicate(directory)]
        if self.dialect == "postgresql":
            conditions.append(t.c.content.icontains(query, autoescape=True))
        stmt = select(t.c.path, t.c.size_bytes, t.c.content).where(and_(*conditions))
        with self.db_engine.begin() as conn:
            rows = conn.execute(stmt).all()
        lower_query = query.lower()
        matches: List[SearchMatch] = []
        for row in sorted(rows, key=lambda r: path_sort_key(r[0])):
            if len(matches) >= limit:
                break
            if lower_query in row[2].lower():
                matches.append(SearchMatch(path=row[0], size_bytes=row[1], snippet=_extract_snippet(row[2], query)))
        return matches

    def usage(self, namespace: str) -> NamespaceUsage:
        self._ensure_table()
        t = self.table
        stmt = select(func.count(), func.coalesce(func.sum(t.c.size_bytes), 0)).where(t.c.namespace_id == namespace)
        with self.db_engine.begin() as conn:
            row = conn.execute(stmt).one()
        return NamespaceUsage(file_count=row[0], total_bytes=row[1])
