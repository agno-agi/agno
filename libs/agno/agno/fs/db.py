"""DbFileSystem — the database backend for FileSystem (Postgres + SQLite).

Standalone storage component in the VectorDb family: takes an existing agno
``db`` (``SqliteDb``/``PostgresDb``) or a raw ``db_url``/``db_engine``, owns its
``Table``, creates it lazily on first use. Deliberately
not on the ``BaseDb`` contract — FileSystem is a pure tool component, not platform
state. Natively full: every operation is implemented, append and move are
atomic, and rows are versioned.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Set

from agno.fs._paths import build_chunk, path_sort_key
from agno.fs.base import BaseFS, _extract_snippet
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
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sql_text
    from sqlalchemy.engine import Engine, create_engine, make_url
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
    from sqlalchemy.sql import select
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install 'agno[sql]'`")

if TYPE_CHECKING:
    from agno.db.base import BaseDb

SUPPORTED_DIALECTS = ("postgresql", "sqlite")

# Distinguishes "caller did not specify a schema" from an explicit None or "ai".
_INHERIT_SCHEMA: Any = object()


class DbFileSystem(BaseFS):
    """Database-backed file storage: one row per ``(namespace_id, path)``.

    Safe for multi-worker deployments — all coordination happens in the
    database: writes are atomic upserts (last-writer-wins, or CAS via
    ``expected_version``), appends serialize on the row lock behind a guarded
    upsert that enforces the per-file cap in the same statement, and moves are
    a single UPDATE. SQLite is for dev, Postgres for production.
    """

    def __init__(
        self,
        db: Optional[BaseDb] = None,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        *,
        table_name: str = "agno_agent_fs",
        db_schema: Optional[str] = _INHERIT_SCHEMA,
    ) -> None:
        provided = [source for source in (db, db_url, db_engine) if source is not None]
        if len(provided) != 1:
            raise ValueError("Provide exactly one of db, db_url, or db_engine")
        if db is not None:
            # Reuse the engine of an agno db the caller already configured, so the
            # agent's files live beside its sessions and memory with one connection
            # setup. The engine and (unless overridden) the schema are borrowed;
            # nothing is added to the BaseDb contract. Not every
            # agno db is SQL-backed (Mongo, Redis, DynamoDb, ... have no engine), so
            # fail with a clear message rather than an AttributeError.
            borrowed = getattr(db, "db_engine", None)
            if borrowed is None:
                raise ValueError(
                    f"DbFileSystem needs a SQL-backed agno db, got {type(db).__name__} which has no db_engine. "
                    "Use SqliteDb or PostgresDb, or pass db_url/db_engine directly."
                )
            self.db_engine: Engine = borrowed
        elif db_engine is not None:
            self.db_engine = db_engine
        else:
            url = make_url(db_url)  # type: ignore[arg-type]
            backend_name = url.get_backend_name()
            if backend_name not in SUPPORTED_DIALECTS:
                raise ValueError(
                    f"DbFileSystem supports dialects {SUPPORTED_DIALECTS}, got {backend_name!r}. "
                    "Use a postgresql or sqlite db_url/db_engine."
                )
            # Create the parent directory for a sqlite file path — sqlite will not
            # create it and errors on connect. Matches SqliteDb (db/sqlite/sqlite.py),
            # so a `sqlite:///tmp/x.db` url just works without the caller pre-making tmp/.
            if backend_name == "sqlite" and url.database and url.database != ":memory:":
                Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
            self.db_engine = create_engine(db_url)  # type: ignore[arg-type]
        self.dialect: str = self.db_engine.dialect.name
        if self.dialect not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"DbFileSystem supports dialects {SUPPORTED_DIALECTS}, got {self.dialect!r}. "
                "Use a postgresql or sqlite db_url/db_engine."
            )
        if self.dialect == "sqlite":
            import sqlite3

            # The guarded append and CAS write detect outcomes via RETURNING,
            # which SQLite added in 3.35.0 — fail with a clear message instead
            # of an opaque CompileError on first write.
            if sqlite3.sqlite_version_info < (3, 35, 0):
                raise ValueError(
                    f"DbFileSystem requires SQLite >= 3.35.0 (RETURNING support); found {sqlite3.sqlite_version}."
                )
        self.table_name = table_name
        if db_schema is _INHERIT_SCHEMA:
            # Follow the db's own schema so the agent's files land beside its
            # sessions; "ai" is agno's default for both, so this only bites when
            # the caller customized theirs (PostgresDb(db_schema="myapp")).
            inherited = getattr(db, "db_schema", None) if db is not None else None
            db_schema = inherited or "ai"
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
            # CREATE SCHEMA IF NOT EXISTS and checkfirst are both check-then-create,
            # so instances in other threads, workers, or processes can race them on
            # first use. Losing the race is fine — verify the table exists and move on.
            try:
                if self.db_schema is not None:
                    with self.db_engine.begin() as conn:
                        conn.execute(sql_text(f'CREATE SCHEMA IF NOT EXISTS "{self.db_schema}"'))
                self.metadata.create_all(self.db_engine, tables=[self.table], checkfirst=True)
            except (IntegrityError, ProgrammingError, OperationalError):
                if not sa_inspect(self.db_engine).has_table(self.table_name, schema=self.db_schema):
                    raise
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
        # Segment-boundary matching by exact prefix comparison, NOT LIKE: SQLite's LIKE
        # case-folds ASCII while Postgres's does not, so a LIKE predicate would scope
        # differently on the two backends for the same data — and in the harmful
        # direction (dev silently treating a genuinely-new item as already-seen). substr
        # equality is case-sensitive and byte-exact on both, matching the == arm.
        prefix = directory + "/"
        return or_(t.c.path == directory, func.substr(t.c.path, 1, len(prefix)) == prefix)

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
        # cover — pre-check the chunk alone client-side (exact: content is fully
        # known). When the row already exists, fall through instead: the guarded
        # statement blocks and its error path reports the size the file would
        # actually have reached.
        if max_file_bytes is not None and chunk_bytes > max_file_bytes and self._stat(namespace, path) is None:
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
            try:
                # Both statements inside the one SAVEPOINT: the DELETE+UPDATE
                # pair is a single rollback unit on the overwrite path.
                with conn.begin_nested():
                    if overwrite and src != dst:
                        if self.dialect == "postgresql":
                            # Lock both rows in sorted order first: cyclic
                            # concurrent moves (a->b and b->a) would otherwise
                            # acquire the two row locks in opposite order and
                            # deadlock.
                            for locked_path in sorted((src, dst)):
                                conn.execute(
                                    select(t.c.path)
                                    .where(and_(t.c.namespace_id == namespace, t.c.path == locked_path))
                                    .with_for_update()
                                )
                        conn.execute(delete(t).where(and_(t.c.namespace_id == namespace, t.c.path == dst)))
                    row = conn.execute(stmt).first()
                    if row is None:
                        raise FileNotFoundError(f"file not found: {src}")
            except IntegrityError:
                raise FileExistsError(f"file exists: {dst}") from None
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
        # Postgres sum(bigint) returns Decimal; coerce so callers (and json.dumps in
        # list_files) always see plain ints, matching SQLite.
        return NamespaceUsage(file_count=int(row[0]), total_bytes=int(row[1]))
