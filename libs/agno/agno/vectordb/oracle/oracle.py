"""OracleVector: documents stored in Oracle Database, retrieved by vector similarity.

Reference implementation: ``agno.vectordb.pgvector.PgVector``. This ticket
(17) delivers the vector-similarity path only -- keyword/hybrid search,
metadata filters and index tuning (``optimize()``) are ticket 18's scope, and
raise ``NotImplementedError`` naming it explicitly here, the same MySQL-stub
precedent the storage adapter side of this effort already follows for its own
not-yet-implemented domains.

Requires Oracle Database 23ai or later: the native ``VECTOR`` type and the
``VECTOR_DISTANCE`` function do not exist on earlier releases. The version
floor is enforced eagerly, in ``create()``, before any DDL is attempted --
never in ``__init__``, which (like PgVector's) does no I/O at all, so the
store can be instantiated without a live connection.
"""

import array
import asyncio
import json as json_module
from hashlib import md5
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from sqlalchemy import and_, bindparam, func, literal_column, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.schema import Column, Index, MetaData, Table
from sqlalchemy.types import DateTime, String, Text, TypeDecorator

from agno.db.oracle._version import OracleCapabilities, detect_capabilities
from agno.db.oracle.engine import create_oracle_engine
from agno.db.oracle.utils import merge_upsert_many
from agno.exceptions import EmbeddingError
from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id
from agno.vectordb.base import (
    VectorDb,
    aembed_before_replace,
    embed_before_replace,
    is_rate_limit_error,
    raise_embedding_failures,
    retrievable_documents,
)
from agno.vectordb.distance import Distance
from agno.vectordb.score import normalize_score, score_to_distance_threshold
from agno.vectordb.search import SearchType

if TYPE_CHECKING:
    from agno.db.oracle import OracleDb

# Oracle 23ai's minimum major version for the native VECTOR type and
# VECTOR_DISTANCE(). See agno.db.oracle._version's own module docstring for
# why detection reads PRODUCT_COMPONENT_VERSION rather than V$INSTANCE.
_MIN_VECTOR_MAJOR_VERSION = 23

_DISTANCE_METRIC = {
    Distance.cosine: "COSINE",
    Distance.l2: "EUCLIDEAN",
    Distance.max_inner_product: "DOT",
}

# Widths are declared locally rather than imported from agno.db.oracle.schemas:
# this store is an independent branch from ticket 02 sharing no files with the
# storage adapter, and these are small, one-off decisions, not a shared table
# of constants worth cross-importing.
_WIDTH_ID = 128  # record id: always a 32-hex-char md5 digest, generous headroom
_WIDTH_NAME = 500  # document name (often a filename or URL)
_WIDTH_HASH = 128  # content_hash, content_id


class OracleVectorType(TypeDecorator):
    """Oracle's native ``VECTOR(n, FLOAT32)`` column type.

    python-oracledb binds and fetches VECTOR values as ``array.array('f', ...)``,
    not a plain Python list (confirmed against a live server: passing a bare
    list raises ``ORA-01484: arrays can only be bound to PL/SQL statements``).
    This type hides that translation so every caller here still works with
    plain ``List[float]``, matching ``Document.embedding``'s own type.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int):
        super().__init__()
        self.dimensions = dimensions

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return array.array("f", value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[List[float]]:
        if value is None:
            return None
        return list(value)


@compiles(OracleVectorType, "oracle")
def _compile_oracle_vector_type(element: Any, compiler: Any, **kw: Any) -> str:
    return f"VECTOR({element.dimensions}, FLOAT32)"


class OracleNativeJSON(TypeDecorator):
    """Native Oracle JSON column (requires 21c+, already guaranteed here by the
    23ai+ floor VECTOR itself requires). Self-contained rather than reusing
    ``agno.db.oracle.schemas.OracleNativeJSON``: this store is an independent
    branch from ticket 02 sharing no files with the storage adapter, and a
    plain ``sqlalchemy.types.JSON`` has no Oracle-dialect DDL rendering at all
    (confirmed against a live server: ``UnsupportedCompilationError``, no
    ``visit_JSON`` on Oracle's type compiler).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        return None if value is None else json_module.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        # python-oracledb's thin driver can hand a native JSON column back
        # already decoded (dict/list/str/etc.), not JSON-encoded text --
        # matching agno.db.oracle.schemas.OracleNativeJSON's own finding
        # against a live server. Only re-parse when it is still a JSON string.
        if value is None or not isinstance(value, str):
            return value
        return json_module.loads(value)


@compiles(OracleNativeJSON, "oracle")
def _compile_oracle_native_json(element: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


def _json_path_literal(key: str) -> str:
    """A safely-escaped, single-quoted SQL literal for a JSON_VALUE/JSON_EXISTS
    path selecting one quoted top-level member name.

    Oracle's JSON path argument to JSON_VALUE must be a SQL literal -- it
    cannot be a bind parameter (confirmed against a live server: ORA-40454,
    "path expression not a literal") -- so a filter key coming from caller
    data must be escaped, not bound, to stay injection-safe. Escapes for the
    JSON path's own quoted-member-name syntax first (backslash, then double
    quote), then for the enclosing SQL string literal (single quote).
    """
    json_escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    sql_escaped = json_escaped.replace("'", "''")
    return f"'$.\"{sql_escaped}\"'"


# Oracle folds an empty string to NULL on write (confirmed against a live
# server, the same finding ticket 04 made for the storage adapter's owner
# columns) -- and NULL is the genuine shared bucket here. Without this
# sentinel, a caller passing user_id="" (an explicitly unowned upload, not
# "no filter") would silently land in the shared bucket with no error, the
# highest-stakes case this ticket calls out: record identity, search scope
# and every delete path all key off this same translation, or the leak is
# invisible until two callers' "unowned" content collides.
_UNOWNED_SENTINEL = "__agno_oraclevector_unowned__"


def _to_db_user_id(user_id: Optional[str]) -> Optional[str]:
    """None stays None (every owner / unfiltered); "" becomes the sentinel,
    so it survives Oracle's empty-string-is-null folding and stays distinct
    from None; any other value is stored unchanged."""
    if user_id is None:
        return None
    if user_id == "":
        return _UNOWNED_SENTINEL
    return user_id


def _from_db_user_id(user_id: Optional[str]) -> Optional[str]:
    """Inverse of ``_to_db_user_id``."""
    if user_id is None:
        return None
    if user_id == _UNOWNED_SENTINEL:
        return ""
    return user_id


class OracleVector(VectorDb):
    """Vector database backed by Oracle Database 23ai+'s native VECTOR type."""

    def __init__(
        self,
        table_name: str,
        schema: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        reranker: Optional[Reranker] = None,
        create_schema: bool = True,
        similarity_threshold: Optional[float] = None,
        *,
        db: Optional["OracleDb"] = None,
    ):
        """
        Args:
            table_name: Name of the table to store vector data.
            schema: Oracle schema (user) the table lives in. None (the default)
                means the connecting user's own schema, matching OracleDb's own
                ``db_schema`` semantics -- Oracle has no per-connection default
                schema distinct from the connecting user.
            db_url: Database connection URL.
            db_engine: SQLAlchemy database engine.
            db: Borrow a synchronous OracleDb's engine. Cannot be combined with
                db_url or db_engine; does not transfer ownership.
            embedder: Embedder instance for creating embeddings.
            distance: Distance metric for vector comparisons.
            reranker: Reranker instance for reranking search results.
            create_schema: Accepted for interface parity with PgVector; has no
                effect (see OracleDb's own create_schema docstring -- Oracle has
                no privilege-safe way to create a schema/user from application
                code).
            similarity_threshold: Minimum similarity score (0.0-1.0) to filter results.
        """
        if not table_name:
            raise ValueError("Table name must be provided.")

        if db is not None:
            from agno.db.oracle import OracleDb

            if db_url is not None or db_engine is not None:
                raise ValueError("Provide db alone, without db_url or db_engine")
            if (
                not isinstance(db, OracleDb)
                or not isinstance(db.db_engine, Engine)
                or db.db_engine.dialect.name != "oracle"
            ):
                raise ValueError("db requires a synchronous OracleDb; use db_engine for a direct engine")
            db_engine = db.db_engine
            if schema is None:
                schema = db.db_schema
        if db_engine is None and db_url is None:
            raise ValueError("Provide db, db_url, or db_engine")

        if id is None:
            base_seed = db_url or str(db_engine.url)  # type: ignore
            seed = f"{base_seed}#{table_name}"
            id = generate_id(seed)

        super().__init__(id=id, name=name, description=description, similarity_threshold=similarity_threshold)

        if db_engine is None:
            if db_url is None:
                raise ValueError("Must provide 'db_url' if 'db_engine' is None.")
            try:
                db_engine = create_oracle_engine(db_url)
            except Exception as e:
                log_error(f"Failed to create engine from 'db_url': {str(e)}")
                raise

        self.table_name: str = table_name
        # None means the connecting user's own schema -- see OracleDb's own
        # db_schema docstring; Oracle has no separate default-schema concept.
        self.schema: Optional[str] = schema
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = db_engine
        self.metadata: MetaData = MetaData(schema=self.schema)

        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions
        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        self.distance: Distance = distance
        self.reranker: Optional[Reranker] = reranker
        self.create_schema: bool = create_schema

        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))
        # Capabilities are resolved lazily, on first create()/table access --
        # never in __init__, which must stay a pure, connection-free
        # constructor (mirroring PgVector's own zero-I/O __init__).
        self.capabilities: Optional[OracleCapabilities] = None
        # Whether the live table has the ``user_id`` column; a hand-created
        # table predating per-user isolation would lack it.
        self._owner_column_exists: Optional[bool] = None
        self.table: Table = self.get_table()
        log_debug(f"Initialized OracleVector with table '{self.table_name}'", log_level=2)

    # -- Table definition --

    def get_table(self) -> Table:
        if self.dimensions is None:
            raise ValueError("Embedder dimensions are not set.")
        table = Table(
            self.table_name,
            self.metadata,
            Column("id", String(_WIDTH_ID), primary_key=True),
            Column("name", String(_WIDTH_NAME)),
            Column("meta_data", OracleNativeJSON),
            Column("filters", OracleNativeJSON, nullable=True),
            Column("content", Text),
            Column("embedding", OracleVectorType(self.dimensions)),
            Column("usage", OracleNativeJSON, nullable=True),
            Column("created_at", DateTime, server_default=func.sysdate()),
            Column("updated_at", DateTime, nullable=True, onupdate=func.sysdate()),
            Column("content_hash", String(_WIDTH_HASH)),
            Column("content_id", String(_WIDTH_HASH), nullable=True),
            # Owner of the chunk. NULL is shared content, readable by every caller.
            Column("user_id", String(_WIDTH_ID), nullable=True),
            extend_existing=True,
        )

        Index(f"idx_{self.table_name}_name", table.c.name)
        Index(f"idx_{self.table_name}_content_hash", table.c.content_hash)
        Index(f"idx_{self.table_name}_content_id", table.c.content_id)
        Index(f"idx_{self.table_name}_user_id", table.c.user_id)
        return table

    # -- Table lifecycle --

    def table_exists(self) -> bool:
        try:
            return inspect(self.db_engine).has_table(self.table_name, schema=self.schema)
        except Exception as e:
            log_error(f"Error checking if table exists: {str(e)}")
            return False

    def _require_version_floor(self) -> None:
        """Enforce the VECTOR type's version floor eagerly, before any DDL.

        Raises a clear, actionable error naming the required version rather
        than letting the CREATE TABLE fail with an opaque ORA-00902 ("invalid
        datatype") on a server that predates the VECTOR type.
        """
        if self.capabilities is None:
            self.capabilities = detect_capabilities(self.db_engine)
        if not self.capabilities.vector:
            raise ValueError(
                f"OracleVector requires Oracle Database {_MIN_VECTOR_MAJOR_VERSION}ai or later for the native "
                f"VECTOR type and VECTOR_DISTANCE(); connected server reports version "
                f"{self.capabilities.full_version} (major {self.capabilities.major})."
            )

    def create(self) -> None:
        self._require_version_floor()
        if not self.table_exists():
            self.table.create(self.db_engine)
            log_debug(f"Created table {self.table.fullname}")
            self._owner_column_exists = True

    async def async_create(self) -> None:
        await asyncio.to_thread(self.create)

    # -- Owner-column guard: mirrors PgVector's own legacy pre-v3 schema
    # guard exactly, pointing at the same migration path. OracleVector has no
    # deployed pre-isolation history of its own (it is a new adapter, built
    # with the user_id column from its first release) -- this guard exists
    # purely so a hand-created table missing the column fails loudly instead
    # of silently ignoring user_id. --

    def _user_id_column_exists(self) -> bool:
        if self._owner_column_exists is None:
            try:
                columns = inspect(self.db_engine).get_columns(self.table_name, schema=self.schema)
                self._owner_column_exists = any(col["name"] == "user_id" for col in columns)
            except NoSuchTableError:
                self._owner_column_exists = True
            except Exception:
                log_warning(
                    f"Could not inspect table '{self.table_name}' for the user_id column; "
                    "proceeding as migrated for this operation."
                )
                return True
        return self._owner_column_exists

    def _require_owner_column(self, user_id: Optional[str]) -> bool:
        if self._user_id_column_exists():
            return True
        if user_id is None:
            return False
        self._owner_column_exists = None
        if self._user_id_column_exists():
            return True
        raise ValueError(
            f"user_id={user_id!r} was passed but table '{self.table.fullname}' has no 'user_id' column. "
            "Run the v2 -> v3 migration (libs/agno/migrations/v2_to_v3/migrate_sql_vectordbs.py) or recreate "
            "the table."
        )

    def _record_exists(self, column, value, scope_to_owner: bool = False, user_id: Optional[str] = None) -> bool:
        scope_to_owner = scope_to_owner and self._require_owner_column(user_id)
        try:
            with self.Session() as sess, sess.begin():
                stmt = select(1).where(column == value)
                if scope_to_owner:
                    if user_id is not None:
                        stmt = stmt.where(self.table.c.user_id == _to_db_user_id(user_id))
                    else:
                        stmt = stmt.where(self.table.c.user_id.is_(None))
                result = sess.execute(stmt.limit(1)).first()
                return result is not None
        except Exception as e:
            log_error(f"Error checking if record exists: {str(e)}")
            return False

    def name_exists(self, name: str) -> bool:
        return self._record_exists(self.table.c.name, name)

    async def async_name_exists(self, name: str) -> bool:
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        return self._record_exists(self.table.c.id, id)

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        return self._record_exists(self.table.c.content_hash, content_hash, scope_to_owner=True, user_id=user_id)

    def _clean_content(self, content: str) -> str:
        return content.replace("\x00", "�")

    # -- Record identity: base id + content hash + owner, two-stage digest --

    def _scoped_record_id(self, base_id: str, content_hash: str, user_id: Optional[str]) -> str:
        """Fold base id, content hash and owner into a fixed-length digest, matching
        PgVector's own two-stage scheme: differently-partitioned inputs cannot collide
        (a document named with a trailing fragment cannot collide with another whose
        owner happens to supply that fragment), since each stage hashes its own
        concatenation rather than joining raw strings with a separator a caller's own
        data could also contain.
        """
        record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
        if user_id is None:
            return record_id
        return md5(f"{record_id}_{user_id}".encode()).hexdigest()

    def _get_document_record(
        self,
        doc: Document,
        filters: Optional[Dict[str, Any]] = None,
        content_hash: str = "",
        user_id: Optional[str] = None,
        *,
        prepared: bool = False,
    ) -> Dict[str, Any]:
        if not prepared or not doc.embedding:
            doc.embed(embedder=self.embedder)
        cleaned_content = self._clean_content(doc.content)
        base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
        record_id = self._scoped_record_id(base_id, content_hash, user_id)

        meta_data = doc.meta_data or {}
        if filters:
            meta_data.update(filters)

        record = {
            "id": record_id,
            "name": doc.name,
            "meta_data": meta_data,
            "filters": filters,
            "content": cleaned_content,
            "embedding": doc.embedding,
            "usage": doc.usage,
            "content_hash": content_hash,
            "content_id": doc.content_id,
        }
        if self._user_id_column_exists():
            record["user_id"] = _to_db_user_id(user_id)
        return record

    # -- Insert --

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        user_id: Optional[str] = None,
    ) -> None:
        self._require_owner_column(user_id)
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    try:
                        batch_records = []
                        for doc in batch_docs:
                            try:
                                batch_records.append(self._get_document_record(doc, filters, content_hash, user_id))
                            except EmbeddingError:
                                raise
                            except Exception as e:
                                log_error(f"Error processing document '{doc.name}': {str(e)}")

                        batch_records = [r for r in batch_records if r.get("embedding")]
                        if batch_records:
                            sess.execute(self.table.insert(), batch_records)
                            sess.commit()
                            log_info(f"Inserted batch of {len(batch_records)} documents.")
                    except Exception as e:
                        log_error(f"Error with batch starting at index {i}: {str(e)}")
                        sess.rollback()
                        raise
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    async def _async_embed_documents(self, batch_docs: List[Document], *, prepared: bool = False) -> None:
        if prepared:
            batch_docs = [doc for doc in batch_docs if not doc.embedding]
        if not batch_docs:
            return
        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            try:
                doc_contents = [doc.content for doc in batch_docs]
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)
                for j, doc in enumerate(batch_docs):
                    try:
                        if j < len(embeddings):
                            doc.embedding = embeddings[j]
                            doc.usage = usages[j] if j < len(usages) else None
                    except Exception as e:
                        log_error(f"Error assigning batch embedding to document '{doc.name}': {str(e)}")
            except Exception as e:
                if isinstance(e, EmbeddingError):
                    is_rate_limit = e.reason == "rate_limit"
                else:
                    is_rate_limit = is_rate_limit_error(e)
                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding.: {str(e)}")
                    raise e
                else:
                    log_warning(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in batch_docs]
                    results = await asyncio.gather(*embed_tasks, return_exceptions=True)
                    raise_embedding_failures(results)
        else:
            embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in batch_docs]
            results = await asyncio.gather(*embed_tasks, return_exceptions=True)
            raise_embedding_failures(results)

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        user_id: Optional[str] = None,
    ) -> None:
        self._require_owner_column(user_id)
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    try:
                        await self._async_embed_documents(batch_docs)
                        batch_docs = retrievable_documents(batch_docs)
                        batch_records = []
                        for doc in batch_docs:
                            try:
                                batch_records.append(
                                    self._get_document_record(doc, filters, content_hash, user_id, prepared=True)
                                )
                            except Exception as e:
                                log_error(f"Error processing document '{doc.name}': {str(e)}")

                        batch_records = [r for r in batch_records if r.get("embedding")]
                        if batch_records:
                            sess.execute(self.table.insert(), batch_records)
                            sess.commit()
                            log_info(f"Inserted batch of {len(batch_records)} documents.")
                    except Exception as e:
                        log_error(f"Error with batch starting at index {i}: {str(e)}")
                        sess.rollback()
                        raise
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    # -- Upsert --

    def upsert_available(self) -> bool:
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents by content hash.

        Embeds before deleting: an embedder that fails must not destroy
        retrievable content. Re-ingesting unchanged content does not
        duplicate it, since the record id is keyed on content hash.
        """
        for document in documents:
            if not document.embedding:
                document.embedding = None
        embed_before_replace(documents, self.embedder)
        documents = retrievable_documents(documents)
        self._require_owner_column(user_id)
        try:
            if self.content_hash_exists(content_hash, user_id=user_id):
                self._delete_by_content_hash(content_hash, user_id=user_id)
            self._upsert(content_hash, documents, filters, batch_size, user_id=user_id)
        except Exception as e:
            log_error(f"Error upserting documents by content hash: {str(e)}")
            raise

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        user_id: Optional[str] = None,
    ) -> None:
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    try:
                        batch_records_dict: Dict[str, Dict[str, Any]] = {}
                        for doc in batch_docs:
                            try:
                                record = self._get_document_record(doc, filters, content_hash, user_id, prepared=True)
                                batch_records_dict[record["id"]] = record
                            except EmbeddingError:
                                raise
                            except Exception as e:
                                log_error(f"Error processing document '{doc.name}': {str(e)}")

                        batch_records = [r for r in batch_records_dict.values() if r.get("embedding")]
                        if not batch_records:
                            log_info("No valid records to upsert in this batch.")
                            continue

                        key_columns = ["id"]
                        preserve = ["created_at"]
                        with sess.begin():
                            merge_upsert_many(
                                sess, self.table, key_columns, batch_records, preserve_on_conflict=preserve
                            )
                        log_info(f"Upserted batch of {len(batch_records)} documents.")
                    except Exception as e:
                        log_error(f"Error with batch starting at index {i}: {str(e)}")
                        sess.rollback()
                        raise
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        user_id: Optional[str] = None,
    ) -> None:
        for document in documents:
            if not document.embedding:
                document.embedding = None
        await aembed_before_replace(documents, self.embedder)
        documents = retrievable_documents(documents)
        self._require_owner_column(user_id)
        try:
            if self.content_hash_exists(content_hash, user_id=user_id):
                self._delete_by_content_hash(content_hash, user_id=user_id)
            await self._async_upsert(content_hash, documents, filters, batch_size, user_id=user_id)
        except Exception as e:
            log_error(f"Error upserting documents by content hash: {str(e)}")
            raise

    async def _async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        user_id: Optional[str] = None,
    ) -> None:
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    try:
                        await self._async_embed_documents(batch_docs, prepared=True)
                        batch_docs = retrievable_documents(batch_docs)
                        batch_records_dict: Dict[str, Dict[str, Any]] = {}
                        for doc in batch_docs:
                            try:
                                record = self._get_document_record(doc, filters, content_hash, user_id, prepared=True)
                                batch_records_dict[record["id"]] = record
                            except Exception as e:
                                log_error(f"Error processing document '{doc.name}': {str(e)}")

                        batch_records = [r for r in batch_records_dict.values() if r.get("embedding")]
                        if not batch_records:
                            log_info("No valid records to upsert in this batch.")
                            continue

                        with sess.begin():
                            merge_upsert_many(
                                sess, self.table, ["id"], batch_records, preserve_on_conflict=["created_at"]
                            )
                        log_info(f"Upserted batch of {len(batch_records)} documents.")
                    except Exception as e:
                        log_error(f"Error with batch starting at index {i}: {str(e)}")
                        sess.rollback()
                        raise
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    # -- Metadata update: per-row shallow merge, matching PgVector's ||
    # exactly (an explicit null in the incoming dict overwrites, never
    # deletes the key -- unlike RFC 7396 JSON_MERGEPATCH semantics, which
    # would delete on null and so is not used here). --

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        try:
            with self.Session() as sess, sess.begin():
                rows = sess.execute(
                    select(self.table.c.id, self.table.c.meta_data).where(self.table.c.content_id == content_id)
                ).fetchall()
                for row in rows:
                    merged = {**(row.meta_data or {}), **metadata}
                    sess.execute(
                        self.table.update().where(self.table.c.id == row.id).values(meta_data=merged, filters=metadata)
                    )
        except Exception as e:
            log_error(f"Error updating metadata for document {content_id}: {str(e)}")
            raise

    # -- Search --

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        self._require_owner_column(user_id)
        return self.vector_search(query=query, limit=limit, filters=filters, user_id=user_id)

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters, user_id)

    def _apply_user_scope(self, stmt, user_id: Optional[str]):
        if user_id is None:
            return stmt
        self._require_owner_column(user_id)
        return stmt.where(or_(self.table.c.user_id == _to_db_user_id(user_id), self.table.c.user_id.is_(None)))

    def _apply_metadata_filter(self, stmt, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]):
        """Simple top-level key/value equality on ``meta_data``, sufficient for the
        common single-value RAG filter case. The FilterExpr DSL (AND/OR/NOT,
        comparison operators) is ticket 18's scope -- raise rather than silently
        ignore an expression this ticket does not evaluate.
        """
        if filters is None:
            return stmt
        if not isinstance(filters, dict):
            raise NotImplementedError(
                "FilterExpr-based metadata filtering is not yet implemented for OracleVector (ticket 18). "
                "Pass a plain dict of key/value equality filters, or None."
            )
        conditions = [
            func.json_value(self.table.c.meta_data, literal_column(_json_path_literal(key))) == str(value)
            for key, value in filters.items()
        ]
        return stmt.where(and_(*conditions))

    def vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Error getting embedding for Query: {query}")
                return []

            metric = _DISTANCE_METRIC.get(self.distance)
            if metric is None:
                log_error(f"Unknown distance metric: {self.distance}")
                return []
            assert self.dimensions is not None  # validated in __init__
            query_vec_param = bindparam("query_vec", query_embedding, type_=OracleVectorType(self.dimensions))
            distance_expr = func.vector_distance(self.table.c.embedding, query_vec_param, literal_column(metric))

            columns = [
                self.table.c.id,
                self.table.c.name,
                self.table.c.meta_data,
                self.table.c.content,
                self.table.c.embedding,
                self.table.c.usage,
                distance_expr.label("distance"),
            ]

            stmt = select(*columns)
            stmt = self._apply_user_scope(stmt, user_id)
            stmt = self._apply_metadata_filter(stmt, filters)

            if self.similarity_threshold is not None:
                distance_threshold = score_to_distance_threshold(self.similarity_threshold, self.distance)
                if self.distance == Distance.max_inner_product:
                    # VECTOR_DISTANCE(..., DOT) returns the negated inner product,
                    # the same convention pgvector's max_inner_product uses.
                    stmt = stmt.where(distance_expr <= -distance_threshold)
                else:
                    stmt = stmt.where(distance_expr <= distance_threshold)

            stmt = stmt.order_by(distance_expr).limit(limit)

            log_debug(f"Vector search query: {stmt}")

            try:
                with self.Session() as sess, sess.begin():
                    results = sess.execute(stmt).fetchall()
            except Exception as e:
                log_error(f"Error performing vector search: {str(e)}")
                log_error(f"Table might not exist, creating for future use: {str(e)}")
                self.create()
                return []

            search_results: List[Document] = []
            for result in results:
                raw_distance = -result.distance if self.distance == Distance.max_inner_product else result.distance
                similarity_score = normalize_score(raw_distance, self.distance)
                meta_data = dict(result.meta_data) if result.meta_data else {}
                meta_data["similarity_score"] = similarity_score

                search_results.append(
                    Document(
                        id=result.id,
                        name=result.name,
                        meta_data=meta_data,
                        content=result.content,
                        embedder=self.embedder,
                        embedding=result.embedding,
                        usage=result.usage,
                    )
                )

            if self.reranker:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results
        except EmbeddingError:
            raise
        except Exception as e:
            log_error(f"Error during vector search: {str(e)}")
            return []

    def keyword_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        raise NotImplementedError("Keyword search is not yet implemented for OracleVector (ticket 18).")

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        raise NotImplementedError("Hybrid search is not yet implemented for OracleVector (ticket 18).")

    # -- Lifecycle / introspection --

    def drop(self) -> None:
        if self.table_exists():
            try:
                log_debug(f"Dropping table '{self.table.fullname}'.")
                self.table.drop(self.db_engine)
                log_info(f"Table '{self.table.fullname}' dropped successfully.")
                self._owner_column_exists = None
            except Exception as e:
                log_error(f"Error dropping table '{self.table.fullname}': {str(e)}")
                raise
        else:
            log_info(f"Table '{self.table.fullname}' does not exist.")

    async def async_drop(self) -> None:
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        return self.table_exists()

    async def async_exists(self) -> bool:
        return await asyncio.to_thread(self.exists)

    def get_count(self) -> int:
        try:
            with self.Session() as sess, sess.begin():
                stmt = select(func.count(self.table.c.name)).select_from(self.table)
                result = sess.execute(stmt).scalar()
                return int(result) if result is not None else 0
        except Exception as e:
            log_error(f"Error getting count from table '{self.table.fullname}': {str(e)}")
            return 0

    # -- Delete --

    def delete(self) -> bool:
        from sqlalchemy import delete

        try:
            with self.Session() as sess:
                sess.execute(delete(self.table))
                sess.commit()
                log_info(f"Deleted all records from table '{self.table.fullname}'.")
                return True
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_id(self, id: str) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.id == id)
                result = sess.execute(stmt)
                sess.commit()
                log_info(f"Deleted records with id '{id}' from table '{self.table.fullname}'.")
                return bool(result.rowcount)
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_name(self, name: str) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.name == name)
                result = sess.execute(stmt)
                sess.commit()
                log_info(f"Deleted records with name '{name}' from table '{self.table.fullname}'.")
                return bool(result.rowcount)
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                conditions = [
                    func.json_value(self.table.c.meta_data, literal_column(_json_path_literal(key))) == str(value)
                    for key, value in metadata.items()
                ]
                stmt = self.table.delete().where(and_(*conditions))
                result = sess.execute(stmt)
                sess.commit()
                log_info(f"Deleted records with metadata '{metadata}' from table '{self.table.fullname}'.")
                return bool(result.rowcount)
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        self._require_owner_column(user_id)
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.content_id == content_id)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == _to_db_user_id(user_id))
                result = sess.execute(stmt)
                sess.commit()
                log_info(f"Deleted records with content ID '{content_id}' from table '{self.table.fullname}'.")
                return bool(result.rowcount)
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def _delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        scope_to_owner = self._require_owner_column(user_id)
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.content_hash == content_hash)
                if scope_to_owner:
                    if user_id is not None:
                        stmt = stmt.where(self.table.c.user_id == _to_db_user_id(user_id))
                    else:
                        stmt = stmt.where(self.table.c.user_id.is_(None))
                result = sess.execute(stmt)
                sess.commit()
                log_info(f"Deleted records with content hash '{content_hash}' from table '{self.table.fullname}'.")
                return bool(result.rowcount)
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def __deepcopy__(self, memo):
        from copy import deepcopy

        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        for k, v in self.__dict__.items():
            if k in {"metadata", "table"}:
                continue
            elif k in {"db_engine", "Session", "embedder"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        copied_obj.metadata = MetaData(schema=copied_obj.schema)
        copied_obj.table = copied_obj.get_table()
        return copied_obj

    def get_supported_search_types(self) -> List[str]:
        return [SearchType.vector]
