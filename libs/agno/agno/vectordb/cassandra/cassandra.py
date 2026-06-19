import asyncio
from hashlib import md5
from typing import Any, Dict, Iterable, List, Optional, Union

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable

# Per-user isolation. cassio's metadata filter is equality/AND only, so the owner is a
# reserved metadata key (shared rows get an explicit sentinel) and "own OR shared" is
# served by merging two equality-filtered ANN searches.
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
        self.initialize_table()

    def initialize_table(self):
        self.table = AgnoMetadataVectorCassandraTable(
            session=self.session,
            keyspace=self.keyspace,
            vector_dimension=self.embedder.dimensions or 1024,
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

    def _owner_value(self, user_id: Optional[str]) -> str:
        """The value stored under metadata_s['user_id']; shared rows get the
        explicit sentinel so the shared-bucket query can match them by equality.
        """
        return user_id if user_id else SHARED_USER_ID_VALUE

    def _row_id(self, doc: Document, content_hash: str, user_id: Optional[str]) -> str:
        """Deterministic primary key. Folds in the owner so two users' copies of
        the same content_hash get distinct row ids; shared rows keep doc.id.
        """
        base_id = doc.id or md5((doc.content or "").encode()).hexdigest()
        if user_id:
            return md5(f"{base_id}_{content_hash}_{user_id}".encode()).hexdigest()
        return base_id

    def _build_metadata(
        self, doc: Document, content_hash: str, filters: Optional[Dict[str, Any]], user_id: Optional[str]
    ) -> Dict[str, str]:
        """Assemble the metadata map for a write, stamping the owner.

        Caller-supplied user_id (in meta_data or filters) is stripped so a
        caller cannot spoof ownership.
        """
        metadata = {key: str(value) for key, value in doc.meta_data.items() if key != USER_ID_METADATA_KEY}
        if filters:
            metadata.update({k: str(v) for k, v in filters.items() if k != USER_ID_METADATA_KEY})
        metadata["content_id"] = doc.content_id or ""
        metadata["content_hash"] = content_hash
        metadata[USER_ID_METADATA_KEY] = self._owner_value(user_id)
        return metadata

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

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a document exists by content hash.

        When user_id is set the check is scoped to the owner's bucket, so an
        upsert dedupes only the caller's own stale chunks.
        """
        if user_id is not None:
            query = (
                f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} "
                "WHERE metadata_s['content_hash'] = %s AND metadata_s['user_id'] = %s ALLOW FILTERING"
            )
            result = self.session.execute(query, (content_hash, user_id))
        else:
            query = (
                f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} "
                "WHERE metadata_s['content_hash'] = %s ALLOW FILTERING"
            )
            result = self.session.execute(query, (content_hash,))
        return result.one()[0] > 0

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        log_info(f"Cassandra VectorDB : Inserting Documents to the table {self.table_name}")
        futures = []
        for doc in documents:
            doc.embed(embedder=self.embedder)
            metadata = self._build_metadata(doc, content_hash, filters, user_id)
            futures.append(
                self.table.put_async(
                    row_id=self._row_id(doc, content_hash, user_id),
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
                # Check if this is a rate limit error - don't fall back as it would make things worse
                error_str = str(e).lower()
                is_rate_limit = any(
                    phrase in error_str
                    for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
                )

                if is_rate_limit:
                    log_error(f"Rate limit detected during batch embedding.: {str(e)}")
                    raise e
                else:
                    log_error(f"Async batch embedding failed, falling back to individual embeddings: {str(e)}")
                    # Fall back to individual embedding
                    for doc in documents:
                        try:
                            embed_tasks = [doc.async_embed(embedder=self.embedder)]
                            await asyncio.gather(*embed_tasks, return_exceptions=True)
                        except Exception as e:
                            log_error(f"Error processing document '{doc.name}': {str(e)}")
        else:
            # Use individual embedding (original behavior)
            for doc in documents:
                try:
                    embed_tasks = [doc.async_embed(embedder=self.embedder)]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
                except Exception as e:
                    log_error(f"Error processing document '{doc.name}': {str(e)}")

        futures = []
        for doc in documents:
            metadata = self._build_metadata(doc, content_hash, filters, user_id)
            futures.append(
                self.table.put_async(
                    row_id=self._row_id(doc, content_hash, user_id),
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
        # Scope the dedupe-delete to the owner bucket (the __shared__ sentinel for None).
        owner = self._owner_value(user_id)
        if self.content_hash_exists(content_hash, user_id=owner):
            self.delete_by_content_hash(content_hash, user_id=owner)
        self.insert(content_hash, documents, filters, user_id=user_id)

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Upsert documents asynchronously by running in a thread."""
        # Scope the dedupe to the owner bucket (the __shared__ sentinel for None);
        # see the sync upsert for why.
        owner = self._owner_value(user_id)
        if self.content_hash_exists(content_hash, user_id=owner):
            self.delete_by_content_hash(content_hash, user_id=owner)
        await self.async_insert(content_hash, documents, filters, user_id=user_id)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Keyword-based search on document metadata."""
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

    def _ann_search(self, vector: List[float], limit: int, owner: Optional[str]) -> List[Dict[str, Any]]:
        """One metadata-filtered ANN search. owner is the exact
        metadata_s['user_id'] to match, or None for an unfiltered search.
        """
        kwargs: Dict[str, Any] = {"vector": vector, "n": limit, "metric": "cos"}
        if owner is not None:
            kwargs["metadata"] = {USER_ID_METADATA_KEY: owner}
        return list(self.table.metric_ann_search(**kwargs))

    def vector_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """Vector similarity search implementation.

        Scope contract:
        * user_id set  -> own OR shared (merge two equality-filtered searches).
        * user_id=None -> one unfiltered search; admin sees everything.
        """
        query_embedding = self.embedder.get_embedding(query)

        if user_id is None:
            hits = self._ann_search(query_embedding, limit, owner=None)
            return self._search_to_documents(hits)

        # Own OR shared: union two equality-filtered searches. Each branch asks
        # for limit so the merged top-k is correct.
        own_hits = self._ann_search(query_embedding, limit, owner=user_id)
        shared_hits = self._ann_search(query_embedding, limit, owner=SHARED_USER_ID_VALUE)
        merged = self._merge_hits(own_hits, shared_hits, limit)
        return self._search_to_documents(merged)

    def _merge_hits(
        self, own_hits: List[Dict[str, Any]], shared_hits: List[Dict[str, Any]], limit: int
    ) -> List[Dict[str, Any]]:
        """Merge two ANN result lists into one top-k: dedupe by row id and
        re-sort by cosine distance descending (cassio's cos metric is reversed:
        higher == more similar).
        """
        seen: set = set()
        combined: List[Dict[str, Any]] = []
        for hit in [*own_hits, *shared_hits]:
            row_id = hit.get("row_id")
            if row_id in seen:
                continue
            seen.add(row_id)
            combined.append(hit)
        combined.sort(key=lambda h: h.get("distance", 0.0), reverse=True)
        return combined[:limit]

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

        Per-user isolation contract:
        * user_id set  -> only the owner's chunks with this content_id.
        * user_id=None -> deletes across all owners (legacy / admin).

        Args:
            content_id (str): The content ID to delete
            user_id (Optional[str]): Restrict the delete to the owner's bucket.

        Returns:
            bool: True if documents were deleted, False otherwise
        """
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
                # Scope to the owner exactly when user_id is set.
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
            user_id (Optional[str]): Restrict the delete to the owner's bucket so
                an upsert dedupes only the caller's own stale chunks.

        Returns:
            bool: True if documents were deleted, False otherwise
        """
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
                if row_metadata.get("content_hash") != content_hash:
                    continue
                if user_id is not None and row_metadata.get(USER_ID_METADATA_KEY) != user_id:
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
                    # Merge existing metadata with new metadata. The driver hands
                    # back metadata_s as an ordered-map type, so copy into a
                    # plain dict before mutating.
                    updated_metadata = dict(row_metadata)
                    # Convert new metadata values to strings (Cassandra requirement).
                    # user_id is the reserved owner key; never let caller metadata reassign it.
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
