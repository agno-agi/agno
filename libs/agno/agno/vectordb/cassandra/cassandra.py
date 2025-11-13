import asyncio
from typing import Any, Dict, Iterable, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_error, log_info
from agno.vectordb.base import VectorDb
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable


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
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
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
            vector_dimension=1024,
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
        metadata = row["metadata"]
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

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if a document exists by content hash."""
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE metadata_s['content_hash'] = %s ALLOW FILTERING"
        result = self.session.execute(query, (content_hash,))
        return result.one()[0] > 0

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_info(f"Cassandra VectorDB : Inserting Documents to the table {self.table_name}")
        futures = []
        for doc in documents:
            doc.embed(embedder=self.embedder)
            metadata = {key: str(value) for key, value in doc.meta_data.items()}
            metadata.update(filters or {})
            metadata["content_id"] = doc.content_id or ""
            metadata["content_hash"] = content_hash
            futures.append(
                self.table.put_async(
                    row_id=doc.id,
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
                    for doc in documents:
                        try:
                            embed_tasks = [doc.async_embed(embedder=self.embedder)]
                            await asyncio.gather(*embed_tasks, return_exceptions=True)
                        except Exception as e:
                            log_error(f"Error processing document '{doc.name}': {e}")
        else:
            # Use individual embedding (original behavior)
            for doc in documents:
                try:
                    embed_tasks = [doc.async_embed(embedder=self.embedder)]
                    await asyncio.gather(*embed_tasks, return_exceptions=True)
                except Exception as e:
                    log_error(f"Error processing document '{doc.name}': {e}")

        futures = []
        for doc in documents:
            metadata = {key: str(value) for key, value in doc.meta_data.items()}
            metadata.update(filters or {})
            metadata["content_id"] = doc.content_id or ""
            metadata["content_hash"] = content_hash
            futures.append(
                self.table.put_async(
                    row_id=doc.id,
                    vector=doc.embedding,
                    metadata=metadata or {},
                    body_blob=doc.content,
                    document_name=doc.name,
                )
            )

        for f in futures:
            f.result()

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert or update documents based on primary key."""
        if self.content_hash_exists(content_hash):
            self.delete_by_content_hash(content_hash)
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents asynchronously by running in a thread."""
        if self.content_hash_exists(content_hash):
            self.delete_by_content_hash(content_hash)
        await self.async_insert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Keyword-based search on document metadata."""
        log_debug(f"Cassandra VectorDB : Performing Vector Search on {self.table_name} with query {query}")
        return self.vector_search(query=query, limit=limit)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def _search_to_documents(
        self,
        hits: Iterable[Dict[str, Any]],
    ) -> List[Document]:
        return [self._row_to_document(row=hit) for hit in hits]

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Vector similarity search implementation."""
        query_embedding = self.embedder.get_embedding(query)
        hits = list(
            self.table.metric_ann_search(
                vector=query_embedding,
                n=limit,
                metric="cos",
            )
        )
        d = self._search_to_documents(hits)
        return d

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

    def delete_by_content_id(self, content_id: str) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id (str): The content ID to delete

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
                if row_metadata.get("content_id") == content_id:
                    # Delete this specific document
                    delete_query = f"DELETE FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
                    self.session.execute(delete_query, (getattr(row, "row_id"),))
                    deleted_count += 1

            return deleted_count > 0
        except Exception as e:
            log_info(f"Error deleting documents with content_id {content_id}: {e}")
            return False

    def delete_by_content_hash(self, content_hash: str) -> bool:
        """
        Delete documents by content hash.

        Args:
            content_hash (str): The content hash to delete

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
                if row_metadata.get("content_hash") == content_hash:
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
                    updated_metadata = row_metadata.copy()
                    # Convert new metadata values to strings (Cassandra requirement)
                    string_metadata = {key: str(value) for key, value in metadata.items()}
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
            log_error(f"Error updating metadata for content_id {content_id}: {e}")
            raise

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # Cassandra doesn't use SearchType enum
