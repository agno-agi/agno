import asyncio
from hashlib import md5
from typing import Any, Dict, Iterable, List, Optional, Union

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb, aembed_before_replace, embed_before_replace, is_rate_limit_error, raise_embedding_failures
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable

# The owner lives in a reserved metadata key. cassio filters metadata by equality only, so
# shared rows carry an explicit sentinel rather than no value.
USER_ID_METADATA_KEY = "user_id"
SHARED_USER_ID_VALUE = "__shared__"


class Cassandra(VectorDb):
    def __init__(
        self,
        table_name: str,
        keyspace: str,
        embedder: Optional[Embedder] = None,
        session=None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        if not table_name:
            raise ValueError("Table name must be provided.")

        if not session:
            raise ValueError("Session is not provided")

        if not keyspace:
            raise ValueError("Keyspace must be provided")

        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        # Initialize base class with name and description
        super().__init__(name=name, description=description)

        self.table_name: str = table_name
        self.embedder: Embedder = embedder
        self.session = session
        self.keyspace: str = keyspace
        self.dimensions: Optional[int] = self.embedder.dimensions
        if self.dimensions is None:
            raise ValueError("Embedder.dimensions must be set.")
        self.initialize_table()

        # Whether the table has migrated rows with user_id; resolved lazily and cached
        self._owner_field_exists: Optional[bool] = None

    def initialize_table(self):
        self.table = AgnoMetadataVectorCassandraTable(
            session=self.session,
            keyspace=self.keyspace,
            vector_dimension=self.dimensions,
            table=self.table_name,
            primary_key_type="TEXT",
        )

    def create(self) -> None:
        """Create the table in Cassandra for storing vectors and metadata."""
        if not self.exists():
            log_debug(f"Cassandra VectorDB : Creating table {self.table_name}")
            self.initialize_table()

    async def async_create(self) -> None:
        """Create the table asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

    def _row_to_document(self, row: Dict[str, Any]) -> Document:
        # user_id is a reserved key; never surface it as caller-visible metadata.
        metadata = {k: v for k, v in row["metadata"].items() if k != USER_ID_METADATA_KEY}
        return Document(
            id=row["row_id"],
            content=row["body_blob"],
            meta_data=metadata,
            embedding=row["vector"],
            name=row["document_name"],
            content_id=metadata.get("content_id"),
        )

    def name_exists(self, name: str) -> bool:
        """Check if a document exists by name."""
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE document_name = %s ALLOW FILTERING"
        result = self.session.execute(query, (name,))
        return result.one()[0] > 0

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        """Check if a document exists by ID."""
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE row_id = %s ALLOW FILTERING"
        result = self.session.execute(query, (id,))
        return result.one()[0] > 0

    def _validate_user_id(self, user_id: Optional[str]) -> None:
        """Reject a user_id that collides with the shared sentinel; use None for shared access."""
        if user_id == SHARED_USER_ID_VALUE:
            raise ValueError(
                f"user_id must not be '{SHARED_USER_ID_VALUE}' - that value is reserved to mark content "
                "shared with every user"
            )

    def _table_has_user_id_field(self) -> Optional[bool]:
        """Check if the table has ANY rows with user_id in metadata_s.

        Follows the Redis pattern: check if the store supports the field at all,
        not whether every row has it. If at least one row has user_id, the table
        is considered migrated (v3-compatible).

        Empty tables return True - no v2 data to protect against.

        Returns True if any row has user_id or table is empty, False if rows exist
        without user_id, None on error.
        """
        try:
            # 1. Check if table has any rows at all (LIMIT 1 for efficiency)
            any_row_query = f"SELECT row_id FROM {self.keyspace}.{self.table_name} LIMIT 1"
            any_row_result = self.session.execute(any_row_query)
            if not list(any_row_result):
                # Empty table - no v2 data to worry about
                return True

            # 2. Check if ANY row has user_id key
            query = (
                f"SELECT row_id FROM {self.keyspace}.{self.table_name} "
                f"WHERE metadata_s CONTAINS KEY '{USER_ID_METADATA_KEY}' LIMIT 1 ALLOW FILTERING"
            )
            result = self.session.execute(query)
            rows = list(result)
            return len(rows) > 0
        except Exception:
            return None

    def _user_id_field_exists(self) -> bool:
        """Cached check for whether the table has any rows with user_id."""
        if self._owner_field_exists is None:
            answer = self._table_has_user_id_field()
            if answer is None:
                log_warning(
                    f"Could not inspect Cassandra table '{self.table_name}' for the "
                    f"'{USER_ID_METADATA_KEY}' field; proceeding as migrated for this operation."
                )
                return True
            self._owner_field_exists = answer
        return self._owner_field_exists

    def _require_owner_field(self, user_id: Optional[str]) -> bool:
        """Gate scoped operations on whether the table has migrated rows.

        Returns True when the field exists, False when missing and unscoped.
        Raises on a scoped call against an unmigrated table.
        """
        if self._user_id_field_exists():
            return True
        if user_id is None:
            return False
        # Re-inspect once in case the table was migrated
        self._owner_field_exists = None
        if self._user_id_field_exists():
            return True
        raise ValueError(
            f"user_id={user_id!r} was passed but Cassandra table '{self.table_name}' has rows "
            f"without the '{USER_ID_METADATA_KEY}' metadata key. Run the v2 -> v3 migration "
            "(libs/agno/migrations/v2_to_v3/migrate_sentinel_vectordbs.py) to backfill user_id."
        )

    def _scoped_row_id(self, base_id: str, content_hash: str, user_id: Optional[str]) -> str:
        """Fold the owner into the deterministic row id so two users inserting the same content
        get distinct rows. ``base_id`` is digested first so a shifting ``_`` boundary can't collide.
        """
        row_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()
        if user_id is None:
            return row_id
        return md5(f"{row_id}_{user_id}".encode()).hexdigest()

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document exists by content hash, scoped to the owner. ``None`` scopes to the
        shared bucket only, never another user's owned row.
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        owner = user_id if user_id is not None else SHARED_USER_ID_VALUE
        query = (
            f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} "
            f"WHERE metadata_s['content_hash'] = %s AND metadata_s['{USER_ID_METADATA_KEY}'] = %s ALLOW FILTERING"
        )
        result = self.session.execute(query, (content_hash, owner))
        return result.one()[0] > 0

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        log_info(f"Cassandra VectorDB : Inserting Documents to the table {self.table_name}")
        futures = []
        for doc in documents:
            doc.embed(embedder=self.embedder)
            metadata = {key: str(value) for key, value in doc.meta_data.items()}
            metadata.update({key: str(value) for key, value in (filters or {}).items()})
            metadata["content_id"] = doc.content_id or ""
            metadata["content_hash"] = content_hash
            metadata[USER_ID_METADATA_KEY] = user_id if user_id is not None else SHARED_USER_ID_VALUE
            cleaned_content = (doc.content or "").replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
            futures.append(
                self.table.put_async(
                    row_id=self._scoped_row_id(base_id, content_hash, user_id),
                    vector=doc.embedding,
                    metadata=metadata or {},
                    body_blob=doc.content,
                    document_name=doc.name,
                )
            )

        for f in futures:
            f.result()

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert documents asynchronously by running in a thread."""
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        log_info(f"Cassandra VectorDB : Inserting Documents to the table {self.table_name}")

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
                        log_error(f"Error assigning batch embedding to document '{doc.name}': {str(e)}")

            except Exception as e:
                # A throttle must not fall back to per-item calls, which would throttle harder.
                is_rate_limit = is_rate_limit_error(e)

                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding.: {str(e)}")
                    raise e
                else:
                    log_error(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
                    results = await asyncio.gather(*embed_tasks, return_exceptions=True)
                    raise_embedding_failures(results)
        else:
            # Use individual embedding (original behavior)
            embed_tasks = [doc.async_embed(embedder=self.embedder) for doc in documents]
            results = await asyncio.gather(*embed_tasks, return_exceptions=True)
            raise_embedding_failures(results)

        futures = []
        for doc in documents:
            metadata = {key: str(value) for key, value in doc.meta_data.items()}
            metadata.update({key: str(value) for key, value in (filters or {}).items()})
            metadata["content_id"] = doc.content_id or ""
            metadata["content_hash"] = content_hash
            metadata[USER_ID_METADATA_KEY] = user_id if user_id is not None else SHARED_USER_ID_VALUE
            cleaned_content = (doc.content or "").replace("\x00", "\ufffd")
            # Include content_hash in ID to ensure uniqueness across different content hashes
            base_id = doc.id or md5(cleaned_content.encode()).hexdigest()
            futures.append(
                self.table.put_async(
                    row_id=self._scoped_row_id(base_id, content_hash, user_id),
                    vector=doc.embedding,
                    metadata=metadata or {},
                    body_blob=doc.content,
                    document_name=doc.name,
                )
            )

        for f in futures:
            f.result()

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Insert or update documents based on primary key."""
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        embed_before_replace(documents, self.embedder)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self.delete_by_content_hash(content_hash, user_id=user_id)
        self.insert(content_hash, documents, filters, user_id=user_id)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents asynchronously by running in a thread."""
        # Embed before the delete below: clearing the old chunks first would destroy
        # retrievable content if the embedder then fails.
        await aembed_before_replace(documents, self.embedder)
        if self.content_hash_exists(content_hash, user_id=user_id):
            self.delete_by_content_hash(content_hash, user_id=user_id)
        await self.async_insert(content_hash, documents, filters, user_id=user_id)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Keyword-based search on document metadata."""
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        log_debug(f"Cassandra VectorDB : Performing Vector Search on {self.table_name} with query {query}")
        if filters is not None:
            log_warning("Filters are not yet supported in Cassandra. No filters will be applied.")
        return self.vector_search(query=query, limit=limit, user_id=user_id)

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters, user_id)

    def _search_to_documents(
        self,
        hits: Iterable[Dict[str, Any]],
    ) -> List[Document]:
        return [self._row_to_document(row=hit) for hit in hits]

    def vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Vector similarity search implementation."""
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        query_embedding = self.embedder.get_embedding(query)

        if user_id is None:
            # Unscoped: one unfiltered search sees every owner.
            hits = list(self.table.metric_ann_search(vector=query_embedding, n=limit, metric="cos"))
            return self._search_to_documents(hits)

        # Equality-only filters, so union own + shared and re-rank the merged top-k
        # (cos distance is reversed: higher == more similar).
        own_hits = list(
            self.table.metric_ann_search(
                vector=query_embedding, n=limit, metric="cos", metadata={USER_ID_METADATA_KEY: user_id}
            )
        )
        shared_hits = list(
            self.table.metric_ann_search(
                vector=query_embedding, n=limit, metric="cos", metadata={USER_ID_METADATA_KEY: SHARED_USER_ID_VALUE}
            )
        )
        seen: set = set()
        merged: List[Dict[str, Any]] = []
        for hit in sorted([*own_hits, *shared_hits], key=lambda h: h.get("distance", 0.0), reverse=True):
            row_id = hit.get("row_id")
            if row_id in seen:
                continue
            seen.add(row_id)
            merged.append(hit)
        return self._search_to_documents(merged[:limit])

    def drop(self) -> None:
        """Drop the vector table in Cassandra."""
        log_debug(f"Cassandra VectorDB : Dropping Table {self.table_name}")
        drop_table_query = f"DROP TABLE IF EXISTS {self.keyspace}.{self.table_name}"
        self.session.execute(drop_table_query)

    async def async_drop(self) -> None:
        """Drop the table asynchronously by running in a thread."""
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        """Check if the table exists in Cassandra."""
        check_table_query = """
        SELECT * FROM system_schema.tables
        WHERE keyspace_name = %s AND table_name = %s
        """
        result = self.session.execute(check_table_query, (self.keyspace, self.table_name))
        return bool(result.one())

    async def async_exists(self) -> bool:
        """Check if table exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.exists)

    def delete(self) -> bool:
        """Delete all documents in the table."""
        log_debug(f"Cassandra VectorDB : Clearing the table {self.table_name}")
        self.table.clear()
        return True

    def delete_by_id(self, id: str) -> bool:
        """
        Delete a document by its ID.

        Args:
            id (str): The document ID to delete

        Returns:
            bool: True if document was deleted, False otherwise
        """
        try:
            log_debug(f"Cassandra VectorDB : Deleting document with ID {id}")
            # Check if document exists before deletion
            if not self.id_exists(id):
                return False

            query = f"DELETE FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
            self.session.execute(query, (id,))
            return True
        except Exception as e:
            log_info(f"Error deleting document with ID {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """
        Delete documents by name.

        Args:
            name (str): The document name to delete

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Cassandra VectorDB : Deleting documents with name {name}")
            # Check if document exists before deletion
            if not self.name_exists(name):
                return False

            # Query to find documents with matching name
            query = f"SELECT row_id, document_name FROM {self.keyspace}.{self.table_name} ALLOW FILTERING"
            result = self.session.execute(query)

            deleted_count = 0
            for row in result:
                # Check if the row's document_name matches our criteria
                # Use attribute access for Row objects
                row_name = getattr(row, "document_name", None)
                if row_name == name:
                    # Delete this specific document
                    delete_query = f"DELETE FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
                    self.session.execute(delete_query, (getattr(row, "row_id"),))
                    deleted_count += 1

            return deleted_count > 0
        except Exception as e:
            log_info(f"Error deleting documents with name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata.

        Args:
            metadata (Dict[str, Any]): The metadata to match for deletion

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        try:
            log_debug(f"Cassandra VectorDB : Deleting documents with metadata {metadata}")
            # For metadata deletion, we need to query first to find matching documents
            # Then delete them by their IDs
            query = f"SELECT row_id, metadata_s FROM {self.keyspace}.{self.table_name} ALLOW FILTERING"
            result = self.session.execute(query)

            deleted_count = 0
            for row in result:
                # Check if the row's metadata matches our criteria
                # Use attribute access for Row objects
                row_metadata = getattr(row, "metadata_s", {})
                if self._metadata_matches(row_metadata, metadata):
                    # Delete this specific document
                    delete_query = f"DELETE FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
                    self.session.execute(delete_query, (getattr(row, "row_id"),))
                    deleted_count += 1

            return deleted_count > 0
        except Exception as e:
            log_debug(f"Error deleting documents with metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id (str): The content ID to delete
            user_id (Optional[str]): Restrict the delete to this owner. ``None`` deletes every owner's rows.

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        try:
            log_debug(f"Cassandra VectorDB : Deleting documents with content_id {content_id}")
            # Query to find documents with matching content_id in metadata
            query = f"SELECT row_id, metadata_s FROM {self.keyspace}.{self.table_name} ALLOW FILTERING"
            result = self.session.execute(query)
            deleted_count = 0
            for row in result:
                # Check if the row's metadata contains the content_id
                # Use attribute access for Row objects
                row_metadata = getattr(row, "metadata_s", {})
                if row_metadata.get("content_id") != content_id:
                    continue
                if user_id is not None and row_metadata.get(USER_ID_METADATA_KEY) != user_id:
                    continue
                # Delete this specific document
                delete_query = f"DELETE FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
                self.session.execute(delete_query, (getattr(row, "row_id"),))
                deleted_count += 1

            return deleted_count > 0
        except Exception as e:
            log_info(f"Error deleting documents with content_id {content_id}: {e}")
            return False

    def delete_by_content_hash(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Delete documents by content hash.

        Args:
            content_hash (str): The content hash to delete
            user_id (Optional[str]): Restrict the delete to this owner. ``None`` clears the shared bucket only.

        Returns:
            bool: True if documents were deleted, False otherwise
        """
        self._validate_user_id(user_id)
        self._require_owner_field(user_id)
        owner = user_id if user_id is not None else SHARED_USER_ID_VALUE
        try:
            log_debug(f"Cassandra VectorDB : Deleting documents with content_hash {content_hash}")
            # Query to find documents with matching content_hash in metadata
            query = f"SELECT row_id, metadata_s FROM {self.keyspace}.{self.table_name} ALLOW FILTERING"
            result = self.session.execute(query)
            deleted_count = 0
            for row in result:
                # Check if the row's metadata contains the content_hash
                # Use attribute access for Row objects
                row_metadata = getattr(row, "metadata_s", {})
                if row_metadata.get("content_hash") == content_hash:
                    if row_metadata.get(USER_ID_METADATA_KEY) != owner:
                        continue
                    # Delete this specific document
                    delete_query = f"DELETE FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
                    self.session.execute(delete_query, (getattr(row, "row_id"),))
                    deleted_count += 1

            return deleted_count > 0
        except Exception as e:
            log_info(f"Error deleting documents with content_hash {content_hash}: {e}")
            return False

    def _metadata_matches(self, row_metadata: Dict[str, Any], target_metadata: Dict[str, Any]) -> bool:
        """
        Check if row metadata matches target metadata criteria.

        Args:
            row_metadata (Dict[str, Any]): The metadata from the database row
            target_metadata (Dict[str, Any]): The target metadata to match against

        Returns:
            bool: True if metadata matches, False otherwise
        """
        try:
            for key, value in target_metadata.items():
                if key not in row_metadata:
                    return False

                # Handle boolean values specially
                if isinstance(value, bool):
                    if row_metadata[key] != value:
                        return False
                else:
                    # For non-boolean values, convert to string for comparison
                    if row_metadata[key] != str(value):
                        return False
            return True
        except Exception:
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for a document.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            log_debug(f"Cassandra VectorDB : Updating metadata for content_id {content_id}")

            # First, find all documents with the given content_id
            query = f"SELECT row_id, metadata_s FROM {self.keyspace}.{self.table_name} ALLOW FILTERING"
            result = self.session.execute(query)

            updated_count = 0
            for row in result:
                row_metadata = getattr(row, "metadata_s", {})
                if row_metadata.get("content_id") == content_id:
                    # Merge existing metadata with new metadata
                    # metadata_s comes back as an ordered-map type, so copy into a plain dict
                    updated_metadata = dict(row_metadata)
                    # Convert new metadata values to strings (Cassandra requirement)
                    # user_id is reserved; never let caller metadata reassign it
                    string_metadata = {
                        key: str(value) for key, value in metadata.items() if key != USER_ID_METADATA_KEY
                    }
                    updated_metadata.update(string_metadata)

                    # Update the document with merged metadata
                    row_id = getattr(row, "row_id")
                    update_query = f"""
                        UPDATE {self.keyspace}.{self.table_name}
                        SET metadata_s = %s
                        WHERE row_id = %s
                    """
                    self.session.execute(update_query, (updated_metadata, row_id))
                    updated_count += 1

            if updated_count == 0:
                log_debug(f"No documents found with content_id {content_id}")
            else:
                log_debug(f"Updated metadata for {updated_count} documents with content_id {content_id}")

        except Exception as e:
            log_error(f"Error updating metadata for content_id {content_id}: {str(e)}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # Cassandra doesn't use SearchType enum
