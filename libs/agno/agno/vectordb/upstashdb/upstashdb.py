import asyncio
from typing import Any, Dict, List, Optional

try:
    from upstash_vector import Index, Vector
    from upstash_vector.types import InfoResult
except ImportError:
    raise ImportError(
        "The `upstash-vector` package is not installed, please install using `pip install upstash-vector`"
    )

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_info, logger
from agno.vectordb.base import VectorDb

DEFAULT_NAMESPACE = ""


class UpstashVectorDb(VectorDb):
    """
    This class provides an interface to Upstash Vector database with support for both
    custom embeddings and Upstash's hosted embedding models.

    Args:
        url (str): The Upstash Vector database URL.
        token (str): The Upstash Vector API token.
        retries (Optional[int], optional): Number of retry attempts for operations. Defaults to 3.
        retry_interval (Optional[float], optional): Time interval between retries in seconds. Defaults to 1.0.
        dimension (Optional[int], optional): The dimension of the embeddings. Defaults to None.
        embedder (Optional[Embedder], optional): The embedder to use. If None, uses Upstash hosted embedding models.
        namespace (Optional[str], optional): The namespace to use. Defaults to DEFAULT_NAMESPACE.
        reranker (Optional[Reranker], optional): The reranker to use. Defaults to None.
        **kwargs: Additional keyword arguments.
    """

    def __init__(
        self,
        url: str,
        token: str,
        retries: Optional[int] = 3,
        retry_interval: Optional[float] = 1.0,
        dimension: Optional[int] = None,
        embedder: Optional[Embedder] = None,
        namespace: Optional[str] = DEFAULT_NAMESPACE,
        reranker: Optional[Reranker] = None,
        **kwargs: Any,
    ) -> None:
        self._index: Optional[Index] = None
        self.url: str = url
        self.token: str = token
        self.retries: int = retries if retries is not None else 3
        self.retry_interval: float = retry_interval if retry_interval is not None else 1.0
        self.dimension: Optional[int] = dimension
        self.namespace: str = namespace if namespace is not None else DEFAULT_NAMESPACE
        self.kwargs: Dict[str, Any] = kwargs
        self.use_upstash_embeddings: bool = embedder is None

        if embedder is None:
            logger.warning(
                "You have not provided an embedder, using Upstash hosted embedding models. "
                "Make sure you created your index with an embedding model."
            )
        self.embedder: Optional[Embedder] = embedder
        self.reranker: Optional[Reranker] = reranker

    @property
    def index(self) -> Index:
        """The Upstash Vector index.
        Returns:
            upstash_vector.Index: The Upstash Vector index.
        """
        if self._index is None:
            self._index = Index(
                url=self.url,
                token=self.token,
                retries=self.retries,
                retry_interval=self.retry_interval,
            )
            if self._index is None:
                raise ValueError("Failed to initialize Upstash index")

            info = self._index.info()
            if info is None:
                raise ValueError("Failed to get index info")

            index_dimension = info.dimension
            if self.dimension is not None and index_dimension != self.dimension:
                raise ValueError(
                    f"Index dimension {index_dimension} does not match provided dimension {self.dimension}"
                )
        return self._index

    def exists(self) -> bool:
        """Check if the index exists and is accessible.

        Returns:
            bool: True if the index exists and is accessible, False otherwise.

        Raises:
            Exception: If there's an error communicating with Upstash.
        """
        try:
            self.index.info()
            return True
        except Exception as e:
            logger.error(f"Error checking index existence: {str(e)}")
            return False

    def create(self) -> None:
        """You can create indexes via Upstash Console."""
        logger.warning(
            "Indexes can only be created through the Upstash Console or the developer API. Please create an index before using this vector database."
        )
        pass

    def drop(self) -> None:
        """You can drop indexes via Upstash Console."""
        logger.warning(
            "Indexes can only be dropped through the Upstash Console. Make sure you have an existing index before performing operations."
        )
        pass

    def drop_namespace(self, namespace: Optional[str] = None) -> None:
        """Delete a namespace from the index.
        Args:
            namespace (Optional[str], optional): The namespace to drop. Defaults to None, which uses the instance namespace.
        """
        _namespace = self.namespace if namespace is None else namespace
        if self.namespace_exists(_namespace):
            self.index.delete_namespace(_namespace)
        else:
            logger.error(f"Namespace {_namespace} does not exist.")

    def get_all_namespaces(self) -> List[str]:
        """Get all namespaces in the index.
        Returns:
            List[str]: A list of namespaces.
        """
        return self.index.list_namespaces()

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if documents with the given content hash exist in the index.

        Args:
            content_hash (str): The content hash to check.

        Returns:
            bool: True if documents with the content hash exist, False otherwise.
        """
        try:
            # Use query with a filter to check if any documents exist with this content_hash
            # We only need to check existence, so limit to 1 result
            filter_str = f'content_hash = "{content_hash}"'

            if not self.use_upstash_embeddings and self.embedder is not None:
                # For custom embeddings, we need a dummy vector for the query
                # Use a zero vector as we only care about the filter match
                info = self.index.info()
                dimension = info.dimension
                dummy_vector = [0.0] * dimension

                response = self.index.query(
                    vector=dummy_vector,
                    namespace=self.namespace,
                    top_k=1,
                    filter=filter_str,
                    include_data=False,
                    include_metadata=False,
                    include_vectors=False,
                )
            else:
                # For hosted embeddings, use a minimal text query
                response = self.index.query(
                    data="",  # Empty query since we only care about the filter
                    namespace=self.namespace,
                    top_k=1,
                    filter=filter_str,
                    include_data=False,
                    include_metadata=False,
                    include_vectors=False,
                )

            return response is not None and len(response) > 0
        except Exception as e:
            logger.error(f"Error checking if content_hash {content_hash} exists: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """You can check if an index exists in Upstash Console.
        Args:
            name (str): The name of the index to check.
        Returns:
            bool: True if the index exists, False otherwise. (Name is not used.)
        """
        logger.warning(
            f"You can check if an index with name {name} exists in Upstash Console."
            "The token and url parameters you provided are used to connect to a specific index."
        )
        return self.exists()

    def namespace_exists(self, namespace: str) -> bool:
        """Check if an namespace exists.
        Args:
            namespace (str): The name of the namespace to check.
        Returns:
            bool: True if the namespace exists, False otherwise.
        """
        namespaces = self.index.list_namespaces()
        return namespace in namespaces

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Upsert documents into the index.

        Args:
            documents (List[Document]): The documents to upsert.
            filters (Optional[Dict[str, Any]], optional): The filters for the upsert. Defaults to None.
            namespace (Optional[str], optional): The namespace for the documents. Defaults to None, which uses the instance namespace.
        """
        _namespace = self.namespace if namespace is None else namespace
        vectors = []

        for i, document in enumerate(documents):
            if document.id is None:
                logger.error(f"Document ID must not be None. Skipping document: {document.content[:100]}...")
                continue

            logger.debug(
                f"Processing document {i + 1}: ID={document.id}, name={document.name}, "
                f"content_id={getattr(document, 'content_id', 'N/A')}"
            )

            # Create a copy of metadata to avoid modifying the original document
            meta_data = document.meta_data.copy() if document.meta_data else {}

            # Add filters to document metadata if provided
            if filters:
                meta_data.update(filters)

            meta_data["text"] = document.content

            # Add content_id to metadata if it exists
            if hasattr(document, "content_id") and document.content_id:
                meta_data["content_id"] = document.content_id
            else:
                logger.warning(f"Document {document.id} has no content_id")

            meta_data["content_hash"] = content_hash

            # Add name to metadata if it exists
            if document.name:
                meta_data["name"] = document.name
            else:
                logger.warning(f"Document {document.id} has no name")

            if not self.use_upstash_embeddings:
                if self.embedder is None:
                    logger.error("Embedder is None but use_upstash_embeddings is False")
                    continue

                document.embed(embedder=self.embedder)
                if document.embedding is None:
                    logger.error(f"Failed to generate embedding for document: {document.id}")
                    continue

                vector = Vector(id=document.id, vector=document.embedding, metadata=meta_data, data=document.content)
            else:
                vector = Vector(id=document.id, data=document.content, metadata=meta_data)
            vectors.append(vector)

        if not vectors:
            logger.warning("No valid documents to upsert")
            return

        logger.info(f"Upserting {len(vectors)} vectors to Upstash with IDs: {[v.id for v in vectors[:5]]}...")
        self.index.upsert(vectors, namespace=_namespace)

    def upsert_available(self) -> bool:
        """Check if upsert operation is available.
        Returns:
            True
        """
        return True

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the index.
        This method is not supported by Upstash. Use `upsert` instead.
        Args:
            documents (List[Document]): The documents to insert.
            filters (Optional[Dict[str, Any]], optional): The filters for the insert. Defaults to None.
        """
        logger.warning("Upstash does not support insert operations. Using upsert instead.")
        self.upsert(content_hash=content_hash, documents=documents, filters=filters)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
    ) -> List[Document]:
        """Search for documents in the index.
        Args:
            query (str): The query string to search for.
            limit (int, optional): Maximum number of results to return. Defaults to 5.
            filters (Optional[Dict[str, Any]], optional): Metadata filters for the search.
            namespace (Optional[str], optional): The namespace to search in. Defaults to None, which uses the instance namespace.
        Returns:
            List[Document]: List of matching documents.
        """
        _namespace = self.namespace if namespace is None else namespace

        filter_str = "" if filters is None else str(filters)

        if not self.use_upstash_embeddings and self.embedder is not None:
            dense_embedding = self.embedder.get_embedding(query)

            if dense_embedding is None:
                logger.error(f"Error getting embedding for Query: {query}")
                return []

            response = self.index.query(
                vector=dense_embedding,
                namespace=_namespace,
                top_k=limit,
                filter=filter_str,
                include_data=True,
                include_metadata=True,
                include_vectors=True,
            )
        else:
            response = self.index.query(
                data=query,
                namespace=_namespace,
                top_k=limit,
                filter=filter_str,
                include_data=True,
                include_metadata=True,
                include_vectors=True,
            )

        if response is None:
            log_info(f"No results found for query: {query}")
            return []

        search_results = []
        for result in response:
            if result.data is not None and result.id is not None and result.vector is not None:
                search_results.append(
                    Document(
                        content=result.data,
                        id=result.id,
                        meta_data=result.metadata or {},
                        embedding=result.vector,
                    )
                )

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        log_info(f"Found {len(search_results)} results")
        return search_results

    def delete(self, namespace: Optional[str] = None, delete_all: bool = False) -> bool:
        """Clear the index.
        Args:
            namespace (Optional[str], optional): The namespace to clear. Defaults to None, which uses the instance namespace.
            delete_all (bool, optional): Whether to delete all documents in the index. Defaults to False.
        Returns:
            bool: True if the index was deleted, False otherwise.
        """
        _namespace = self.namespace if namespace is None else namespace
        response = self.index.reset(namespace=_namespace, all=delete_all)
        return True if response.lower().strip() == "success" else False

    def get_index_info(self) -> InfoResult:
        """Get information about the index.
        Returns:
            InfoResult: Information about the index including size, vector count, etc.
        """
        return self.index.info()

    def optimize(self) -> None:
        """Optimize the index.
        This method is empty as Upstash automatically optimizes indexes.
        """
        pass

    def delete_by_id(self, id: str) -> bool:
        """Delete document by ID.

        Args:
            id (str): The document ID to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            response = self.index.delete(ids=[id], namespace=self.namespace)
            deleted_count = getattr(response, "deleted", 0)
            logger.info(f"Deleted {deleted_count} document(s) with ID: {id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document by ID {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name using metadata filter.

        Args:
            name (str): The document name to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # Use Upstash's delete with metadata filter
            response = self.index.delete(filter=f'name = "{name}"', namespace=self.namespace)
            deleted_count = getattr(response, "deleted", 0)
            logger.info(f"Deleted {deleted_count} document(s) with name: {name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata filter.

        Args:
            metadata (Dict[str, Any]): Metadata criteria for deletion

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # Build filter string for Upstash metadata filtering
            filter_parts = []
            for key, value in metadata.items():
                if isinstance(value, str):
                    filter_parts.append(f'{key} = "{value}"')
                else:
                    filter_parts.append(f"{key} = {value}")

            filter_str = " AND ".join(filter_parts)

            response = self.index.delete(filter=filter_str, namespace=self.namespace)
            deleted_count = getattr(response, "deleted", 0)
            logger.info(f"Deleted {deleted_count} document(s) matching metadata: {metadata}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content_id.

        Args:
            content_id (str): The content ID to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        return self.delete_by_metadata({"content_id": content_id})

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        logger.warning("Upstash does not support async insert operations. Using upsert instead.")
        await self.async_upsert(content_hash=content_hash, documents=documents, filters=filters)

    async def async_exists(self) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_create(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_drop(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Async Upsert documents into the index.

        Args:
            documents (List[Document]): The documents to upsert.
            filters (Optional[Dict[str, Any]], optional): The filters for the upsert. Defaults to None.
            namespace (Optional[str], optional): The namespace for the documents. Defaults to None, which uses the instance namespace.
        """
        _namespace = self.namespace if namespace is None else namespace
        vectors = []

        embed_tasks = [document.async_embed(embedder=self.embedder) for document in documents]
        await asyncio.gather(*embed_tasks, return_exceptions=True)

        for i, document in enumerate(documents):
            if document.id is None:
                logger.error(f"Document ID must not be None. Skipping document: {document.content[:100]}...")
                continue

            logger.debug(
                f"Processing document {i + 1}: ID={document.id}, name={document.name}, "
                f"content_id={getattr(document, 'content_id', 'N/A')}"
            )

            # Create a copy of metadata to avoid modifying the original document
            meta_data = document.meta_data.copy() if document.meta_data else {}

            # Add filters to document metadata if provided
            if filters:
                meta_data.update(filters)

            meta_data["text"] = document.content

            # Add content_id to metadata if it exists
            if hasattr(document, "content_id") and document.content_id:
                meta_data["content_id"] = document.content_id
            else:
                logger.warning(f"Document {document.id} has no content_id")

            meta_data["content_hash"] = content_hash

            # Add name to metadata if it exists
            if document.name:
                meta_data["name"] = document.name
            else:
                logger.warning(f"Document {document.id} has no name")

            if not self.use_upstash_embeddings:
                if self.embedder is None:
                    logger.error("Embedder is None but use_upstash_embeddings is False")
                    continue

                if document.embedding is None:
                    logger.error(f"Failed to generate embedding for document: {document.id}")
                    continue

                vector = Vector(id=document.id, vector=document.embedding, metadata=meta_data, data=document.content)
            else:
                vector = Vector(id=document.id, data=document.content, metadata=meta_data)
            vectors.append(vector)

        if not vectors:
            logger.warning("No valid documents to upsert")
            return

        logger.info(f"Upserting {len(vectors)} vectors to Upstash with IDs: {[v.id for v in vectors[:5]]}...")
        self.index.upsert(vectors, namespace=_namespace)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists in the index.

        Args:
            id (str): The document ID to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        try:
            response = self.index.fetch(ids=[id], namespace=self.namespace)
            return len(response) > 0
        except Exception as e:
            logger.error(f"Error checking if ID {id} exists: {e}")
            return False

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """Delete documents by content hash using metadata filter.

        Args:
            content_hash (str): The content hash to delete.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        try:
            response = self.index.delete(filter=f'content_hash = "{content_hash}"', namespace=self.namespace)
            deleted_count = getattr(response, "deleted", 0)
            logger.info(f"Deleted {deleted_count} document(s) with content_hash: {content_hash}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by content_hash {content_hash}: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        try:
            # Query for vectors with the given content_id
            query_response = self.index.query(
                filter=f'content_id = "{content_id}"',
                top_k=1000,  # Get all matching vectors
                include_metadata=True,
                namespace=self.namespace,
            )

            if not query_response or not hasattr(query_response, "__iter__"):
                logger.debug(f"No documents found with content_id: {content_id}")
                return

            # Update each matching vector
            updated_count = 0
            for result in query_response:
                if hasattr(result, "id") and hasattr(result, "metadata"):
                    vector_id = result.id
                    current_metadata = result.metadata or {}

                    # Merge existing metadata with new metadata
                    updated_metadata = current_metadata.copy()
                    updated_metadata.update(metadata)

                    if "filters" not in updated_metadata:
                        updated_metadata["filters"] = {}
                    if isinstance(updated_metadata["filters"], dict):
                        updated_metadata["filters"].update(metadata)
                    else:
                        updated_metadata["filters"] = metadata

                    # Update the vector metadata
                    self.index.update(id=vector_id, metadata=updated_metadata, namespace=self.namespace)
                    updated_count += 1

            logger.debug(f"Updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            logger.error(f"Error updating metadata for content_id '{content_id}': {e}")
            raise
