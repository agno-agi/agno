"""Coordinated catalog, filesystem and vector publication on PostgreSQL."""

from __future__ import annotations

import base64
import contextvars
import hashlib
import inspect
import json
import math
import re
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import closing, contextmanager, nullcontext
from threading import BoundedSemaphore
from typing import Any, Callable, Dict, List, Optional, Tuple, cast
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
    and_,
    delete,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from agno.db.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.fs.errors import QuotaExceededError
from agno.knowledge.chunking.page import PageMarkdownChunking
from agno.knowledge.document import Document
from agno.knowledge.page._source import PageSource, SourcePage, page_path, page_prefix
from agno.knowledge.page.types import (
    GrepMatch,
    GrepResult,
    Page,
    PageChanged,
    PageError,
    PageList,
    PageNotFound,
    PageRead,
    PageSearchConfig,
    SearchHit,
    SearchResult,
    SearchUnavailable,
    SyncFailed,
    SyncReport,
    encoded_size,
)
from agno.utils.bounded import BoundedWorkers, WorkBudget
from agno.utils.log import log_warning
from agno.vectordb.pgvector import PgVector
from agno.vectordb.pgvector.index import HNSW

READ_WORKERS = BoundedWorkers(8, "knowledge-read")
SYNC_WORKERS = BoundedWorkers(2, "knowledge-sync")
MAX_JSON_BYTES = 24_000
MAX_SEARCH_JSON_BYTES = 32_000
# At most two searches may fan out, so readers doing serial work can always
# release connections back to the eight-connection pool while children wait.
_PARALLEL_SEARCHES = BoundedSemaphore(2)
_QUERY_WORKERS = ThreadPoolExecutor(max_workers=6, thread_name_prefix="knowledge-query")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identifier(value: Optional[str]) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value):
        raise ValueError("invalid_page_storage_identifier")
    return '"' + value + '"'


class PageCoordinator:
    def __init__(self, knowledge: Any):
        self.knowledge = knowledge
        self.db = knowledge.contents_db
        self.fs = knowledge.page_store
        self.vector = knowledge.vector_db
        if knowledge.page_search is not None and not isinstance(knowledge.page_search, PageSearchConfig):
            raise ValueError("page_search must be a PageSearchConfig")
        self.search_config = knowledge.page_search or PageSearchConfig()
        if not isinstance(self.db, PostgresDb) or not isinstance(self.fs, FileSystem):
            raise ValueError("page_store requires FileSystem and synchronous PostgresDb contents_db")
        if not isinstance(self.fs.backend, DbFileSystem) or self.fs.backend.dialect != "postgresql":
            raise ValueError("page_store requires PostgreSQL DbFileSystem")
        if not isinstance(self.vector, PgVector):
            raise ValueError("page_store requires PgVector")
        if self.fs.is_templated:
            raise ValueError("page_store requires a resolved shared namespace")
        self.backend = self.fs.backend
        self.namespace = self.fs.namespace
        if knowledge.name is None:
            knowledge.name = self.namespace
        self.engine = getattr(knowledge, "_page_engine", self.db.db_engine)
        for engine in (self.backend.db_engine, self.vector.db_engine):
            if engine.dialect.name != "postgresql":
                raise ValueError("page storage adapters must use PostgreSQL")
            if engine.url.database != self.engine.url.database:
                raise ValueError("page storage adapters must share a logical database")
        for identifier in (
            self.db.db_schema,
            self.db.knowledge_table_name,
            self.backend.db_schema,
            self.backend.table_name,
            self.vector.schema,
            self.vector.table_name,
        ):
            _identifier(identifier)
        identities = {
            (self.db.db_schema, self.db.knowledge_table_name),
            (self.backend.db_schema, self.backend.table_name),
            (self.vector.schema, self.vector.table_name),
        }
        if len(identities) != 3:
            raise ValueError("page storage tables must be distinct")
        if self.vector.dimensions is None or not 1 <= self.vector.dimensions <= 2000:
            raise ValueError("page storage requires 1-2000 embedding dimensions for HNSW")
        from agno.knowledge.embedder.openai import OpenAIEmbedder

        if (
            not isinstance(self.vector.embedder, OpenAIEmbedder)
            and "timeout" not in inspect.signature(self.vector.embedder.get_embedding).parameters
        ):
            raise ValueError(
                "Page storage requires OpenAIEmbedder or an embedder accepting a transport timeout keyword"
            )
        self.binding = Table(
            self.backend.table_name + "_knowledge",
            MetaData(schema=self.backend.db_schema),
            Column("namespace", String, primary_key=True),
            Column("catalog", String, nullable=False),
            Column("vectors", String, nullable=False),
            Column("source", String),
            Column("revision", BigInteger, nullable=False, server_default="0"),
        )
        self.lock_key = int.from_bytes(
            hashlib.sha256((self.backend.table.fullname + ":" + self.namespace).encode()).digest()[:8],
            "big",
            signed=True,
        )
        self.catalog: Any = getattr(knowledge, "_page_catalog", None)
        self._pending_publication: Optional[Dict[str, Any]] = None

    def setup(self, *, budget: Optional[WorkBudget] = None) -> None:
        budget = budget or WorkBudget(60)
        from agno.db.postgres._bounded import bounded_engine

        if not hasattr(self.knowledge, "_page_engine"):
            self.knowledge._page_engine = bounded_engine(self.db.db_engine, capacity=8)
        self.engine = self.knowledge._page_engine
        identities = []
        for source_engine in (self.db.db_engine, self.backend.db_engine, self.vector.db_engine):
            engine = bounded_engine(source_engine, capacity=1)
            budget.remaining()
            with engine.connect() as conn:
                identities.append(
                    tuple(
                        conn.execute(
                            text("SELECT current_database(), inet_server_addr()::text, inet_server_port()")
                        ).one()
                    )
                )
            engine.dispose()
        if len(set(identities)) != 1:
            raise ValueError("page storage adapters must share a logical database")
        from copy import copy

        from sqlalchemy.orm import sessionmaker

        setup_db, setup_fs, setup_vector = copy(self.db), copy(self.backend), copy(self.vector)
        for adapter in (setup_db, setup_fs, setup_vector):
            adapter.db_engine = self.engine
        setup_db.Session = sessionmaker(bind=self.engine)
        setup_vector.Session = sessionmaker(bind=self.engine)
        self.catalog = setup_db._get_table(table_type="knowledge")
        with self.engine.begin() as conn:
            self._settings(conn, budget)
            if not self._setup_complete(conn):
                # Serialize first-time table/index creation independently of long
                # namespace refreshes. Initialized startups take the read-only path.
                setup_key = int.from_bytes(hashlib.sha256(b"agno.page.setup").digest()[:8], "big", signed=True)
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": setup_key})
                self.catalog = setup_db._get_table(table_type="knowledge")
                if not self._setup_complete(conn):
                    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": self.lock_key})
                    self.catalog = setup_db._get_table(table_type="knowledge", create_table_if_not_found=True)
                    budget.remaining()
                    setup_fs._ensure_table()
                    budget.remaining()
                    setup_vector.create()
                    self.binding.create(self.engine, checkfirst=True)
                    assert self.catalog is not None
                    conn.execute(
                        insert(self.binding)
                        .values(
                            namespace=self.namespace, catalog=self.catalog.fullname, vectors=self.vector.table.fullname
                        )
                        .on_conflict_do_nothing()
                    )
                    self._check_binding(conn)
                    conn.execute(
                        text(
                            f"ALTER TABLE {self._vector_name} ADD COLUMN IF NOT EXISTS _agno_page_tsv tsvector "
                            "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
                        )
                    )
                    for schema, name, table, definition in self._search_indexes():
                        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {_identifier(name)} ON {table} {definition}"))
                    if not self._setup_complete(conn):
                        raise ValueError("incomplete_page_search_schema")
        self.knowledge._page_catalog = self.catalog
        self.knowledge._page_ready = True

    def _check_binding(self, conn: Any) -> bool:
        binding = (
            conn.execute(select(self.binding).where(self.binding.c.namespace == self.namespace))
            .mappings()
            .one_or_none()
        )
        if binding is None:
            return False
        if binding["catalog"] != self.catalog.fullname or binding["vectors"] != self.vector.table.fullname:
            raise ValueError("filesystem namespace is bound to another knowledge catalog or vector table")
        return True

    @staticmethod
    def _normalized_definition(value: str) -> str:
        return "".join(value.lower().replace("::text", "").replace("(", "").replace(")", "").split())

    def _search_indexes(self):
        namespace_literal = str(
            literal(self.namespace).compile(dialect=self.engine.dialect, compile_kwargs={"literal_binds": True})
        )
        for suffix, definition in (
            ("page_gin", "USING gin (_agno_page_tsv)"),
            (
                "page_hnsw_" + self.namespace,
                "USING hnsw (embedding vector_cosine_ops) WHERE (meta_data->>'namespace') = " + namespace_literal,
            ),
        ):
            yield (
                self.vector.schema,
                "agno_" + _digest(self.vector.table.fullname + suffix)[:24],
                self._vector_name,
                definition,
            )
        yield (
            self.catalog.schema,
            "agno_" + _digest(self.catalog.fullname + "pages")[:24],
            _identifier(self.catalog.schema) + "." + _identifier(self.catalog.name),
            "((metadata->'_agno'->'page'->>'namespace'), (metadata->'_agno'->'page'->>'path'))",
        )

    def _setup_complete(self, conn: Any) -> bool:
        if self.catalog is None:
            return False
        for table in (self.catalog, self.backend.table, self.vector.table, self.binding):
            name = _identifier(table.schema) + "." + _identifier(table.name)
            if conn.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar_one() is None:
                return False
        if not self._check_binding(conn):
            return False
        column = (
            conn.execute(
                text(
                    "SELECT a.attgenerated, a.atttypid='tsvector'::regtype AS valid_type, "
                    "pg_get_expr(d.adbin, d.adrelid) AS expression FROM pg_attribute a "
                    "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                    "WHERE a.attrelid=to_regclass(:table) AND a.attname='_agno_page_tsv' AND NOT a.attisdropped"
                ),
                {"table": self._vector_name},
            )
            .mappings()
            .one_or_none()
        )
        if column is None:
            return False
        if (
            column["attgenerated"] != "s"
            or not column["valid_type"]
            or self._normalized_definition(column["expression"] or "")
            != self._normalized_definition("to_tsvector('english'::regconfig, content)")
        ):
            raise ValueError("incompatible_page_search_column")
        for schema, name, _, definition in self._search_indexes():
            row = (
                conn.execute(
                    text(
                        "SELECT pg_get_indexdef(i.indexrelid) AS definition, i.indisvalid AND i.indisready AS valid "
                        "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relname=:name"
                    ),
                    {"schema": schema, "name": name},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or not row["valid"]:
                return False
            if self._normalized_definition(definition) not in self._normalized_definition(row["definition"]):
                raise ValueError("incompatible_page_search_index")
        return True

    @property
    def _vector_name(self) -> str:
        return _identifier(self.vector.schema) + "." + _identifier(self.vector.table_name)

    def _ready(self) -> None:
        if not getattr(self.knowledge, "_page_ready", False) or self.catalog is None:
            raise ValueError("call Knowledge.setup() before serving or synchronizing pages")

    def _settings(self, conn: Any, budget: WorkBudget) -> None:
        timeout = max(1, int(min(budget.remaining(), 30) * 1000))
        conn.execute(
            text("SELECT set_config('statement_timeout', :timeout, true), set_config('lock_timeout', :timeout, true)"),
            {"timeout": str(timeout)},
        )

    @contextmanager
    def _snapshot(self, budget: Optional[WorkBudget] = None, *, snapshot: Optional[str] = None):
        from agno.db.postgres._bounded import optional_connection

        self._ready()
        with (
            optional_connection(budget or WorkBudget(2)) if snapshot is not None else nullcontext(),
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            ) as conn,
            conn.begin(),
        ):
            if snapshot is not None:
                # Import before any SELECT establishes this connection's snapshot.
                quoted = literal(snapshot).compile(dialect=self.engine.dialect, compile_kwargs={"literal_binds": True})
                conn.execute(text("SET TRANSACTION SNAPSHOT " + str(quoted)))
            self._settings(conn, budget or WorkBudget(2))
            yield conn

    def _predicate(self):
        return and_(
            self.catalog.c.type == "page",
            self._page_field("namespace") == self.namespace,
        )

    def _page_field(self, name: str):
        # Keep the expression identical to the published catalog index. JSONB
        # subscripting generated by newer SQLAlchemy versions cannot use it.
        page = self.catalog.c.metadata.op("->")(literal_column("'_agno'")).op("->")(literal_column("'page'"))
        return page.op("->>")(literal_column("'" + name + "'"))

    def _rows(
        self,
        conn: Any,
        *,
        prefix: str = "/",
        after: str = "",
        limit: int = 201,
        include_content: bool = True,
        literal_query: Optional[str] = None,
        ignore_case: bool = False,
        exact_path: bool = False,
        read_range: Optional[tuple[int, int]] = None,
    ):
        c, f = self.catalog, self.backend.table
        path = self._page_field("path")
        stmt = (
            select(
                c.c.metadata,
                f.c.content if include_content else (f.c.version.is_not(None)).label("content"),
                f.c.version,
            )
            .select_from(
                c.outerjoin(
                    f,
                    and_(
                        f.c.namespace == self.namespace,
                        f.c.path == func.substr(path, 2),
                    ),
                )
            )
            .where(self._predicate())
            .order_by(path)
            .limit(limit)
        )
        if exact_path:
            stmt = stmt.where(path == prefix)
        else:
            stmt = stmt.where(path > after, path >= prefix, func.starts_with(path, prefix))
        if read_range is not None:
            offset, max_chars = read_range
            # Slice before transferring the row: a short read must not fetch a
            # multi-megabyte body just to discard it in Python. PostgreSQL text
            # positions and public offsets both count Unicode code points.
            stmt = stmt.with_only_columns(
                c.c.metadata,
                func.substr(f.c.content, offset + 1, max_chars).label("content"),
                f.c.version,
                func.length(f.c.content).label("total_chars"),
            )
        if ignore_case:
            stmt = stmt.add_columns(func.lower(f.c.content).label("folded_content"))
        if literal_query is not None:
            # Filter in the bounded database statement before transferring bodies.
            # Drift must still reach _checked even when its changed text no longer matches.
            stmt = stmt.where(
                or_(
                    func.strpos(
                        func.lower(f.c.content) if ignore_case else f.c.content,
                        func.lower(literal_query) if ignore_case else literal_query,
                    )
                    > 0,
                    f.c.version.is_(None),
                    f.c.version != c.c.metadata["_agno"]["page"]["filesystem_version"].as_integer(),
                )
            )
        return conn.execute(stmt).all()

    def _checked(self, row: Any) -> tuple[Page, str]:
        page = Page.model_validate(row.metadata["_agno"]["page"])
        if row.content is None or row.version != page.filesystem_version:
            raise PageError()
        return page, row.content

    def _one(self, conn: Any, path: str) -> tuple[Page, str]:
        rows = self._rows(conn, prefix=path, limit=1, exact_path=True)
        if not rows or rows[0].metadata["_agno"]["page"]["path"] != path:
            raise PageNotFound()
        return self._checked(rows[0])

    def _page_id(self, path: str) -> str:
        return _digest(self.backend.table.fullname + ":" + self.namespace + ":" + path)

    def _fingerprint(self, version: str) -> str:
        embedder = self.vector.embedder
        return _digest(
            json.dumps(
                {
                    "model": getattr(embedder, "id", type(embedder).__name__),
                    "provider": type(embedder).__module__,
                    "dimensions": self.vector.dimensions,
                    "chunk_size": 2000,
                    "split_level": 2,
                    "normalization": "lf-v1",
                    "index_version": version,
                },
                sort_keys=True,
            )
        )

    def _embeddings(self, contents: List[str], budget: WorkBudget) -> List[List[float]]:
        embedder = self.vector.embedder
        # OpenAI-compatible clients support per-call transport deadlines without
        # mutating the shared embedder or its configured credentials.
        from agno.knowledge.embedder.openai import OpenAIEmbedder

        if isinstance(embedder, OpenAIEmbedder):
            embeddings: List[List[float]] = []
            for start in range(0, len(contents), min(100, max(1, embedder.batch_size))):
                client = embedder.client.with_options(timeout=min(30, budget.remaining()), max_retries=0)
                batch = contents[start : start + min(100, max(1, embedder.batch_size))]
                arguments = {
                    **(embedder.request_params or {}),
                    "input": batch,
                    "model": embedder.id,
                    "encoding_format": "float",
                }
                if embedder.id.startswith("text-embedding-3") or embedder.base_url is not None:
                    arguments["dimensions"] = self.vector.dimensions
                if embedder.user is not None:
                    arguments["user"] = embedder.user
                response = client.embeddings.create(**arguments)
                ordered = sorted(response.data, key=lambda item: item.index)
                if len(ordered) != len(batch) or [item.index for item in ordered] != list(range(len(batch))):
                    raise ValueError("invalid_page_embedding_batch")
                embeddings.extend(item.embedding for item in ordered)
        else:
            embeddings = []
            for content in contents:
                budget.remaining()
                embeddings.append(embedder.get_embedding(content, timeout=min(30, budget.remaining())))
        budget.remaining()
        if any(
            len(embedding) != self.vector.dimensions
            or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in embedding)
            for embedding in embeddings
        ):
            raise ValueError("invalid_page_embedding")
        return [list(embedding) for embedding in embeddings]

    def _embedding(self, content: str, budget: WorkBudget) -> List[float]:
        return self._embeddings([content], budget)[0]

    def _valid_vectors(self, conn: Any, page: Page) -> bool:
        v = self.vector.table
        rows = conn.execute(select(v.c.id, v.c.meta_data).where(v.c.content_id == page.content_id)).all()
        return (
            len(rows) == page.expected_chunk_count
            and all(
                row.meta_data.get("revision") == page.revision
                and row.meta_data.get("namespace") == self.namespace
                and row.meta_data.get("index_fingerprint") == page.index_fingerprint
                for row in rows
            )
            and {row.id for row in rows}
            == {_digest(page.content_id + ":" + str(index)) for index in range(page.expected_chunk_count)}
        )

    def _attempt(self, conn: Any, source: SourcePage, status: str) -> None:
        ident = self._page_id(source.path)
        old = conn.execute(select(self.catalog).where(self.catalog.c.id == ident)).mappings().first()
        row = (
            KnowledgeRow.model_validate(dict(old))
            if old
            else KnowledgeRow(
                id=ident,
                name=source.title,
                description="Documentation page",
                type="page",
                linked_to=self.knowledge.name,
                metadata={"_agno": {"source_url": source.url}},
                created_at=int(time.time()),
            )
        )
        row.status = status
        row.status_message = "page_sync_failed" if status == "failed" else None
        row.updated_at = int(time.time())
        self.db._upsert_knowledge_content_on(conn, self.catalog, row)

    def _source_attempt(self, conn: Any, source: PageSource, status: str, report: Optional[SyncReport] = None) -> None:
        ident = _digest(self.backend.table.fullname + ":" + self.namespace + ":source")
        old = conn.execute(select(self.catalog).where(self.catalog.c.id == ident)).mappings().first()
        row = (
            KnowledgeRow.model_validate(dict(old))
            if old
            else KnowledgeRow(
                id=ident,
                name=self.knowledge.name,
                description="Documentation source synchronization",
                type="source",
                linked_to=self.knowledge.name,
                created_at=int(time.time()),
            )
        )
        metadata = row.metadata or {}
        metadata["_agno"] = {**metadata.get("_agno", {}), "namespace": self.namespace, "source_url": source.url}
        if report is not None:
            metadata["_agno"]["sync"] = report.model_dump()
        row.metadata = metadata
        row.status = status
        row.status_message = "source_sync_failed" if status == "failed" else None
        row.updated_at = int(time.time())
        self.db._upsert_knowledge_content_on(conn, self.catalog, row)

    def _fetch_pages(self, source: PageSource, pages: Dict[str, SourcePage], transform: Any, budget: WorkBudget):
        """Keep at most eight page bodies in flight, without queuing the full index."""
        executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="knowledge-fetch")
        pending: Any = deque()
        remaining = iter(pages.values())

        def fetch(page: SourcePage) -> str:
            content = source.fetch(page.url, min(source.max_page_bytes, self.fs.max_file_bytes))
            if transform is not None:
                content = transform(content, path=page.path)
            budget.remaining()
            if not isinstance(content, str) or "\x00" in content:
                raise ValueError("invalid_page_text")
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            if len(content.encode("utf-8")) > min(source.max_page_bytes, self.fs.max_file_bytes):
                raise ValueError("page_size_limit")
            return content

        def submit() -> None:
            page = next(remaining, None)
            if page is not None:
                pending.append((page, executor.submit(fetch, page)))

        try:
            for _ in range(8):
                submit()
            while pending:
                page, future = pending.popleft()
                try:
                    content, error = future.result(timeout=budget.remaining()), None
                except Exception as exc:
                    content, error = None, exc
                yield page, content, error
                budget.remaining()
                submit()
        finally:
            for _, future in pending:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)

    def _embedding_pages(
        self,
        conn: Any,
        source: PageSource,
        pages: Any,
        transform: Any,
        fingerprint: str,
        budget: WorkBudget,
        reindex: bool,
    ):
        """Two embedding pages in flight; all database statements stay on the lock owner."""
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="knowledge-embed")
        pending: Any = deque()
        prepared: Optional[Dict[str, Any]] = None
        total_bytes = 0
        exhausted = False
        try:
            with closing(self._fetch_pages(source, pages, transform, budget)) as fetched:
                while pending or not exhausted:
                    while len(pending) < 2 and not exhausted:
                        try:
                            page, content, error = next(fetched)
                        except StopIteration:
                            exhausted = True
                            break
                        try:
                            if error is not None:
                                raise error
                            size = len(content.encode("utf-8"))
                            total_bytes += size
                            if total_bytes > min(256 * 1024 * 1024, self.fs.max_namespace_bytes):
                                raise QuotaExceededError(
                                    "page_storage_quota",
                                    scope="namespace",
                                    current=total_bytes,
                                    limit=self.fs.max_namespace_bytes,
                                )
                            prepared = self._prepare_page(conn, page, content, fingerprint, budget, reindex)
                            future = executor.submit(self._embed_page, page, content, fingerprint, budget, prepared)
                            pending.append((page, content, future, None))
                        except Exception as exc:
                            if conn.invalidated or conn.closed:
                                # Do not let an already prepared page reconnect after lock loss.
                                yield page, None, None, exc
                                return
                            pending.append((page, content, None, exc))
                    if pending:
                        page, content, future, error = pending.popleft()
                        try:
                            prepared = future.result(timeout=budget.remaining()) if future is not None else None
                        except Exception as exc:
                            prepared, error = None, exc
                        yield page, content, prepared, error
        finally:
            for _, _, future, _ in pending:
                if future is not None:
                    future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)

    def _prepare_page(
        self, conn: Any, source: SourcePage, content: str, fingerprint: str, budget: WorkBudget, reindex: bool
    ) -> Dict[str, Any]:
        digest = _digest(content)
        revision = _digest(digest + ":" + fingerprint)
        previous = None
        with conn.begin():
            self._settings(conn, budget)
            try:
                previous, old_text = self._one(conn, source.path)
                valid = (
                    previous.digest == digest
                    and previous.index_fingerprint == fingerprint
                    and old_text == content
                    and self._valid_vectors(conn, previous)
                )
            except PageError:
                valid = False
            if (
                valid
                and previous is not None
                and not reindex
                and previous.url == source.citation_url
                and previous.title == source.title
            ):
                self._attempt(conn, source, "completed")
                return {"unchanged": True}
            self._attempt(conn, source, "processing")
        return {
            "unchanged": False,
            "digest": digest,
            "revision": revision,
            "previous": previous,
            "embed": not valid or reindex,
        }

    def _embed_page(
        self, source: SourcePage, content: str, fingerprint: str, budget: WorkBudget, prepared: Dict[str, Any]
    ) -> Dict[str, Any]:
        if prepared["unchanged"]:
            return prepared
        digest, revision = prepared["digest"], prepared["revision"]
        records = None
        if prepared["embed"]:
            documents = PageMarkdownChunking().chunk(
                Document(id=self._page_id(source.path), name=source.path, content=content)
            )
            if len(documents) > 2000:
                raise ValueError("page_chunk_limit")
            records = []
            embeddings = self._embeddings([document.content for document in documents], budget)
            for index, (document, embedding) in enumerate(zip(documents, embeddings)):
                records.append(
                    {
                        "id": _digest(self._page_id(source.path) + ":" + str(index)),
                        "content_id": self._page_id(source.path),
                        "name": source.path,
                        "content": document.content,
                        "embedding": embedding,
                        "content_hash": digest,
                        "user_id": None,
                        "meta_data": {
                            **document.meta_data,
                            "namespace": self.namespace,
                            "revision": revision,
                            "index_fingerprint": fingerprint,
                        },
                    }
                )
        prepared["records"] = records
        return prepared

    def _publish(
        self,
        conn: Any,
        source: SourcePage,
        content: str,
        fingerprint: str,
        budget: WorkBudget,
        reindex: bool,
        prepared: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self._pending_publication = None
        if prepared is None:
            prepared = self._embed_page(
                source,
                content,
                fingerprint,
                budget,
                self._prepare_page(conn, source, content, fingerprint, budget, reindex),
            )
        if prepared["unchanged"]:
            return False
        digest, revision, previous, records = (prepared[key] for key in ("digest", "revision", "previous", "records"))
        budget.remaining()
        with conn.begin():
            self._settings(conn, budget)
            f = self.backend.table
            used = conn.execute(
                select(func.coalesce(func.sum(f.c.size_bytes), 0)).where(
                    f.c.namespace == self.namespace, f.c.path != source.path[1:]
                )
            ).scalar_one()
            size = len(content.encode("utf-8"))
            if size > self.fs.max_file_bytes or used + size > self.fs.max_namespace_bytes:
                raise QuotaExceededError(
                    "page_storage_quota", scope="namespace", current=size, limit=self.fs.max_namespace_bytes
                )
            file = self.backend._write_on(conn, self.namespace, source.path[1:], content)
            assert file.version is not None
            if records is not None:
                self.vector._replace_page_on(conn, self._page_id(source.path), records)
            page = Page(
                content_id=self._page_id(source.path),
                namespace=self.namespace,
                path=source.path,
                url=source.citation_url,
                title=source.title,
                revision=revision,
                digest=digest,
                index_fingerprint=fingerprint,
                filesystem_version=file.version,
                expected_chunk_count=len(records)
                if records is not None
                else previous.expected_chunk_count
                if previous is not None
                else 0,
            )
            if not self._valid_vectors(conn, page):
                raise ValueError("incomplete_page_vectors")
            old = (
                conn.execute(
                    select(self.catalog.c.metadata).where(self.catalog.c.id == page.content_id)
                ).scalar_one_or_none()
                or {}
            )
            publication_id = uuid4().hex
            metadata = {
                **old,
                "_agno": {
                    **old.get("_agno", {}),
                    "source_url": source.url,
                    "page": page.model_dump(),
                    "publication_id": publication_id,
                },
            }
            self.db._upsert_knowledge_content_on(
                conn,
                self.catalog,
                KnowledgeRow(
                    id=page.content_id,
                    name=source.title,
                    description="Published documentation page",
                    type="page",
                    size=size,
                    linked_to=self.knowledge.name,
                    status="completed",
                    metadata=metadata,
                    updated_at=int(time.time()),
                    created_at=int(time.time()),
                ),
            )
            conn.execute(
                update(self.binding)
                .where(self.binding.c.namespace == self.namespace)
                .values(revision=self.binding.c.revision + 1)
            )
            self._pending_publication = {"page": page, "publication_id": publication_id}
        self._pending_publication = None
        return True

    def _publication_outcome(self, path: str, *, deleted: bool = False) -> Optional[bool]:
        """Inspect a lost commit acknowledgement after fencing the old lock owner."""
        try:
            with self.engine.connect() as fresh, fresh.begin():
                self._settings(fresh, WorkBudget(3))
                if not fresh.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": self.lock_key}
                ).scalar_one():
                    return None
                if deleted:
                    catalog = fresh.execute(
                        select(self.catalog.c.id).where(self.catalog.c.id == self._page_id(path))
                    ).first()
                    file = fresh.execute(
                        select(self.backend.table.c.path).where(
                            self.backend.table.c.namespace == self.namespace, self.backend.table.c.path == path[1:]
                        )
                    ).first()
                    vectors = fresh.execute(
                        select(self.vector.table.c.id).where(self.vector.table.c.content_id == self._page_id(path))
                    ).first()
                    return True if catalog is None and file is None and vectors is None else None
                if self._pending_publication is None:
                    return None
                row = fresh.execute(
                    select(self.catalog.c.metadata).where(self.catalog.c.id == self._page_id(path))
                ).scalar_one_or_none()
                if (
                    row is None
                    or row.get("_agno", {}).get("publication_id") != self._pending_publication["publication_id"]
                ):
                    return None
                page, content = self._one(fresh, path)
                if (
                    page == self._pending_publication["page"]
                    and _digest(content) == page.digest
                    and self._valid_vectors(fresh, page)
                ):
                    return True
        except Exception:
            pass
        return None

    def read(
        self,
        path: str,
        *,
        revision: Optional[str] = None,
        offset: int = 0,
        max_chars: int = 12000,
        budget: Optional[WorkBudget] = None,
    ) -> PageRead:
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or not 1 <= max_chars <= 24000:
            raise ValueError("invalid_page_range")
        with self._snapshot(budget) as conn:
            rows = self._rows(conn, prefix=page_path(path), limit=1, exact_path=True, read_range=(offset, max_chars))
            if not rows:
                raise PageNotFound()
            page, content = self._checked(rows[0])
            total_chars = rows[0].total_chars
            if revision is not None and revision != page.revision:
                raise PageChanged(current_revision=page.revision)
            if offset > total_chars:
                raise ValueError("invalid_page_offset")

            def result(length: int) -> PageRead:
                end = offset + length
                return PageRead(
                    path=page.path,
                    url=page.url,
                    title=page.title,
                    revision=page.revision,
                    text=content[:length],
                    offset=offset,
                    next_offset=end if end < total_chars else None,
                    total_chars=total_chars,
                    truncated=end < total_chars,
                )

            low, high = 0, len(content)
            full = result(high)
            if encoded_size(full) <= MAX_JSON_BYTES:
                return full
            while low < high:
                middle = (low + high + 1) // 2
                if encoded_size(result(middle)) <= MAX_JSON_BYTES:
                    low = middle
                else:
                    high = middle - 1
            return result(low)

    def list(
        self, *, prefix: str = "/", cursor: Optional[str] = None, limit: int = 100, budget: Optional[WorkBudget] = None
    ) -> PageList:
        if not 1 <= limit <= 200:
            raise ValueError("invalid_page_limit")
        prefix = page_prefix(prefix)
        with self._snapshot(budget) as conn:
            revision = conn.execute(
                select(self.binding.c.revision).where(self.binding.c.namespace == self.namespace)
            ).scalar_one()
            after = ""
            if cursor:
                try:
                    if len(cursor) > 4096:
                        raise ValueError()
                    state = json.loads(base64.urlsafe_b64decode(cursor))
                    if state["namespace"] != self.namespace or state["prefix"] != prefix:
                        raise ValueError()
                    if state["revision"] != revision:
                        return PageList(restart_required=True)
                    after = page_path(state["after"])
                except Exception as exc:
                    raise ValueError("invalid_page_cursor") from exc
            rows = self._rows(conn, prefix=prefix, after=after, limit=limit + 1, include_content=False)
            pages: List[Page] = []
            page_bytes = 0

            def cursor_after(path: str) -> str:
                state = {"namespace": self.namespace, "prefix": prefix, "revision": revision, "after": path}
                return base64.urlsafe_b64encode(json.dumps(state).encode()).decode()

            for row in rows[:limit]:
                page = self._checked(row)[0]
                added_bytes = encoded_size(page) + bool(pages)
                envelope_bytes = encoded_size(PageList(next_cursor=cursor_after(page.path)))
                if envelope_bytes + page_bytes + added_bytes > MAX_JSON_BYTES:
                    break
                pages.append(page)
                page_bytes += added_bytes
            next_cursor = cursor_after(pages[-1].path) if pages and len(rows) > len(pages) else None
            return PageList(pages=tuple(pages), next_cursor=next_cursor)

    def grep(
        self,
        query: str,
        *,
        prefix: str = "/",
        ignore_case: bool = False,
        limit: int = 20,
        budget: Optional[WorkBudget] = None,
    ) -> GrepResult:
        if not isinstance(query, str) or not query or len(query) > 500 or not 1 <= limit <= 100:
            raise ValueError("invalid_grep_query")
        prefix = page_prefix(prefix)
        budget = budget or WorkBudget(0.25)
        budget.deadline = min(budget.deadline, time.monotonic() + 0.25)
        matches: List[GrepMatch] = []
        after = ""
        pattern = query
        try:
            with self._snapshot(budget) as conn:
                if ignore_case:
                    # Use one PostgreSQL collation for filtering, query folding and
                    # line matching; Python lower() differs for some Unicode text.
                    pattern = conn.execute(select(func.lower(query))).scalar_one()
                while True:
                    self._settings(conn, budget)
                    rows = self._rows(
                        conn, prefix=prefix, after=after, limit=4, literal_query=query, ignore_case=ignore_case
                    )
                    if not rows:
                        return GrepResult(matches=tuple(matches))
                    for row in rows:
                        page, content = self._checked(row)
                        folded_lines = row.folded_content.splitlines() if ignore_case else content.splitlines()
                        for number, line in enumerate(content.splitlines(), 1):
                            budget.remaining()
                            if pattern not in folded_lines[number - 1]:
                                continue
                            item = GrepMatch(
                                path=page.path, url=page.url, revision=page.revision, line_number=number, text=line
                            )
                            candidate = GrepResult(
                                matches=tuple([*matches, item]), complete=False, stop_reason="output_limit"
                            )
                            if encoded_size(candidate) > MAX_JSON_BYTES:
                                return GrepResult(matches=tuple(matches), complete=False, stop_reason="output_limit")
                            matches.append(item)
                            if len(matches) == limit:
                                return GrepResult(matches=tuple(matches), complete=False, stop_reason="limit")
                        after = page.path
        except TimeoutError:
            return GrepResult(matches=tuple(matches), complete=False, stop_reason="deadline")
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in ("57014", "55P03"):
                return GrepResult(matches=tuple(matches), complete=False, stop_reason="deadline")
            raise PageError() from exc

    def search(
        self,
        query: str,
        *,
        alternatives: Optional[List[str]] = None,
        limit: int = 10,
        max_output_bytes: int = MAX_JSON_BYTES,
        budget: Optional[WorkBudget] = None,
    ) -> SearchResult:
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 500 or not 1 <= limit <= 20:
            raise ValueError("invalid_search_query")
        if alternatives is not None and (not isinstance(alternatives, list) or len(alternatives) > 3):
            raise ValueError("invalid_search_alternatives")
        if type(max_output_bytes) is not int or not MAX_JSON_BYTES <= max_output_bytes <= MAX_SEARCH_JSON_BYTES:
            raise ValueError("invalid_search_output_budget")
        budget = budget or WorkBudget(2)
        queries = [query.strip()]
        for alternative in alternatives or []:
            if not isinstance(alternative, str) or not alternative.strip() or len(alternative.strip()) > 500:
                raise ValueError("invalid_search_alternatives")
            if alternative.strip() not in queries:
                queries.append(alternative.strip())
        vectors = []
        partial = False
        from agno.knowledge.embedder.openai import OpenAIEmbedder

        if isinstance(self.vector.embedder, OpenAIEmbedder):
            try:
                vectors = list(zip(queries, self._embeddings(queries, budget)))
            except Exception as exc:
                if len(queries) == 1:
                    raise SearchUnavailable() from exc
                # Recover the primary query when a batch was rejected as a whole.
                try:
                    vectors = [(queries[0], self._embedding(queries[0], budget))]
                except Exception as primary:
                    raise SearchUnavailable() from primary
                partial = True
        else:
            for index, phrasing in enumerate(queries):
                try:
                    vectors.append((phrasing, self._embedding(phrasing, budget)))
                except Exception as exc:
                    if index == 0:
                        raise SearchUnavailable() from exc
                    partial = True
        scores: Dict[str, float] = {}
        payload: Dict[str, Any] = {}
        parallel = len(vectors) > 1 and _PARALLEL_SEARCHES.acquire(blocking=False)
        try:
            with self._snapshot(budget) as conn:
                # Each partial HNSW index contains one corpus before ANN traversal.
                # Prepare the same stemmed OR queries once. Bound tsquery values let
                # PostgreSQL estimate lexical matches instead of assuming a one-row
                # CTE, and let its parallel bitmap scan rank broad matches in parallel.
                settings, setting_values = self._search_settings(parallel=parallel)
                tsqueries = conn.execute(
                    text(
                        "SELECT ARRAY(SELECT (SELECT string_agg(quote_literal(lexeme), ' | ') "
                        "FROM unnest(tsvector_to_array(to_tsvector('english', phrasing))) AS lexeme)::tsquery::text "
                        "FROM unnest(CAST(:queries AS text[])) WITH ORDINALITY AS inputs(phrasing, position) "
                        "ORDER BY position)" + (", " + settings if settings else "")
                    ),
                    {"queries": [phrasing for phrasing, _ in vectors], **setting_values},
                ).scalar_one()
                query_specs = [
                    (
                        self._hybrid_sql(),
                        {
                            "tsquery": tsqueries[index],
                            "vector": json.dumps(vector),
                            "namespace": self.namespace,
                            "weight": self.vector.vector_score_weight,
                        },
                    )
                    for index, (_, vector) in enumerate(vectors)
                ]
                for index, outcome in enumerate(self._search_queries(conn, query_specs, budget, parallel=parallel)):
                    try:
                        if isinstance(outcome, Exception):
                            raise outcome
                        for rank, row in enumerate(outcome):
                            if row["file_version"] != row["page"]["filesystem_version"]:
                                raise SearchUnavailable()
                            ident = row["id"]
                            scores[ident] = scores.get(ident, 0) + 1 / (60 + rank)
                            if ident not in payload or row["score"] > payload[ident]["score"]:
                                payload[ident] = row
                    except Exception:
                        if index == 0:
                            raise
                        partial = True
                hits: List[SearchHit] = []
                per_page: Counter = Counter()
                # Equal fused scores retain first appearance in the caller's query
                # order, so a primary-query hit wins a tie with an alternative.
                for ident in sorted(scores, key=lambda key: -scores[key]):
                    row = payload[ident]
                    page = row["page"]
                    if per_page[page["path"]] >= 3:
                        continue
                    hit = SearchHit(
                        path=page["path"],
                        url=page["url"],
                        title=row["breadcrumb"] or page["title"],
                        revision=page["revision"],
                        chunk_id=ident,
                        content=row["content"],
                        score=row["score"],
                        rank=len(hits) + 1,
                    )
                    hits.append(hit)
                    per_page[page["path"]] += 1
                    if len(hits) == limit:
                        break
                total = len(hits)
                while (
                    hits
                    and encoded_size(
                        SearchResult(
                            results=tuple(hits),
                            partial=partial,
                            truncated=len(hits) != total,
                            omitted_count=total - len(hits),
                            warnings=("alternative_unavailable",) if partial else (),
                        )
                    )
                    > max_output_bytes
                ):
                    hits.pop()
                result = SearchResult(
                    results=tuple(hits),
                    partial=partial,
                    truncated=len(hits) != total,
                    omitted_count=total - len(hits),
                    warnings=("alternative_unavailable",) if partial else (),
                )
                return result
        except PageError:
            raise
        except Exception as exc:
            raise SearchUnavailable() from exc
        finally:
            if parallel:
                _PARALLEL_SEARCHES.release()

    def _search_queries(
        self, conn: Any, queries: List[Tuple[str, Dict[str, Any]]], budget: WorkBudget, *, parallel: bool
    ) -> List[Any]:
        from agno.db.postgres._bounded import ConnectionUnavailable

        # Optional SQL must stop before the caller's deadline, leaving time for
        # rollback, child cleanup and delivery of the successful primary result.
        # Share cancellation with the parent; never extend its overall deadline.
        remaining = budget.remaining()
        optional_budget = WorkBudget(remaining)
        optional_budget.deadline = budget.deadline - 0.2
        optional_budget.cancelled = budget.cancelled

        def execute(connection: Any, query: tuple, work_budget: WorkBudget) -> Any:
            self._settings(connection, work_budget)
            return connection.execute(text(query[0]), query[1]).mappings().all()

        if not parallel:
            outcomes = []
            for index, query in enumerate(queries):
                try:
                    with conn.begin_nested() if index else nullcontext():
                        outcomes.append(execute(conn, query, optional_budget if index else budget))
                except Exception as exc:
                    if index == 0:
                        raise
                    outcomes.append(exc)
            return outcomes

        snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar_one()

        def alternative(query: tuple) -> Any:
            try:
                optional_budget.remaining()
                with self._snapshot(optional_budget, snapshot=snapshot) as child:
                    settings, values = self._search_settings(parallel=True)
                    child.execute(text("SELECT " + settings), values)
                    return execute(child, query, optional_budget)
            except Exception as exc:
                return exc

        futures = []
        try:
            for query in queries[1:]:
                futures.append(_QUERY_WORKERS.submit(contextvars.copy_context().run, alternative, query))
            primary = execute(conn, queries[0], budget)
            outcomes = [primary]
            for query, future in zip(queries[1:], futures):
                try:
                    outcome = future.result(timeout=0 if future.done() else optional_budget.remaining())
                    if isinstance(outcome, ConnectionUnavailable):
                        # Preserve query coverage without making the primary wait
                        # for a new child's connection handshake or pool retry.
                        with conn.begin_nested():
                            outcome = execute(conn, query, optional_budget)
                    outcomes.append(outcome)
                except Exception as exc:
                    outcomes.append(exc)
            return outcomes
        finally:
            # The exporting transaction and admission slot outlive every child,
            # including cancellation or failure while a child is using its snapshot.
            for future in futures:
                future.cancel()
            wait(futures)

    def _search_settings(self, *, parallel: bool) -> Tuple[str, Dict[str, str]]:
        settings = {
            name: getattr(self.search_config, name)
            for name in PageSearchConfig.model_fields
            if getattr(self.search_config, name) is not None
        }
        if isinstance(self.vector.vector_index, HNSW):
            settings["hnsw.ef_search"] = self.vector.vector_index.ef_search
        if parallel:
            settings["max_parallel_workers_per_gather"] = 0
        sql, values = [], {}
        for index, (name, value) in enumerate(settings.items()):
            # Names come only from the typed config and the fixed HNSW setting;
            # every caller-provided value is a bound parameter.
            parameter = "search_setting_" + str(index)
            sql.append(f"set_config('{name}', :{parameter}, true)")
            values[parameter] = "on" if value is True else "off" if value is False else str(value)
        return ", ".join(sql), values

    def _hybrid_sql(self) -> str:
        catalog = _identifier(self.catalog.schema) + "." + _identifier(self.catalog.name)
        files = _identifier(self.backend.db_schema) + "." + _identifier(self.backend.table_name)
        # Parallel ranking must restore bitmap-heap traversal order before the
        # top-N sort, so ties at the lexical cutoff retain the serial candidates.
        return f"""WITH by_vector AS (
            SELECT id FROM {self._vector_name} WHERE meta_data->>'namespace'=:namespace
            ORDER BY embedding <=> CAST(:vector AS vector) LIMIT 200
        ), keyword_scores AS MATERIALIZED (
            SELECT id, ts_rank_cd(_agno_page_tsv, CAST(:tsquery AS tsquery)) AS keyword_score
            FROM {self._vector_name}
            WHERE meta_data->>'namespace'=:namespace AND _agno_page_tsv @@ CAST(:tsquery AS tsquery)
            ORDER BY ctid
        ), by_keyword AS (
            SELECT id FROM keyword_scores ORDER BY keyword_score DESC LIMIT 200
        ), candidates AS (SELECT id FROM by_vector UNION SELECT id FROM by_keyword), ranked AS (
        SELECT v.id, v.content, v.meta_data->>'breadcrumb' AS breadcrumb,
            c.metadata->'_agno'->'page' AS page,
            :weight * GREATEST(0, 1 - (v.embedding <=> CAST(:vector AS vector))) +
            (1 - :weight) * COALESCE(ts_rank_cd(v._agno_page_tsv, CAST(:tsquery AS tsquery)) /
                                       (ts_rank_cd(v._agno_page_tsv, CAST(:tsquery AS tsquery)) + 0.1), 0) AS score
        FROM {self._vector_name} v JOIN candidates USING (id)
        JOIN {catalog} c ON c.id=v.content_id
            AND c.metadata->'_agno'->'page'->>'namespace'=:namespace
            AND c.metadata->'_agno'->'page'->>'revision'=v.meta_data->>'revision'
        ORDER BY score DESC, v.id LIMIT 20)
        SELECT ranked.*, f.version AS file_version FROM ranked
        LEFT JOIN {files} f ON f.namespace=:namespace AND f.path=substr(ranked.page->>'path', 2)
        ORDER BY score DESC, ranked.id"""

    def sync(
        self,
        *,
        url: str,
        public_url: Optional[str] = None,
        transform: Any = None,
        index_version: str = "1",
        reindex: bool = False,
        validate_discovery: Optional[Callable[[int, int], None]] = None,
        budget: Optional[WorkBudget] = None,
    ) -> SyncReport:
        if validate_discovery is not None and not callable(validate_discovery):
            raise ValueError("validate_discovery must be a synchronous callable")
        self._ready()
        budget = budget or WorkBudget(3900)
        source = PageSource(url, public_url, budget)
        updated = deleted = failed = unknown = 0
        errors = []
        acquired = False
        with self.engine.connect() as conn:
            lock_deadline = time.monotonic() + min(1200, budget.remaining())
            try:
                while not acquired:
                    with conn.begin():
                        self._settings(conn, budget)
                        acquired = conn.execute(
                            text("SELECT pg_try_advisory_lock(:key)"), {"key": self.lock_key}
                        ).scalar_one()
                    if not acquired:
                        if time.monotonic() >= lock_deadline:
                            raise SyncFailed()
                        budget.cancelled.wait(min(0.1, budget.remaining()))
                budget.deadline = min(budget.deadline, time.monotonic() + 2700)
                with conn.begin():
                    binding = (
                        conn.execute(select(self.binding).where(self.binding.c.namespace == self.namespace))
                        .mappings()
                        .one()
                    )
                    if binding["source"] not in (None, source.url):
                        raise ValueError("filesystem namespace is bound to another documentation source")
                    conn.execute(
                        update(self.binding).where(self.binding.c.namespace == self.namespace).values(source=source.url)
                    )
                    self._source_attempt(conn, source, "processing")
                pages = source.discover()
                if validate_discovery is not None:
                    with conn.begin():
                        self._settings(conn, budget)
                        published = conn.execute(
                            select(func.count()).select_from(self.catalog).where(self._predicate())
                        ).scalar_one()
                    budget.remaining()
                    # Enforce the callback contract even for untyped callers. An
                    # accidental boolean or coroutine must not approve publication.
                    outcome = cast(Callable[[int, int], Any], validate_discovery)(len(pages), published)
                    if outcome is not None:
                        if inspect.iscoroutine(outcome):
                            outcome.close()
                        raise ValueError("validate_discovery must return None or raise ValueError")
                    budget.remaining()
                fingerprint = self._fingerprint(index_version)
                with closing(
                    self._embedding_pages(conn, source, pages, transform, fingerprint, budget, reindex)
                ) as prepared_pages:
                    for page, content, prepared, fetch_error in prepared_pages:
                        budget.remaining()
                        try:
                            if fetch_error is not None:
                                raise fetch_error
                            assert isinstance(content, str)
                            updated += int(
                                self._publish(conn, page, content, fingerprint, budget, reindex, prepared=prepared)
                            )
                        except Exception as exc:
                            log_warning(f"Page sync failed ({type(exc).__name__})")
                            if conn.invalidated or conn.closed or self._pending_publication is not None:
                                # Do not reconnect a connection that owned the namespace lock.
                                conn.invalidate()
                                if self._publication_outcome(page.path):
                                    updated += 1
                                    errors.append("sync_connection_lost")
                                else:
                                    unknown += 1
                                    errors.append("commit_outcome_unknown")
                                break
                            failed += 1
                            errors.append("page_sync_failed")
                            with conn.begin():
                                self._settings(conn, budget)
                                self._attempt(conn, page, "failed")
                if source.complete and not errors and not failed and not unknown:
                    with conn.begin():
                        paths = [
                            row.metadata["_agno"]["page"]["path"]
                            for row in self._rows(conn, limit=20_001, include_content=False)
                        ]
                    for path in paths:
                        if path in pages:
                            continue
                        pending_delete = False
                        try:
                            with conn.begin():
                                self._settings(conn, budget)
                                self.vector._replace_page_on(conn, self._page_id(path), [])
                                self.backend._delete_on(conn, self.namespace, path[1:])
                                conn.execute(delete(self.catalog).where(self.catalog.c.id == self._page_id(path)))
                                conn.execute(
                                    update(self.binding)
                                    .where(self.binding.c.namespace == self.namespace)
                                    .values(revision=self.binding.c.revision + 1)
                                )
                                pending_delete = True
                            deleted += 1
                        except Exception:
                            if conn.invalidated or conn.closed or pending_delete:
                                conn.invalidate()
                                if self._publication_outcome(path, deleted=True):
                                    deleted += 1
                                    errors.append("sync_connection_lost")
                                else:
                                    unknown += 1
                                    errors.append("commit_outcome_unknown")
                            else:
                                failed += 1
                                errors.append("page_delete_failed")
                            break
                if not source.complete:
                    errors.append("incomplete_discovery")
                report = SyncReport(
                    status="partial" if errors else "completed" if updated or deleted else "unchanged",
                    discovered=len(pages),
                    updated=updated,
                    deleted=deleted,
                    failed=failed,
                    unknown=unknown,
                    errors=tuple(errors[:20]),
                )
                if not conn.invalidated and not conn.closed:
                    with conn.begin():
                        self._settings(conn, budget)
                        self._source_attempt(conn, source, "partial" if errors else "completed", report)
                return report
            except Exception as exc:
                if acquired and not conn.invalidated and not conn.closed:
                    try:
                        conn.rollback()
                        with conn.begin():
                            self._settings(conn, WorkBudget(3))
                            self._source_attempt(conn, source, "failed")
                    except Exception:
                        conn.invalidate()
                if isinstance(exc, ValueError):
                    raise
                raise SyncFailed() from exc
            finally:
                if acquired and not conn.invalidated and not conn.closed:
                    try:
                        conn.rollback()
                        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.lock_key})
                        conn.commit()
                    except Exception:
                        conn.invalidate()
