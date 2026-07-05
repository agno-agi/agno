import asyncio
import json
import time
from hashlib import md5
from typing import Any, Dict, List, Optional, Set, Union

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning, logger
from agno.utils.string import generate_id
from agno.utils.turso import create_turso_engine
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

try:
    from sqlalchemy import bindparam
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install using `pip install sqlalchemy`")


# libSQL/Turso distance functions keyed by our Distance enum.
_DISTANCE_FUNCTIONS = {
    Distance.cosine: "vector_distance_cos",
    Distance.l2: "vector_distance_l2",
}


class TursoVector(VectorDb):
    """Vector store backed by Turso native vector search (via the ``pyturso`` driver).

    Turso is a from-scratch, SQLite-compatible database that supports vector
    similarity search natively through the ``vector32()`` constructor and
    ``vector_distance_cos`` / ``vector_distance_l2`` functions (no extension
    required). Vectors are stored in a ``BLOB`` column.

    Note: the current Turso engine does not implement SQLite FTS5, so only
    ``vector`` search is supported (no keyword / hybrid search), and it does not
    expose an ANN vector index, so search is exact (full-scan).

    Args:
        table_name: Name of the table to store vector data.
        db_file: Local Turso database file path.
        db_engine: A pre-built SQLAlchemy engine to use.
        embedder: Embedder used to embed document contents (defaults to OpenAIEmbedder).
        search_type: Search type to use (only ``vector`` is supported).
        distance: Distance metric for vector comparisons (cosine or l2).
        reranker: Optional reranker applied to search results.
        similarity_threshold: Minimum similarity (0.0-1.0) to keep a result (cosine only).
        name: Optional name for the vector database.
        description: Optional description for the vector database.
        id: Optional custom ID.
    """

    def __init__(
        self,
        table_name: str,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        distance: Distance = Distance.cosine,
        reranker: Optional[Reranker] = None,
        similarity_threshold: Optional[float] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
    ):
        if not table_name:
            raise ValueError("Table name must be provided.")

        if id is None:
            base_seed = db_file or (str(db_engine.url) if db_engine else "sqlite+turso:///agno.db")
            id = generate_id(f"{base_seed}#{table_name}")

        super().__init__(id=id, name=name, description=description, similarity_threshold=similarity_threshold)

        # Build the Turso engine if one was not provided.
        if db_engine is None:
            db_engine = create_turso_engine(db_file=db_file)

        self.table_name: str = table_name
        self.db_file: Optional[str] = db_file
        self.db_engine: Engine = db_engine

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions
        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")

        if search_type != SearchType.vector:
            log_warning(
                f"TursoVector only supports vector search (Turso has no FTS5). "
                f"Ignoring search_type '{search_type}' and using vector search."
            )
        self.search_type: SearchType = SearchType.vector
        self.distance: Distance = distance
        self.reranker: Optional[Reranker] = reranker

        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

        log_debug(f"Initialized TursoVector with table '{self.table_name}'")

    # -- Helpers ------------------------------------------------------------

    def _distance_function(self) -> str:
        """Return the Turso distance function name for the configured metric."""
        func = _DISTANCE_FUNCTIONS.get(self.distance)
        if func is None:
            log_warning(f"Distance '{self.distance}' is not supported by Turso. Falling back to cosine.")
            return _DISTANCE_FUNCTIONS[Distance.cosine]
        return func

    @staticmethod
    def _clean_content(content: str) -> str:
        return content.replace("\x00", "�")

    def _get_document_record(
        self, content_hash: str, document: Document, filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build a row dict for a document, embedding it if needed."""
        if filters:
            meta_data = document.meta_data.copy() if document.meta_data else {}
            meta_data.update(filters)
            document.meta_data = meta_data

        if document.embedding is None or (isinstance(document.embedding, list) and len(document.embedding) == 0):
            document.embed(embedder=self.embedder)

        cleaned_content = self._clean_content(document.content)
        base_id = document.id or md5(cleaned_content.encode()).hexdigest()
        doc_id = str(md5(f"{base_id}_{content_hash}".encode()).hexdigest())
        now = int(time.time())
        return {
            "id": doc_id,
            "name": document.name,
            "meta_data": json.dumps(document.meta_data or {}),
            "content": cleaned_content,
            "embedding": json.dumps([float(x) for x in (document.embedding or [])]),
            "usage": json.dumps(document.usage) if document.usage else None,
            "content_id": document.content_id,
            "content_hash": content_hash,
            "created_at": now,
            "updated_at": now,
        }

    def _build_search_results(self, rows: List[Dict[str, Any]]) -> List[Document]:
        search_results: List[Document] = []
        try:
            for row in rows:
                meta_data = json.loads(row["meta_data"]) if row.get("meta_data") else {}
                usage = json.loads(row["usage"]) if row.get("usage") else None
                search_results.append(
                    Document(
                        name=row.get("name"),
                        meta_data=meta_data,
                        content=row.get("content") or "",
                        embedder=self.embedder,
                        usage=usage,
                        content_id=row.get("content_id"),
                    )
                )
        except Exception:
            logger.exception("Error building search results")
        return search_results

    # -- Lifecycle ----------------------------------------------------------

    def create(self) -> None:
        """Create the vector table if it does not exist."""
        if self.exists():
            return
        with self.Session() as sess, sess.begin():
            log_info(f"Creating table: {self.table_name}")
            sess.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {self.table_name} ("
                    "id TEXT PRIMARY KEY, "
                    "name TEXT, "
                    "meta_data TEXT, "
                    "content TEXT, "
                    "embedding BLOB, "
                    "usage TEXT, "
                    "content_id TEXT, "
                    "content_hash TEXT, "
                    "created_at INTEGER, "
                    "updated_at INTEGER)"
                )
            )
            sess.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_content_hash ON {self.table_name}(content_hash)"
                )
            )
            sess.execute(
                text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_content_id ON {self.table_name}(content_id)")
            )

    async def async_create(self) -> None:
        await asyncio.to_thread(self.create)

    def exists(self) -> bool:
        try:
            with self.Session() as sess:
                result = sess.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name = :name LIMIT 1"),
                    {"name": self.table_name},
                ).first()
                return result is not None
        except Exception as e:
            log_error(f"Error checking if table exists: {str(e)}")
            return False

    async def async_exists(self) -> bool:
        return await asyncio.to_thread(self.exists)

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Dropping table: {self.table_name}")
            with self.Session() as sess, sess.begin():
                sess.execute(text(f"DROP TABLE IF EXISTS {self.table_name}"))

    async def async_drop(self) -> None:
        await asyncio.to_thread(self.drop)

    def get_count(self) -> int:
        if not self.exists():
            return 0
        try:
            with self.Session() as sess:
                result = sess.execute(text(f"SELECT COUNT(*) FROM {self.table_name}")).scalar()
                return int(result) if result is not None else 0
        except Exception as e:
            log_error(f"Error getting count: {str(e)}")
            return 0

    def optimize(self) -> None:
        # The current Turso engine does not expose an ANN vector index
        # (no libsql_vector_idx / vector_top_k); vector search is exact (full-scan).
        log_debug("TursoVector.optimize() is a no-op: Turso has no ANN vector index yet.")

    def delete(self) -> bool:
        return False

    # -- Existence checks ---------------------------------------------------

    def _record_exists(self, column: str, value: str) -> bool:
        if not self.exists():
            return False
        try:
            with self.Session() as sess:
                result = sess.execute(
                    text(f"SELECT 1 FROM {self.table_name} WHERE {column} = :value LIMIT 1"),
                    {"value": value},
                ).first()
                return result is not None
        except Exception as e:
            log_error(f"Error checking if record exists: {str(e)}")
            return False

    def name_exists(self, name: str) -> bool:
        return self._record_exists("name", name)

    async def async_name_exists(self, name: str) -> bool:
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        return self._record_exists("id", id)

    def content_hash_exists(self, content_hash: str) -> bool:
        return self._record_exists("content_hash", content_hash)

    # -- Insert / Upsert ----------------------------------------------------

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        if len(documents) <= 0:
            log_info("No documents to insert")
            return
        if not self.exists():
            self.create()

        records = []
        for document in documents:
            try:
                records.append(self._get_document_record(content_hash, document, filters))
            except Exception as e:
                log_error(f"Error processing document '{document.name}': {str(e)}")

        if not records:
            log_debug("No new data to insert")
            return

        insert_stmt = text(
            f"INSERT INTO {self.table_name} "
            "(id, name, meta_data, content, embedding, usage, content_id, content_hash, created_at, updated_at) "
            "VALUES (:id, :name, :meta_data, :content, vector32(:embedding), :usage, :content_id, :content_hash, "
            ":created_at, :updated_at)"
        )
        try:
            with self.Session() as sess, sess.begin():
                sess.execute(insert_stmt, records)
            log_info(f"Inserted {len(records)} documents")
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await asyncio.to_thread(self.insert, content_hash, documents, filters)

    def upsert_available(self) -> bool:
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        self.insert(content_hash=content_hash, documents=documents, filters=filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await asyncio.to_thread(self.upsert, content_hash, documents, filters)

    # -- Search -------------------------------------------------------------

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        if not self.exists():
            log_error("Table not initialized")
            return []

        if isinstance(filters, list):
            log_warning("Filter Expressions are not yet supported in TursoVector. No filters will be applied.")
            filters = None

        search_results = self.vector_search(query, limit)

        # Filter results based on metadata if filters are provided
        if filters and search_results:
            filtered_results = []
            for doc in search_results:
                if doc.meta_data is None:
                    continue
                if all(key in doc.meta_data and doc.meta_data[key] == value for key, value in filters.items()):
                    filtered_results.append(doc)
            search_results = filtered_results

        if self.reranker and search_results:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        # Deduplicate by content
        seen_hashes: Set[str] = set()
        unique_results: List[Document] = []
        for doc in search_results:
            doc_hash = md5(doc.content.encode()).hexdigest()
            if doc_hash not in seen_hashes:
                seen_hashes.add(doc_hash)
                unique_results.append(doc)

        log_info(f"Found {len(unique_results)} documents")
        return unique_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        distance_fn = self._distance_function()
        stmt = text(
            f"SELECT id, name, meta_data, content, usage, content_id, "
            f"{distance_fn}(embedding, vector32(:qvec)) AS distance "
            f"FROM {self.table_name} ORDER BY distance ASC LIMIT :limit"
        )
        try:
            with self.Session() as sess:
                result = sess.execute(stmt, {"qvec": json.dumps([float(x) for x in query_embedding]), "limit": limit})
                rows = [dict(row) for row in result.mappings().all()]
        except Exception:
            logger.exception("Error during vector search")
            return []

        # For cosine, similarity = 1 - distance; apply the optional threshold.
        if self.similarity_threshold is not None and self.distance == Distance.cosine:
            rows = [r for r in rows if (1.0 - float(r["distance"])) >= self.similarity_threshold]

        return self._build_search_results(rows)

    def get_supported_search_types(self) -> List[str]:
        return [SearchType.vector]

    # -- Deletes ------------------------------------------------------------

    def _delete_where(self, where_sql: str, params: Dict[str, Any], label: str) -> bool:
        if not self.exists():
            log_error("Table not initialized")
            return False
        try:
            with self.Session() as sess, sess.begin():
                result = sess.execute(text(f"DELETE FROM {self.table_name} WHERE {where_sql}"), params)
                deleted = result.rowcount or 0
            if deleted:
                log_info(f"Deleted {deleted} records for {label} from '{self.table_name}'.")
                return True
            log_info(f"No records found for {label} to delete.")
            return False
        except Exception:
            logger.exception(f"Error deleting rows for {label}")
            return False

    def delete_by_id(self, id: str) -> bool:
        return self._delete_where("id = :value", {"value": id}, f"id '{id}'")

    def delete_by_name(self, name: str) -> bool:
        return self._delete_where("name = :value", {"value": name}, f"name '{name}'")

    def delete_by_content_id(self, content_id: str) -> bool:
        return self._delete_where("content_id = :value", {"value": content_id}, f"content_id '{content_id}'")

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        return self._delete_where("content_hash = :value", {"value": content_hash}, f"content_hash '{content_hash}'")

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete content by metadata (matched in Python against the stored JSON)."""
        if not self.exists():
            log_error("Table not initialized")
            return False
        try:
            with self.Session() as sess, sess.begin():
                rows = sess.execute(text(f"SELECT id, meta_data FROM {self.table_name}")).mappings().all()
                ids_to_delete = []
                for row in rows:
                    doc_meta = json.loads(row["meta_data"]) if row["meta_data"] else {}
                    if all(key in doc_meta and doc_meta[key] == value for key, value in metadata.items()):
                        ids_to_delete.append(row["id"])
                if not ids_to_delete:
                    log_info(f"No records found with metadata '{metadata}' to delete.")
                    return False
                del_stmt = text(f"DELETE FROM {self.table_name} WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                sess.execute(del_stmt, {"ids": ids_to_delete})
            log_info(f"Deleted {len(ids_to_delete)} records with metadata '{metadata}' from '{self.table_name}'.")
            return True
        except Exception:
            logger.exception(f"Error deleting rows by metadata '{metadata}'")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """Merge new metadata into all documents with the given content_id."""
        if not self.exists():
            log_error("Table not initialized")
            return
        try:
            with self.Session() as sess, sess.begin():
                rows = (
                    sess.execute(
                        text(f"SELECT id, meta_data FROM {self.table_name} WHERE content_id = :cid"),
                        {"cid": content_id},
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    log_debug(f"No documents found with content_id: {content_id}")
                    return
                for row in rows:
                    current_meta = json.loads(row["meta_data"]) if row["meta_data"] else {}
                    current_meta.update(metadata)
                    sess.execute(
                        text(f"UPDATE {self.table_name} SET meta_data = :meta WHERE id = :id"),
                        {"meta": json.dumps(current_meta), "id": row["id"]},
                    )
            log_debug(f"Updated metadata for {len(rows)} documents with content_id: {content_id}")
        except Exception:
            logger.exception(f"Error updating metadata for content_id '{content_id}'")
            raise
