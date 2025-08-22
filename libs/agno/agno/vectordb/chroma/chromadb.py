import asyncio
from hashlib import md5
from typing import Any, Dict, List, Mapping, Optional, Union, cast

try:
    from chromadb import Client as ChromaDbClient
    from chromadb import PersistentClient as PersistentChromaDbClient
    from chromadb.api.client import ClientAPI
    from chromadb.api.models.Collection import Collection
    from chromadb.api.types import QueryResult

except ImportError:
    raise ImportError("The `chromadb` package is not installed. Please install it via `pip install chromadb`.")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class ChromaDb(VectorDb):
    def __init__(
        self,
        collection: str,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        path: str = "tmp/chromadb",
        persistent_client: bool = False,
        reranker: Optional[Reranker] = None,
        **kwargs,
    ):
        # Collection attributes
        self.collection_name: str = collection

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        # Distance metric
        self.distance: Distance = distance

        # Chroma client instance
        self._client: Optional[ClientAPI] = None

        # Chroma collection instance
        self._collection: Optional[Collection] = None

        # Persistent Chroma client instance
        self.persistent_client: bool = persistent_client
        self.path: str = path

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Chroma client kwargs
        self.kwargs = kwargs

    @property
    def client(self) -> ClientAPI:
        if self._client is None:
            if not self.persistent_client:
                log_debug("Creating Chroma Client")
                self._client = ChromaDbClient(
                    **self.kwargs,
                )
            elif self.persistent_client:
                log_debug("Creating Persistent Chroma Client")
                self._client = PersistentChromaDbClient(
                    path=self.path,
                    **self.kwargs,
                )
        return self._client

    def create(self) -> None:
        """Create the collection in ChromaDb."""
        if self.exists():
            log_debug(f"Collection already exists: {self.collection_name}")
            self._collection = self.client.get_collection(name=self.collection_name)
        else:
            log_debug(f"Creating collection: {self.collection_name}")
            self._collection = self.client.create_collection(
                name=self.collection_name, metadata={"hnsw:space": self.distance.value}
            )

    async def async_create(self) -> None:
        """Create the collection asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

    def name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists in the collection.
        Args:
            name (str): Name of the document to check.
        Returns:
            bool: True if document exists, False otherwise."""
        if not self.client:
            logger.warning("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)
            result = collection.get(where=cast(Any, {"name": {"$eq": name}}), limit=1)
            return len(result.get("ids", [])) > 0
        except Exception as e:
            logger.error(f"Error checking name existence: {e}")
        return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the collection.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to merge with document metadata
        """
        log_info(f"Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(metadata)
            log_debug(f"Prepared document: {document.id} | {document.name} | {metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.add(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insert documents asynchronously by running in a thread."""
        log_info(f"Async Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        try:
            embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
            await asyncio.gather(*embed_tasks, return_exceptions=True)
        except Exception as e:
            log_error(f"Error processing document: {e}")

        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(metadata)
            log_debug(f"Prepared document: {document.id} | {document.name} | {metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.add(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    def upsert_available(self) -> bool:
        """Check if upsert is available in ChromaDB."""
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        try:
            if self.content_hash_exists(content_hash):
                self._delete_by_content_hash(content_hash)
            self._upsert(content_hash, documents, filters)
        except Exception as e:
            logger.error(f"Error upserting documents by content hash: {e}")
            raise

    def _upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_info(f"Upserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(metadata)
            log_debug(f"Upserted document: {document.id} | {document.name} | {metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.upsert(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def _async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_info(f"Async Upserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
        await asyncio.gather(*embed_tasks, return_exceptions=True)

        for document in documents:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()

            # Handle metadata and filters
            metadata = document.meta_data or {}
            if filters:
                metadata.update(filters)

            # Add name, content_id to metadata
            if document.name is not None:
                metadata["name"] = document.name
            if document.content_id is not None:
                metadata["content_id"] = document.content_id

            metadata["content_hash"] = content_hash

            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(metadata)
            log_debug(f"Upserted document: {document.id} | {document.name} | {metadata}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.upsert(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents asynchronously by running in a thread."""
        try:
            if self.content_hash_exists(content_hash):
                self._delete_by_content_hash(content_hash)
            await self._async_upsert(content_hash, documents, filters)
        except Exception as e:
            logger.error(f"Error upserting documents by content hash: {e}")
            raise

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search the collection for a query.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply while searching.
                Supports ChromaDB's filtering operators:
                - $eq, $ne: Equality/Inequality
                - $gt, $gte, $lt, $lte: Numeric comparisons
                - $in, $nin: List inclusion/exclusion
                - $and, $or: Logical operators
        Returns:
            List[Document]: List of search results.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        # Convert simple filters to ChromaDB's format if needed
        where_filter = self._convert_filters(filters) if filters else None

        result: QueryResult = self._collection.query(
            query_embeddings=query_embedding,
            n_results=limit,
            where=where_filter,  # Add where filter
            include=["metadatas", "documents", "embeddings", "distances", "uris"],
        )

        # Build search results
        search_results: List[Document] = []

        ids_list = result.get("ids", [[]])
        metadata_list = result.get("metadatas", [[{}]])
        documents_list = result.get("documents", [[]])
        embeddings_list = result.get("embeddings")
        distances_list = result.get("distances", [[]])

        if not ids_list or not metadata_list or not documents_list or embeddings_list is None or not distances_list:
            return search_results

        ids = ids_list[0]
        metadata = [dict(m) if m else {} for m in metadata_list[0]]  # Convert to mutable dicts
        documents = documents_list[0]
        embeddings_raw = embeddings_list[0] if embeddings_list else []
        embeddings = []
        for e in embeddings_raw:
            if hasattr(e, "tolist") and callable(getattr(e, "tolist", None)):
                try:
                    embeddings.append(list(cast(Any, e).tolist()))
                except (AttributeError, TypeError):
                    embeddings.append(list(e) if isinstance(e, (list, tuple)) else [])
            elif isinstance(e, (list, tuple)):
                embeddings.append([float(x) for x in e if isinstance(x, (int, float))])
            elif isinstance(e, (int, float)):
                embeddings.append([float(e)])
            else:
                embeddings.append([])
        distances = distances_list[0]

        for idx, distance in enumerate(distances):
            if idx < len(metadata):
                metadata[idx]["distances"] = distance

        try:
            for idx, (id_, doc_metadata, document) in enumerate(zip(ids, metadata, documents)):
                # Extract the fields we added to metadata
                name_val = doc_metadata.pop("name", None)
                content_id_val = doc_metadata.pop("content_id", None)

                # Convert types to match Document constructor expectations
                name = str(name_val) if name_val is not None and not isinstance(name_val, str) else name_val
                content_id = (
                    str(content_id_val)
                    if content_id_val is not None and not isinstance(content_id_val, str)
                    else content_id_val
                )
                content = str(document) if document is not None else ""
                embedding = embeddings[idx] if idx < len(embeddings) else None

                search_results.append(
                    Document(
                        id=id_,
                        name=name,
                        meta_data=doc_metadata,
                        content=content,
                        embedding=embedding,
                        content_id=content_id,
                    )
                )
        except Exception as e:
            logger.error(f"Error building search results: {e}")

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def _convert_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Convert simple filters to ChromaDB's filter format.

        Handles conversion of simple key-value filters to ChromaDB's operator format
        when needed.
        """
        if not filters:
            return {}

        # If filters already use ChromaDB operators ($eq, $ne, etc.), return as is
        if any(key.startswith("$") for key in filters.keys()):
            return filters

        # Convert simple key-value pairs to ChromaDB's format
        converted = {}
        for key, value in filters.items():
            if isinstance(value, (list, tuple)):
                # Convert lists to $in operator
                converted[key] = {"$in": list(value)}
            else:
                # Convert simple equality to $eq
                converted[key] = {"$eq": value}

        return converted

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def drop(self) -> None:
        """Delete the collection."""
        if self.exists():
            log_debug(f"Deleting collection: {self.collection_name}")
            self.client.delete_collection(name=self.collection_name)

    async def async_drop(self) -> None:
        """Drop the collection asynchronously by running in a thread."""
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        """Check if the collection exists."""
        try:
            self.client.get_collection(name=self.collection_name)
            return True
        except Exception as e:
            log_debug(f"Collection does not exist: {e}")
        return False

    async def async_exists(self) -> bool:
        """Check if collection exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.exists)

    def get_count(self) -> int:
        """Get the count of documents in the collection."""
        if self.exists():
            try:
                collection: Collection = self.client.get_collection(name=self.collection_name)
                return collection.count()
            except Exception as e:
                logger.error(f"Error getting count: {e}")
        return 0

    def optimize(self) -> None:
        raise NotImplementedError

    def delete(self) -> bool:
        try:
            self.client.delete_collection(name=self.collection_name)
            return True
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete document by ID."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Check if document exists
            if not self.id_exists(id):
                log_info(f"Document with ID '{id}' not found")
                return False

            # Delete the document
            collection.delete(ids=[id])
            log_info(f"Deleted document with ID '{id}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting document by ID '{id}': {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find all documents with the given name
            result = collection.get(where=cast(Any, {"name": {"$eq": name}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with name '{name}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with name '{name}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by name '{name}': {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Build where clause for metadata filtering
            where_clause = {}
            for key, value in metadata.items():
                where_clause[key] = {"$eq": value}

            # Find all documents with the matching metadata
            result = collection.get(where=cast(Any, where_clause))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with metadata '{metadata}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with metadata '{metadata}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by metadata '{metadata}': {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content ID."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find all documents with the given content_id
            result = collection.get(where=cast(Any, {"content_id": {"$eq": content_id}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with content_id '{content_id}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with content_id '{content_id}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_id '{content_id}': {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete documents by content hash."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find all documents with the given content_hash
            result = collection.get(where=cast(Any, {"content_hash": {"$eq": content_hash}}))
            ids_to_delete = result.get("ids", [])

            if not ids_to_delete:
                log_info(f"No documents found with content_hash '{content_hash}'")
                return False

            # Delete all matching documents
            collection.delete(ids=ids_to_delete)
            log_info(f"Deleted {len(ids_to_delete)} documents with content_hash '{content_hash}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_hash '{content_hash}': {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the collection.

        Args:
            id (str): The document ID to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)
            print("COLLECTION_----------", collection)
            # Try to get the document by ID
            result = collection.get(ids=[id])
            found_ids = result.get("ids", [])

            # Return True if the document was found
            return len(found_ids) > 0
        except Exception as e:
            logger.error(f"Error checking if ID '{id}' exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if documents with the given content hash exist."""
        if not self.client:
            logger.error("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Try to query for documents with the given content_hash
            try:
                result = collection.get(where=cast(Any, {"content_hash": {"$eq": content_hash}}))
                # Safely extract ids from result
                if hasattr(result, "get") and callable(result.get):
                    found_ids = result.get("ids", [])
                elif hasattr(result, "__getitem__") and "ids" in result:
                    found_ids = result["ids"]
                else:
                    found_ids = []

                # Return True if any documents were found
                if isinstance(found_ids, (list, tuple)):
                    return len(found_ids) > 0
                elif isinstance(found_ids, int):
                    # Some ChromaDB versions might return a count instead of a list
                    return found_ids > 0
                else:
                    return False

            except TypeError as te:
                if "object of type 'int' has no len()" in str(te):
                    # Known issue with ChromaDB 0.5.0 - internal bug
                    # As a workaround, assume content doesn't exist to allow processing to continue
                    logger.warning(
                        f"ChromaDB internal error (version 0.5.0 bug): {te}. Assuming content_hash '{content_hash}' does not exist."
                    )
                    return False
                else:
                    raise te

        except Exception as e:
            logger.error(f"Error checking if content_hash '{content_hash}' exists: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            if not self.client:
                logger.error("Client not initialized")
                return

            collection: Collection = self.client.get_collection(name=self.collection_name)

            # Find documents with the given content_id
            try:
                result = collection.get(where=cast(Any, {"content_id": {"$eq": content_id}}))

                # Extract IDs and current metadata
                if hasattr(result, "get") and callable(result.get):
                    ids = result.get("ids", [])
                    current_metadatas = result.get("metadatas", [])
                elif hasattr(result, "__getitem__"):
                    ids = result.get("ids", []) if "ids" in result else []
                    current_metadatas = result.get("metadatas", []) if "metadatas" in result else []
                else:
                    ids = []
                    current_metadatas = []

                if not ids:
                    logger.debug(f"No documents found with content_id: {content_id}")
                    return

                # Merge metadata for each document
                updated_metadatas = []
                for i, current_meta in enumerate(current_metadatas or []):
                    if current_meta is None:
                        meta_dict: Dict[str, Any] = {}
                    else:
                        meta_dict = dict(current_meta)  # Convert Mapping to dict
                    updated_meta: Dict[str, Any] = meta_dict.copy()
                    updated_meta.update(metadata)

                    if "filters" not in updated_meta:
                        updated_meta["filters"] = {}
                    if isinstance(updated_meta["filters"], dict):
                        updated_meta["filters"].update(metadata)
                    else:
                        updated_meta["filters"] = metadata
                    updated_metadatas.append(updated_meta)

                # Update the documents
                # Convert to the expected type for ChromaDB
                chroma_metadatas = cast(List[Mapping[str, Union[str, int, float, bool, None]]], updated_metadatas)
                collection.update(ids=ids, metadatas=chroma_metadatas)
                logger.debug(f"Updated metadata for {len(ids)} documents with content_id: {content_id}")

            except TypeError as te:
                if "object of type 'int' has no len()" in str(te):
                    logger.warning(
                        f"ChromaDB internal error (version 0.5.0 bug): {te}. Cannot update metadata for content_id '{content_id}'."
                    )
                    return
                else:
                    raise te

        except Exception as e:
            logger.error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise
