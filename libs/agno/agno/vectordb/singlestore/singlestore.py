import asyncio
import json
from hashlib import md5
from typing import Any, Dict, List, Optional, Union

try:
    from sqlalchemy.dialects import mysql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import func, select, text, update
    from sqlalchemy.types import DateTime
except ImportError:
    raise ImportError("`sqlalchemy` not installed")

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class SingleStore(VectorDb):
    def __init__(
        self,
        collection: str,
        schema: Optional[str] = "ai",
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        reranker: Optional[Reranker] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        # index: Optional[Union[Ivfflat, HNSW]] = HNSW(),
    ):
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)

        if _engine is None:
            raise ValueError("Must provide either db_url or db_engine")

        self.collection: str = collection
        self.schema: Optional[str] = schema
        self.db_url: Optional[str] = db_url
        # Initialize base class with name and description
        super().__init__(name=name, description=description)

        self.db_engine: Engine = _engine
        self.metadata: MetaData = MetaData(schema=self.schema)
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        self.distance: Distance = distance
        # self.index: Optional[Union[Ivfflat, HNSW]] = index
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)
        self.reranker: Optional[Reranker] = reranker
        self.table: Table = self.get_table()

    def get_table(self) -> Table:
        """
        Define the table structure.

        Returns:
            Table: SQLAlchemy Table object.
        """
        return Table(
            self.collection,
            self.metadata,
            Column("id", mysql.TEXT),
            Column("name", mysql.TEXT),
            Column("meta_data", mysql.TEXT),
            Column("content", mysql.TEXT),
            Column("embedding", mysql.TEXT),  # Placeholder for the vector column
            Column("usage", mysql.TEXT),
            Column("created_at", DateTime(timezone=True), server_default=text("now()")),
            Column("updated_at", DateTime(timezone=True), onupdate=text("now()")),
            Column("content_hash", mysql.TEXT),
            Column("content_id", mysql.TEXT),
            extend_existing=True,
        )

    def create(self) -> None:
        """
        Create the table if it does not exist.
        """
        if not self.table_exists():
            log_info(f"Creating table: {self.collection}")
            with self.db_engine.connect() as connection:
                connection.execute(
                    text(f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.{self.collection} (
                        id TEXT,
                        name TEXT,
                        meta_data TEXT,
                        content TEXT,
                        embedding VECTOR({self.dimensions}) NOT NULL,
                        `usage` TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        content_hash TEXT,
                        content_id TEXT
                    );
                    """)
                )
            # Call optimize to create indexes
            self.optimize()

    def table_exists(self) -> bool:
        """
        Check if the table exists.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        log_debug(f"Checking if table exists: {self.table.name}")
        try:
            return inspect(self.db_engine).has_table(self.table.name, schema=self.schema)
        except Exception as e:
            log_error(e)
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """
        Validating if the document exists or not

        Args:
            document (Document): Document to validate
        """
        with self.Session.begin() as sess:
            stmt = select(self.table.c.name).where(self.table.c.content_hash == content_hash)
            result = sess.execute(stmt).first()
            return result is not None

    def name_exists(self, name: str) -> bool:
        """
        Validate if a row with this name exists or not

        Args:
            name (str): Name to check
        """
        with self.Session.begin() as sess:
            stmt = select(self.table.c.name).where(self.table.c.name == name)
            result = sess.execute(stmt).first()
            return result is not None

    def id_exists(self, id: str) -> bool:
        """
        Validate if a row with this id exists or not

        Args:
            id (str): Id to check
        """
        with self.Session.begin() as sess:
            stmt = select(self.table.c.id).where(self.table.c.id == id)
            result = sess.execute(stmt).first()
            return result is not None

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 10,
    ) -> None:
        """
        Insert documents into the table.

        Args:
            documents (List[Document]): List of documents to insert.
            filters (Optional[Dict[str, Any]]): Optional filters for the insert.
            batch_size (int): Number of documents to insert in each batch.
        """
        with self.Session.begin() as sess:
            counter = 0
            for document in documents:
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                # Include content_hash in ID to ensure uniqueness across different content hashes
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
                _id = record_id

                meta_data_json = json.dumps(document.meta_data)
                usage_json = json.dumps(document.usage)

                # Convert embedding list to SingleStore VECTOR format
                embeddings = f"[{','.join(map(str, document.embedding))}]" if document.embedding else None

                stmt = mysql.insert(self.table).values(
                    id=_id,
                    name=document.name,
                    meta_data=meta_data_json,
                    content=cleaned_content,
                    embedding=embeddings,
                    usage=usage_json,
                    content_hash=content_hash,
                    content_id=document.content_id,
                )
                sess.execute(stmt)
                counter += 1
                log_debug(f"Inserted document: {document.name} ({document.meta_data})")

            sess.commit()
            log_debug(f"Committed {counter} documents")

    def upsert_available(self) -> bool:
        """Indicate that upsert functionality is available."""
        return True

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 20,
    ) -> None:
        if self.content_hash_exists(content_hash):
            self._delete_by_content_hash(content_hash)
        self._upsert(content_hash=content_hash, documents=documents, filters=filters, batch_size=batch_size)

    def _upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 20,
    ) -> None:
        """
        Upsert (insert or update) documents in the table.

        Args:
            documents (List[Document]): List of documents to upsert.
            filters (Optional[Dict[str, Any]]): Optional filters for the upsert.
            batch_size (int): Number of documents to upsert in each batch.
        """
        with self.Session.begin() as sess:
            counter = 0
            for document in documents:
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                # Include content_hash in ID to ensure uniqueness across different content hashes
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
                _id = record_id

                meta_data_json = json.dumps(document.meta_data)
                usage_json = json.dumps(document.usage)

                # Convert embedding list to SingleStore VECTOR format
                embeddings = f"[{','.join(map(str, document.embedding))}]" if document.embedding else None
                stmt = (
                    mysql.insert(self.table)
                    .values(
                        id=_id,
                        name=document.name,
                        meta_data=meta_data_json,
                        content=cleaned_content,
                        embedding=embeddings,
                        usage=usage_json,
                        content_hash=content_hash,
                        content_id=document.content_id,
                    )
                    .on_duplicate_key_update(
                        name=document.name,
                        meta_data=meta_data_json,
                        content=cleaned_content,
                        embedding=embeddings,
                        usage=usage_json,
                        content_hash=content_hash,
                        content_id=document.content_id,
                    )
                )
                sess.execute(stmt)
                counter += 1
                log_debug(f"Upserted document: {document.name} ({document.meta_data})")

            sess.commit()
            log_debug(f"Committed {counter} documents")

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        """
        Search for documents based on a query and optional filters.

        Args:
            query (str): The search query.
            limit (int): The maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Optional filters for the search.

        Returns:
            List[Document]: List of documents that match the query.
        """
        if filters is not None:
            log_warning("Filters are not supported in SingleStore. No filters will be applied.")
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            log_error(f"Error getting embedding for Query: {query}")
            return []

        columns = [
            self.table.c.name,
            self.table.c.meta_data,
            self.table.c.content,
            self.table.c.embedding,
            self.table.c.usage,
            self.table.c.content_id,
        ]

        stmt = select(*columns)

        # if filters is not None:
        #     for key, value in filters.items():
        #         if hasattr(self.table.c, key):
        #             stmt = stmt.where(getattr(self.table.c, key) == value)

        if self.distance == Distance.l2:
            stmt = stmt.order_by(self.table.c.embedding.max_inner_product(query_embedding))
        if self.distance == Distance.cosine:
            embeddings = json.dumps(query_embedding)
            dot_product_expr = func.dot_product(self.table.c.embedding, text(":embedding"))
            stmt = stmt.order_by(dot_product_expr.desc())
            stmt = stmt.params(embedding=embeddings)
            # stmt = stmt.order_by(self.table.c.embedding.cosine_distance(query_embedding))
        if self.distance == Distance.max_inner_product:
            stmt = stmt.order_by(self.table.c.embedding.max_inner_product(query_embedding))

        stmt = stmt.limit(limit=limit)
        log_debug(f"Query: {stmt}")

        # Get neighbors
        # This will only work if embedding column is created with `vector` data type.
        with self.Session.begin() as sess:
            sess.execute(text("SET vector_type_project_format = JSON"))
            neighbors = sess.execute(stmt).fetchall() or []
            #         if self.index is not None:
            #             if isinstance(self.index, Ivfflat):
            #                 # Assuming 'nprobe' is a relevant parameter to be set for the session
            #                 # Update the session settings based on the Ivfflat index configuration
            #                 sess.execute(text(f"SET SESSION nprobe = {self.index.nprobe}"))
            #             elif isinstance(self.index, HNSWFlat):
            #                 # Assuming 'ef_search' is a relevant parameter to be set for the session
            #                 # Update the session settings based on the HNSW index configuration
            #                 sess.execute(text(f"SET SESSION ef_search = {self.index.ef_search}"))

        # Build search results
        search_results: List[Document] = []
        for neighbor in neighbors:
            meta_data_dict = json.loads(neighbor.meta_data) if neighbor.meta_data else {}
            usage_dict = json.loads(neighbor.usage) if neighbor.usage else {}

            # Convert SingleStore VECTOR type to list
            embedding_list = []
            if neighbor.embedding:
                try:
                    embedding_list = json.loads(neighbor.embedding)
                except Exception as e:
                    log_error(f"Error extracting vector: {e}")
                    embedding_list = []

            search_results.append(
                Document(
                    name=neighbor.name,
                    meta_data=meta_data_dict,
                    content=neighbor.content,
                    embedder=self.embedder,
                    embedding=embedding_list,
                    usage=usage_dict,
                )
            )

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

    def drop(self) -> None:
        """
        Delete the table.
        """
        if self.table_exists():
            log_debug(f"Deleting table: {self.collection}")
            self.table.drop(self.db_engine)

    def exists(self) -> bool:
        """
        Check if the table exists.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        return self.table_exists()

    def get_count(self) -> int:
        """
        Get the count of rows in the table.

        Returns:
            int: The count of rows.
        """
        with self.Session.begin() as sess:
            stmt = select(func.count(self.table.c.name)).select_from(self.table)
            result = sess.execute(stmt).scalar()
            if result is not None:
                return int(result)
            return 0

    def optimize(self) -> None:
        pass

    def delete(self) -> bool:
        """
        Clear all rows from the table.

        Returns:
            bool: True if the table was cleared, False otherwise.
        """
        from sqlalchemy import delete

        with self.Session.begin() as sess:
            stmt = delete(self.table)
            sess.execute(stmt)
            return True

    def delete_by_id(self, id: str) -> bool:
        """
        Delete a document by its ID.
        """
        from sqlalchemy import delete

        try:
            with self.Session.begin() as sess:
                stmt = delete(self.table).where(self.table.c.id == id)
                result = sess.execute(stmt)  # type: ignore
                log_info(f"Deleted {result.rowcount} records with ID {id} from table '{self.table.name}'.")  # type: ignore
                return result.rowcount > 0  # type: ignore
        except Exception as e:
            log_error(f"Error deleting document with ID {id}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """
        Delete a document by its content ID.
        """
        from sqlalchemy import delete

        try:
            with self.Session.begin() as sess:
                stmt = delete(self.table).where(self.table.c.content_id == content_id)
                result = sess.execute(stmt)  # type: ignore
                log_info(
                    f"Deleted {result.rowcount} records with content_id {content_id} from table '{self.table.name}'."  # type: ignore
                )
                return result.rowcount > 0  # type: ignore
        except Exception as e:
            log_error(f"Error deleting document with content_id {content_id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """
        Delete a document by its name.
        """
        from sqlalchemy import delete

        try:
            with self.Session.begin() as sess:
                stmt = delete(self.table).where(self.table.c.name == name)
                result = sess.execute(stmt)  # type: ignore
                log_info(f"Deleted {result.rowcount} records with name '{name}' from table '{self.table.name}'.")  # type: ignore
                return result.rowcount > 0  # type: ignore
        except Exception as e:
            log_error(f"Error deleting document with name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata.
        """
        from sqlalchemy import delete

        try:
            with self.Session.begin() as sess:
                # Convert metadata to JSON string for comparison
                metadata_json = json.dumps(metadata, sort_keys=True)
                stmt = delete(self.table).where(self.table.c.meta_data == metadata_json)
                result = sess.execute(stmt)  # type: ignore
                log_info(f"Deleted {result.rowcount} records with metadata {metadata} from table '{self.table.name}'.")  # type: ignore
                return result.rowcount > 0  # type: ignore
        except Exception as e:
            log_error(f"Error deleting documents with metadata {metadata}: {e}")
            return False

    async def async_create(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            # Use batch embedding when enabled and supported
            try:
                # Extract content from all documents
                doc_contents = [doc.content for doc in documents]

                # Get batch embeddings and usage
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                # Process documents with pre-computed embeddings
                for j, doc in enumerate(documents):
                    try:
                        if j < len(embeddings):
                            doc.embedding = embeddings[j]
                            doc.usage = usages[j] if j < len(usages) else None
                    except Exception as e:
                        log_error(f"Error assigning batch embedding to document '{doc.name}': {e}")

            except Exception as e:
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding. {e}")
                    raise e
                else:
                    log_error(f"Async batch embedding failed, falling back to individual embeddings: {e}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            await asyncio.gather(*embed_tasks, return_exceptions=True)

        with self.Session.begin() as sess:
            counter = 0
            for document in documents:
                cleaned_content = document.content.replace("\x00", "\ufffd")
                # Include content_hash in ID to ensure uniqueness across different content hashes
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
                _id = record_id

                meta_data_json = json.dumps(document.meta_data)
                usage_json = json.dumps(document.usage)

                # Convert embedding list to SingleStore VECTOR format
                embeddings = f"[{','.join(map(str, document.embedding))}]" if document.embedding else None

                stmt = mysql.insert(self.table).values(
                    id=_id,
                    name=document.name,
                    meta_data=meta_data_json,
                    content=cleaned_content,
                    embedding=embeddings,
                    usage=usage_json,
                    content_hash=content_hash,
                    content_id=document.content_id,
                )
                sess.execute(stmt)
                counter += 1
                log_debug(f"Inserted document: {document.name} ({document.meta_data})")

            sess.commit()
            log_debug(f"Committed {counter} documents")

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Upsert (insert or update) documents in the table.

        Args:
            documents (List[Document]): List of documents to upsert.
            filters (Optional[Dict[str, Any]]): Optional filters for the upsert.
            batch_size (int): Number of documents to upsert in each batch.
        """

        if self.embedder.enable_batch and hasattr(self.embedder, "async_get_embeddings_batch_and_usage"):
            # Use batch embedding when enabled and supported
            try:
                # Extract content from all documents
                doc_contents = [doc.content for doc in documents]

                # Get batch embeddings and usage
                embeddings, usages = await self.embedder.async_get_embeddings_batch_and_usage(doc_contents)

                # Process documents with pre-computed embeddings
                for j, doc in enumerate(documents):
                    try:
                        if j < len(embeddings):
                            doc.embedding = embeddings[j]
                            doc.usage = usages[j] if j < len(usages) else None
                    except Exception as e:
                        log_error(f"Error assigning batch embedding to document '{doc.name}': {e}")

            except Exception as e:
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding. {e}")
                    raise e
                else:
                    log_error(f"Async batch embedding failed, falling back to individual embeddings: {e}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
        else:
            # Use individual embedding
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            await asyncio.gather(*embed_tasks, return_exceptions=True)

        with self.Session.begin() as sess:
            counter = 0
            for document in documents:
                cleaned_content = document.content.replace("\x00", "\ufffd")
                # Include content_hash in ID to ensure uniqueness across different content hashes
                base_id = document.id or md5(cleaned_content.encode()).hexdigest()
                record_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
                _id = record_id

                meta_data_json = json.dumps(document.meta_data)
                usage_json = json.dumps(document.usage)

                # Convert embedding list to SingleStore VECTOR format
                embeddings = f"[{','.join(map(str, document.embedding))}]" if document.embedding else None
                stmt = (
                    mysql.insert(self.table)
                    .values(
                        id=_id,
                        name=document.name,
                        meta_data=meta_data_json,
                        content=cleaned_content,
                        embedding=embeddings,
                        usage=usage_json,
                        content_hash=content_hash,
                        content_id=document.content_id,
                    )
                    .on_duplicate_key_update(
                        name=document.name,
                        meta_data=meta_data_json,
                        content=cleaned_content,
                        embedding=embeddings,
                        usage=usage_json,
                        content_hash=content_hash,
                        content_id=document.content_id,
                    )
                )
                sess.execute(stmt)
                counter += 1
                log_debug(f"Upserted document: {document.name} ({document.meta_data})")

            sess.commit()
            log_debug(f"Committed {counter} documents")

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        return self.search(query=query, limit=limit, filters=filters)

    async def async_drop(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_exists(self) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """
        Delete documents by their content hash.

        Args:
            content_hash (str): The content hash to delete.

        Returns:
            bool: True if documents were deleted, False otherwise.
        """
        from sqlalchemy import delete

        try:
            with self.Session.begin() as sess:
                stmt = delete(self.table).where(self.table.c.content_hash == content_hash)
                result = sess.execute(stmt)  # type: ignore
                log_info(
                    f"Deleted {result.rowcount} records with content_hash '{content_hash}' from table '{self.table.name}'."  # type: ignore
                )
                return result.rowcount > 0  # type: ignore
        except Exception as e:
            log_error(f"Error deleting documents with content_hash {content_hash}: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        import json

        try:
            with self.Session.begin() as sess:
                # Find documents with the given content_id
                stmt = select(self.table).where(self.table.c.content_id == content_id)
                result = sess.execute(stmt)  # type: ignore

                updated_count = 0
                for row in result:
                    # Parse existing metadata
                    current_metadata = json.loads(row.meta_data) if row.meta_data else {}

                    # Merge existing metadata with new metadata
                    updated_metadata = current_metadata.copy()
                    updated_metadata.update(metadata)

                    # Also update filters field within the metadata JSON
                    if "filters" not in updated_metadata:
                        updated_metadata["filters"] = {}
                    if isinstance(updated_metadata["filters"], dict):
                        updated_metadata["filters"].update(metadata)
                    else:
                        updated_metadata["filters"] = metadata

                    # Update the document (only meta_data column exists)
                    update_stmt = (
                        update(self.table)
                        .where(self.table.c.id == row.id)
                        .values(meta_data=json.dumps(updated_metadata))
                    )
                    sess.execute(update_stmt)
                    updated_count += 1

                if updated_count == 0:
                    log_debug(f"No documents found with content_id: {content_id}")
                else:
                    log_debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            log_error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # SingleStore doesn't use SearchType enum
