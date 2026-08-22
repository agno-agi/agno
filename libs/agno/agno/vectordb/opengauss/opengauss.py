import asyncio
import re
from hashlib import md5
from math import sqrt
from typing import Any, Dict, List, Optional, Union, cast

from agno.utils.string import generate_id

try:
    from sqlalchemy import and_, not_, or_, update
    from sqlalchemy.dialects import postgresql, registry
    from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, scoped_session, sessionmaker
    from sqlalchemy.schema import Column, Index, MetaData, Table
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.expression import bindparam, desc, func, select, text
    from sqlalchemy.types import DateTime, Integer, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install using `pip install sqlalchemy psycopg`")

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    raise ImportError("`pgvector` not installed. Please install using `pip install pgvector`")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.opengauss.index import HNSW, Ivfflat
from agno.vectordb.score import normalize_score, score_to_distance_threshold
from agno.vectordb.search import SearchType


def parse_opengauss_version(version_string: str) -> Optional[tuple[int, int, int]]:
    """Extract a normalized 3-part version tuple from common openGauss version strings."""
    normalized = " ".join(version_string.split())
    patterns = [
        r"openGauss(?:-lite)?\s+[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?",
        r"openGauss(?:-lite)?[^\d]+(\d+)(?:\.(\d+))?(?:\.(\d+))?",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            major, minor, patch = match.groups()
            return int(major), int(minor or 0), int(patch or 0)

    if "opengauss" not in normalized.lower():
        return None

    fallback_match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", normalized)
    if fallback_match:
        major, minor, patch = fallback_match.groups()
        return int(major), int(minor), int(patch or 0)

    return None


class OpenGaussPsycopgDialect(PGDialect_psycopg):
    """SQLAlchemy psycopg dialect variant that understands openGauss version strings."""

    supports_statement_cache = True

    def _get_server_version_info(self, connection):
        version_string = connection.exec_driver_sql("select pg_catalog.version()").scalar()
        parsed_version = parse_opengauss_version(version_string)
        if parsed_version is not None:
            return parsed_version

        return super()._get_server_version_info(connection)


class OpenGaussVectorDb(VectorDb):
    """Standalone openGauss DataVec vector database adapter."""

    def __init__(
        self,
        table_name: str,
        schema: str = "ai",
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        vector_index: Union[Ivfflat, HNSW] = HNSW(),
        distance: Distance = Distance.cosine,
        prefix_match: bool = False,
        vector_score_weight: float = 0.5,
        content_language: str = "english",
        schema_version: int = 1,
        auto_upgrade_schema: bool = False,
        reranker: Optional[Reranker] = None,
        create_schema: bool = True,
        similarity_threshold: Optional[float] = None,
    ):
        if not table_name:
            raise ValueError("Table name must be provided.")

        if db_engine is None and db_url is None:
            raise ValueError("Either 'db_url' or 'db_engine' must be provided.")

        if id is None:
            if db_engine is None:
                base_seed = db_url
            else:
                base_seed = str(db_engine.url)
            schema_suffix = table_name if table_name is not None else "ai"
            seed = f"{base_seed}#{schema_suffix}"
            id = generate_id(seed)

        super().__init__(id=id, name=name, description=description, similarity_threshold=similarity_threshold)

        if db_engine is None:
            if db_url is None:
                raise ValueError("Must provide 'db_url' if 'db_engine' is None.")
            db_engine = self._create_opengauss_engine(db_url)

        self.table_name: str = table_name
        self.schema: str = schema
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

        self.search_type: SearchType = search_type
        self.distance: Distance = distance
        self.vector_index: Union[Ivfflat, HNSW] = vector_index
        self.prefix_match: bool = prefix_match
        self.vector_score_weight: float = vector_score_weight
        self.content_language: str = content_language

        self.schema_version: int = schema_version
        self.auto_upgrade_schema: bool = auto_upgrade_schema
        self.reranker: Optional[Reranker] = reranker
        self.create_schema: bool = create_schema

        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))
        self.table: Table = self.get_table()
        log_debug(f"Initialized OpenGaussVectorDb with table '{self.schema}.{self.table_name}'")

    @staticmethod
    def _validate_setting_key(key: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid openGauss setting key: {key}")
        return key

    @staticmethod
    def _sql_setting_value(value: Any) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, (int, float)):
            return str(value)

        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def _create_opengauss_engine(self, db_url: str) -> Engine:
        registry.register(
            "postgresql.opengauss_psycopg",
            "agno.vectordb.opengauss.opengauss",
            "OpenGaussPsycopgDialect",
        )
        parsed_url = make_url(db_url)
        if parsed_url.drivername.startswith("postgresql"):
            parsed_url = parsed_url.set(drivername="postgresql+opengauss_psycopg")
        return create_engine(parsed_url)

    def get_table_v1(self) -> Table:
        if self.dimensions is None:
            raise ValueError("Embedder dimensions are not set.")

        table = Table(
            self.table_name,
            self.metadata,
            Column("id", String, primary_key=True),
            Column("name", String),
            Column("meta_data", postgresql.JSONB, server_default=text("'{}'::jsonb")),
            Column("filters", postgresql.JSONB, server_default=text("'{}'::jsonb"), nullable=True),
            Column("content", postgresql.TEXT),
            Column("embedding", Vector(self.dimensions)),
            Column("usage", postgresql.JSONB),
            Column("created_at", DateTime(timezone=True), server_default=func.now()),
            Column("updated_at", DateTime(timezone=True), onupdate=func.now()),
            Column("content_hash", String),
            Column("content_id", String),
            extend_existing=True,
        )

        Index(f"idx_{self.table_name}_id", table.c.id)
        Index(f"idx_{self.table_name}_name", table.c.name)
        Index(f"idx_{self.table_name}_content_hash", table.c.content_hash)
        Index(f"idx_{self.table_name}_content_id", table.c.content_id)
        return table

    def get_table(self) -> Table:
        if self.schema_version == 1:
            return self.get_table_v1()
        raise NotImplementedError(f"Unsupported schema version: {self.schema_version}")

    def table_exists(self) -> bool:
        try:
            return inspect(self.db_engine).has_table(self.table_name, schema=self.schema)
        except Exception as e:
            log_error(f"Error checking if table exists: {str(e)}")
            return False

    def create(self) -> None:
        if not self.table_exists():
            with self.Session() as sess, sess.begin():
                if self.create_schema and self.schema is not None:
                    try:
                        log_debug(f"Creating schema: {self.schema}")
                        sess.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema};"))
                    except Exception as e:
                        log_warning(f"Could not create schema {self.schema}: {str(e)}")
            log_debug(f"Creating table: {self.table_name}")
            self.table.create(self.db_engine)

    async def async_create(self) -> None:
        await asyncio.to_thread(self.create)

    def _record_exists(self, column, value) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = select(1).where(column == value).limit(1)
                result = sess.execute(stmt).first()
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

    def content_hash_exists(self, content_hash: str) -> bool:
        return self._record_exists(self.table.c.content_hash, content_hash)

    def _clean_content(self, content: str) -> str:
        return content.replace("\x00", "\ufffd")

    def _get_document_record(
        self, doc: Document, filters: Optional[Dict[str, Any]] = None, content_hash: str = ""
    ) -> Dict[str, Any]:
        doc.embed(embedder=self.embedder)
        cleaned_content = self._clean_content(doc.content)
        base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
        record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

        meta_data = doc.meta_data or {}
        if filters:
            meta_data.update(filters)

        return {
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

    async def _async_embed_documents(self, batch_docs: List[Document]) -> None:
        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            try:
                doc_contents = [doc.content for doc in batch_docs]
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                for i, doc in enumerate(batch_docs):
                    if i < len(embeddings):
                        doc.embedding = embeddings[i]
                        doc.usage = usages[i] if i < len(usages) else None
            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )
                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding: {str(e)}")
                    raise
                log_warning(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                await asyncio.gather(*[doc.async_embed(embedder=self.embedder) for doc in batch_docs])
        else:
            await asyncio.gather(*[doc.async_embed(embedder=self.embedder) for doc in batch_docs])

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    batch_records: List[Dict[str, Any]] = []
                    for doc in batch_docs:
                        try:
                            batch_records.append(self._get_document_record(doc, filters, content_hash))
                        except Exception as e:
                            log_error(f"Error processing document '{doc.name}': {str(e)}")

                    if not batch_records:
                        continue

                    insert_stmt = postgresql.insert(self.table)
                    sess.execute(insert_stmt, batch_records)
                    sess.commit()
                    log_info(f"Inserted batch of {len(batch_records)} documents.")
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    await self._async_embed_documents(batch_docs)

                    batch_records: List[Dict[str, Any]] = []
                    for doc in batch_docs:
                        try:
                            cleaned_content = self._clean_content(doc.content)
                            base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
                            record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

                            meta_data = doc.meta_data or {}
                            if filters:
                                meta_data.update(filters)

                            batch_records.append(
                                {
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
                            )
                        except Exception as e:
                            log_error(f"Error processing document '{doc.name}': {str(e)}")

                    if not batch_records:
                        continue

                    insert_stmt = postgresql.insert(self.table)
                    sess.execute(insert_stmt, batch_records)
                    sess.commit()
                    log_info(f"Inserted batch of {len(batch_records)} documents.")
        except Exception as e:
            log_error(f"Error inserting documents: {str(e)}")
            raise

    def upsert_available(self) -> bool:
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        self._upsert(content_hash, documents, filters, batch_size)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        await self._async_upsert(content_hash, documents, filters, batch_size)

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    batch_records_dict: Dict[str, Dict[str, Any]] = {}
                    for doc in batch_docs:
                        try:
                            record = self._get_document_record(doc, filters, content_hash)
                            batch_records_dict[record["id"]] = record
                        except Exception as e:
                            log_error(f"Error processing document '{doc.name}': {str(e)}")

                    batch_records = list(batch_records_dict.values())
                    if not batch_records:
                        continue

                    # openGauss deployments may not support PostgreSQL ON CONFLICT in all configurations.
                    batch_ids = list(batch_records_dict.keys())
                    sess.execute(self.table.delete().where(self.table.c.id.in_(batch_ids)))

                    insert_stmt = postgresql.insert(self.table)
                    sess.execute(insert_stmt, batch_records)
                    sess.commit()
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    async def _async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> None:
        try:
            with self.Session() as sess:
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i : i + batch_size]
                    await self._async_embed_documents(batch_docs)

                    batch_records_dict: Dict[str, Dict[str, Any]] = {}
                    for doc in batch_docs:
                        try:
                            cleaned_content = self._clean_content(doc.content)
                            base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
                            record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

                            meta_data = doc.meta_data or {}
                            if filters:
                                meta_data.update(filters)

                            batch_records_dict[record_id] = {
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
                        except Exception as e:
                            log_error(f"Error processing document '{doc.name}': {str(e)}")

                    batch_records = list(batch_records_dict.values())
                    if not batch_records:
                        continue

                    # openGauss deployments may not support PostgreSQL ON CONFLICT in all configurations.
                    batch_ids = list(batch_records_dict.keys())
                    sess.execute(self.table.delete().where(self.table.c.id.in_(batch_ids)))

                    insert_stmt = postgresql.insert(self.table)
                    sess.execute(insert_stmt, batch_records)
                    sess.commit()
        except Exception as e:
            log_error(f"Error upserting documents: {str(e)}")
            raise

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        try:
            with self.Session() as sess:
                stmt = (
                    update(self.table)
                    .where(self.table.c.content_id == content_id)
                    .values(
                        meta_data=func.coalesce(self.table.c.meta_data, text("'{}'::jsonb")).op("||")(
                            bindparam("md", type_=postgresql.JSONB)
                        ),
                        filters=bindparam("ft", type_=postgresql.JSONB),
                    )
                )
                sess.execute(stmt, {"md": metadata, "ft": metadata})
                sess.commit()
        except Exception as e:
            log_error(f"Error updating metadata for document {content_id}: {str(e)}")
            raise

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        if self.search_type == SearchType.vector:
            return self.vector_search(query=query, limit=limit, filters=filters)
        if self.search_type == SearchType.keyword:
            return self.keyword_search(query=query, limit=limit, filters=filters)
        if self.search_type == SearchType.hybrid:
            return self.hybrid_search(query=query, limit=limit, filters=filters)

        log_error(f"Invalid search type '{self.search_type}'.")
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters)

    def _dsl_to_sqlalchemy(self, filter_expr, table) -> ColumnElement[bool]:
        op = filter_expr["op"]

        if op == "EQ":
            return table.c.meta_data[filter_expr["key"]].astext == str(filter_expr["value"])
        if op == "IN":
            return table.c.meta_data[filter_expr["key"]].astext.in_([str(v) for v in filter_expr["values"]])
        if op == "GT":
            return table.c.meta_data[filter_expr["key"]].astext.cast(Integer) > filter_expr["value"]
        if op == "LT":
            return table.c.meta_data[filter_expr["key"]].astext.cast(Integer) < filter_expr["value"]
        if op == "NOT":
            return not_(self._dsl_to_sqlalchemy(filter_expr["condition"], table))
        if op == "AND":
            return and_(*[self._dsl_to_sqlalchemy(cond, table) for cond in filter_expr["conditions"]])
        if op == "OR":
            return or_(*[self._dsl_to_sqlalchemy(cond, table) for cond in filter_expr["conditions"]])

        raise ValueError(f"Unknown filter operator: {op}")

    def _set_query_index_runtime_parameters(self, sess: Session) -> None:
        if self.vector_index is not None:
            if self._is_ivfflat_index(self.vector_index):
                ivfflat_index = cast(Ivfflat, self.vector_index)
                sess.execute(text(f"SET LOCAL ivfflat_probes = {int(ivfflat_index.probes)}"))
            elif self._is_hnsw_index(self.vector_index):
                hnsw_index = cast(HNSW, self.vector_index)
                sess.execute(text(f"SET LOCAL hnsw_ef_search = {int(hnsw_index.ef_search)}"))

    def _is_ivfflat_index(self, index: Any) -> bool:
        return hasattr(index, "probes") and hasattr(index, "lists")

    def _is_hnsw_index(self, index: Any) -> bool:
        return hasattr(index, "ef_search") and hasattr(index, "m")

    def _is_supported_index(self, index: Any) -> bool:
        return self._is_ivfflat_index(index) or self._is_hnsw_index(index)

    def vector_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Error getting embedding for query: {query}")
                return []

            if self.distance == Distance.l2:
                distance_expr = self.table.c.embedding.l2_distance(query_embedding)
            elif self.distance == Distance.cosine:
                distance_expr = self.table.c.embedding.cosine_distance(query_embedding)
            elif self.distance == Distance.max_inner_product:
                distance_expr = self.table.c.embedding.max_inner_product(query_embedding)
            else:
                log_error(f"Unknown distance metric: {self.distance}")
                return []

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

            if filters is not None:
                if isinstance(filters, dict):
                    stmt = stmt.where(self.table.c.meta_data.contains(filters))
                else:
                    sqlalchemy_conditions = [
                        self._dsl_to_sqlalchemy(f.to_dict() if hasattr(f, "to_dict") else f, self.table)
                        for f in filters
                    ]
                    stmt = stmt.where(and_(*sqlalchemy_conditions))

            if self.similarity_threshold is not None:
                distance_threshold = score_to_distance_threshold(self.similarity_threshold, self.distance)
                if self.distance == Distance.max_inner_product:
                    stmt = stmt.where(distance_expr <= -distance_threshold)
                else:
                    stmt = stmt.where(distance_expr <= distance_threshold)

            stmt = stmt.order_by(distance_expr).limit(limit)

            with self.Session() as sess, sess.begin():
                self._set_query_index_runtime_parameters(sess)
                results = sess.execute(stmt).fetchall()

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

            return search_results
        except Exception as e:
            log_error(f"Error during openGauss vector search: {str(e)}")
            return []

    def enable_prefix_matching(self, query: str) -> str:
        words = query.strip().split()
        processed_words = [word + "*" for word in words]
        return " ".join(processed_words)

    def _build_ts_query(self, processed_query: str):
        # websearch_to_tsquery is not available in many openGauss builds.
        if self.prefix_match:
            return func.to_tsquery(self.content_language, bindparam("query", value=processed_query))
        return func.plainto_tsquery(self.content_language, bindparam("query", value=processed_query))

    def keyword_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        try:
            columns = [
                self.table.c.id,
                self.table.c.name,
                self.table.c.meta_data,
                self.table.c.content,
                self.table.c.embedding,
                self.table.c.usage,
            ]

            stmt = select(*columns)
            ts_vector = func.to_tsvector(self.content_language, self.table.c.content)
            processed_query = self.enable_prefix_matching(query) if self.prefix_match else query
            ts_query = self._build_ts_query(processed_query)
            text_rank = func.ts_rank_cd(ts_vector, ts_query)

            if filters is not None:
                if isinstance(filters, dict):
                    stmt = stmt.where(self.table.c.meta_data.contains(filters))
                else:
                    sqlalchemy_conditions = [
                        self._dsl_to_sqlalchemy(f.to_dict() if hasattr(f, "to_dict") else f, self.table)
                        for f in filters
                    ]
                    stmt = stmt.where(and_(*sqlalchemy_conditions))

            stmt = stmt.order_by(text_rank.desc()).limit(limit)

            with self.Session() as sess, sess.begin():
                results = sess.execute(stmt).fetchall()

            search_results: List[Document] = []
            for result in results:
                search_results.append(
                    Document(
                        id=result.id,
                        name=result.name,
                        meta_data=result.meta_data,
                        content=result.content,
                        embedder=self.embedder,
                        embedding=result.embedding,
                        usage=result.usage,
                    )
                )
            return search_results
        except Exception as e:
            log_error(f"Error during keyword search: {str(e)}")
            return []

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    ) -> List[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Error getting embedding for query: {query}")
                return []

            columns = [
                self.table.c.id,
                self.table.c.name,
                self.table.c.meta_data,
                self.table.c.content,
                self.table.c.embedding,
                self.table.c.usage,
            ]

            ts_vector = func.to_tsvector(self.content_language, self.table.c.content)
            processed_query = self.enable_prefix_matching(query) if self.prefix_match else query
            ts_query = self._build_ts_query(processed_query)
            raw_text_rank = func.ts_rank_cd(ts_vector, ts_query)
            text_rank = raw_text_rank / (raw_text_rank + 0.1)

            if self.distance == Distance.l2:
                vector_distance = self.table.c.embedding.l2_distance(query_embedding)
                vector_score = 1 / (1 + vector_distance)
            elif self.distance == Distance.cosine:
                vector_distance = self.table.c.embedding.cosine_distance(query_embedding)
                vector_score = func.greatest(0.0, 1 - vector_distance)
            elif self.distance == Distance.max_inner_product:
                negative_ip = self.table.c.embedding.max_inner_product(query_embedding)
                inner_product = -negative_ip
                vector_score = func.greatest(0.0, func.least(1.0, (inner_product + 1) / 2))
            else:
                log_error(f"Unknown distance metric: {self.distance}")
                return []

            if not 0 <= self.vector_score_weight <= 1:
                raise ValueError("vector_score_weight must be between 0 and 1")

            text_rank_weight = 1 - self.vector_score_weight
            hybrid_score = (self.vector_score_weight * vector_score) + (text_rank_weight * text_rank)

            stmt = select(*columns, hybrid_score.label("hybrid_score"))

            if filters is not None:
                if isinstance(filters, dict):
                    stmt = stmt.where(self.table.c.meta_data.contains(filters))
                else:
                    sqlalchemy_conditions = [
                        self._dsl_to_sqlalchemy(f.to_dict() if hasattr(f, "to_dict") else f, self.table)
                        for f in filters
                    ]
                    stmt = stmt.where(and_(*sqlalchemy_conditions))

            if self.similarity_threshold is not None:
                stmt = stmt.where(hybrid_score >= self.similarity_threshold)

            stmt = stmt.order_by(desc("hybrid_score")).limit(limit)

            with self.Session() as sess, sess.begin():
                self._set_query_index_runtime_parameters(sess)
                results = sess.execute(stmt).fetchall()

            search_results: List[Document] = []
            for result in results:
                meta_data = dict(result.meta_data) if result.meta_data else {}
                meta_data["similarity_score"] = float(result.hybrid_score)
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

            return search_results
        except Exception as e:
            log_error(f"Error during openGauss hybrid search: {str(e)}")
            return []

    def drop(self) -> None:
        if self.table_exists():
            try:
                self.table.drop(self.db_engine)
            except Exception as e:
                log_error(f"Error dropping table '{self.table.fullname}': {str(e)}")
                raise

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

    def optimize(self, force_recreate: bool = False) -> None:
        self._create_vector_index(force_recreate=force_recreate)
        self._create_gin_index(force_recreate=force_recreate)

    def _index_exists(self, index_name: str) -> bool:
        inspector = inspect(self.db_engine)
        indexes = inspector.get_indexes(self.table.name, schema=self.schema)
        return any(idx["name"] == index_name for idx in indexes)

    def _drop_index(self, index_name: str) -> None:
        with self.Session() as sess, sess.begin():
            drop_index_sql = f'DROP INDEX IF EXISTS "{self.schema}"."{index_name}";'
            sess.execute(text(drop_index_sql))

    def _create_vector_index(self, force_recreate: bool = False) -> None:
        if self.vector_index is None:
            log_debug("No vector index specified, skipping vector index optimization.")
            return

        if not self._is_supported_index(self.vector_index):
            log_error(f"Unsupported vector index type for openGauss: {type(self.vector_index)}")
            return

        index_name = getattr(self.vector_index, "name", None)
        if index_name is None:
            index_type = "ivfflat" if self._is_ivfflat_index(self.vector_index) else "hnsw"
            index_name = f"{self.table_name}_{index_type}_index"
            self.vector_index.name = index_name

        index_distance = {
            Distance.l2: "vector_l2_ops",
            Distance.max_inner_product: "vector_ip_ops",
            Distance.cosine: "vector_cosine_ops",
        }.get(self.distance, "vector_cosine_ops")

        table_fullname = self.table.fullname
        vector_index_exists = self._index_exists(index_name)

        if vector_index_exists and not force_recreate:
            log_debug(f"Vector index '{index_name}' already exists, skipping.")
            return

        if vector_index_exists and force_recreate:
            self._drop_index(index_name)

        with self.Session() as sess, sess.begin():
            configuration = getattr(self.vector_index, "configuration", {})
            if configuration:
                for key, value in configuration.items():
                    safe_key = self._validate_setting_key(str(key))
                    safe_value = self._sql_setting_value(value)
                    sess.execute(text(f"SET {safe_key} = {safe_value}"))

            if self._is_ivfflat_index(self.vector_index):
                self._create_ivfflat_index(sess, table_fullname, index_distance)
            elif self._is_hnsw_index(self.vector_index):
                self._create_hnsw_index(sess, table_fullname, index_distance)

    def _create_ivfflat_index(self, sess: Session, table_fullname: str, index_distance: str) -> None:
        vector_index = cast(Ivfflat, self.vector_index)
        num_lists = vector_index.lists

        if vector_index.dynamic_lists:
            total_records = self.get_count()
            if total_records < 1000000:
                num_lists = max(int(total_records / 1000), 1)
            else:
                num_lists = max(int(sqrt(total_records)), 1)

        sess.execute(text(f"SET ivfflat_probes = {int(vector_index.probes)}"))
        create_index_sql = text(
            f'CREATE INDEX "{vector_index.name}" ON {table_fullname} '
            f"USING ivfflat (embedding {index_distance}) "
            f"WITH (lists = {int(num_lists)});"
        )
        sess.execute(create_index_sql)

    def _create_hnsw_index(self, sess: Session, table_fullname: str, index_distance: str) -> None:
        vector_index = cast(HNSW, self.vector_index)
        create_index_sql = text(
            f'CREATE INDEX "{vector_index.name}" ON {table_fullname} '
            f"USING hnsw (embedding {index_distance}) "
            f"WITH (m = {int(vector_index.m)}, ef_construction = {int(vector_index.ef_construction)});"
        )
        sess.execute(create_index_sql)

    def _create_gin_index(self, force_recreate: bool = False) -> None:
        gin_index_name = f"{self.table_name}_content_gin_index"

        gin_index_exists = self._index_exists(gin_index_name)
        if gin_index_exists and not force_recreate:
            return

        if gin_index_exists and force_recreate:
            self._drop_index(gin_index_name)

        with self.Session() as sess, sess.begin():
            language = self._sql_setting_value(self.content_language)
            create_gin_index_sql = text(
                f'CREATE INDEX "{gin_index_name}" ON {self.table.fullname} '
                f"USING GIN (to_tsvector({language}, content));"
            )
            sess.execute(create_gin_index_sql)

    def delete(self) -> bool:
        from sqlalchemy import delete

        try:
            with self.Session() as sess:
                sess.execute(delete(self.table))
                sess.commit()
                return True
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_id(self, id: str) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.id == id)
                sess.execute(stmt)
                sess.commit()
                return True
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_name(self, name: str) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.name == name)
                sess.execute(stmt)
                sess.commit()
                return True
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.meta_data.contains(metadata))
                sess.execute(stmt)
                sess.commit()
                return True
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.content_id == content_id)
                sess.execute(stmt)
                sess.commit()
                return True
        except Exception as e:
            log_error(f"Error deleting rows from table '{self.table.fullname}': {str(e)}")
            sess.rollback()
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        try:
            with self.Session() as sess, sess.begin():
                stmt = self.table.delete().where(self.table.c.content_hash == content_hash)
                sess.execute(stmt)
                sess.commit()
                return True
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
            if k in {"db_engine", "Session", "embedder"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        copied_obj.metadata = MetaData(schema=copied_obj.schema)
        copied_obj.table = copied_obj.get_table()

        return copied_obj

    def get_supported_search_types(self) -> List[str]:
        return [SearchType.vector, SearchType.keyword, SearchType.hybrid]
