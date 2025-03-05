from typing import Any, Dict, List, Optional

try:
    from upstash_vector import Index, Vector
    from upstash_vector.types import InfoResult
except ImportError:
    raise ImportError(
        "The `upstash-vector` package is not installed, please install using `pip install upstash-vector`"
    )

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import logger
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

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the index.
        Args:
            document (Document): The document to check.
        Returns:
            bool: True if the document exists, False otherwise.
        """
        if document.id is None:
            logger.error("Document ID cannot be None")
            return False
        documents_to_fetch = [document.id]
        response = self.index.fetch(ids=documents_to_fetch)
        return len(response) > 0

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
        self, documents: List[Document], filters: Optional[Dict[str, Any]] = None, namespace: Optional[str] = None
    ) -> None:
        """Upsert documents into the index.

        Args:
            documents (List[Document]): The documents to upsert.
            filters (Optional[Dict[str, Any]], optional): The filters for the upsert. Defaults to None.
            namespace (Optional[str], optional): The namespace for the documents. Defaults to None, which uses the instance namespace.
        """
        _namespace = self.namespace if namespace is None else namespace
        vectors = []

        for document in documents:
            if document.id is None:
                logger.error(f"Document ID must not be None. Skipping document: {document.content[:100]}...")
                continue

            document.meta_data["text"] = document.content

            if not self.use_upstash_embeddings:
                if self.embedder is None:
                    logger.error("Embedder is None but use_upstash_embeddings is False")
                    continue

                document.embed(embedder=self.embedder)
                if document.embedding is None:
                    logger.error(f"Failed to generate embedding for document: {document.id}")
                    continue

                vector = Vector(
                    id=document.id, vector=document.embedding, metadata=document.meta_data, data=document.content
                )
            else:
                vector = Vector(id=document.id, data=document.content, metadata=document.meta_data)
            vectors.append(vector)

        if not vectors:
            logger.warning("No valid documents to upsert")
            return

        self.index.upsert(vectors, namespace=_namespace)

    def upsert_available(self) -> bool:
        """Check if upsert operation is available.
        Returns:
            True
        """
        return True

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the index.
        This method is not supported by Upstash. Use `upsert` instead.
        Args:
            documents (List[Document]): The documents to insert.
            filters (Optional[Dict[str, Any]], optional): The filters for the insert. Defaults to None.
        Raises:
            NotImplementedError: This method is not supported by Upstash.
        """
        raise NotImplementedError("Upstash does not support insert operations. Use upsert instead.")

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
            logger.info(f"No results found for query: {query}")
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
