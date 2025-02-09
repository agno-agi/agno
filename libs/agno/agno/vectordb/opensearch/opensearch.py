from typing import Any, Dict, List, Literal, Optional, Type

try:
    from opensearchpy import (Connection, OpenSearch, RequestsHttpConnection,
                              Transport)
except ImportError:
    raise ImportError(
        "`opensearch-py` not installed. Please install using `pip install opensearch-py`"
    )

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import logger
from agno.vectordb.base import VectorDb


class OpensearchDb(VectorDb):
    """
    A class representing an OpenSearch database with vector search capabilities.

    Args:
        index_name (str): The name of the index
        dimension (int): The dimension of the embeddings
        hosts (List[Dict[str, Any]]): List of OpenSearch hosts
        embedder (Optional[Embedder]): The embedder to use for encoding documents
        engine (str): The engine to use for KNN search ("nmslib", "faiss", or "lucene")
        space_type (str): The space type for similarity calculation ("l2", "cosinesimil", "innerproduct")
        parameters (Dict[str, Any]): Engine-specific parameters for index construction
        http_auth (Optional[tuple]): Basic authentication tuple (username, password)
        use_ssl (bool): Whether to use SSL for connections
        verify_certs (bool): Whether to verify SSL certificates
        connection_class (Any): The connection class to use
        timeout (int): Connection timeout in seconds
        max_retries (int): Maximum number of connection retries
        retry_on_timeout (bool): Whether to retry on timeout
        reranker (Optional[Reranker]): Optional reranker for search results

    Attributes:
        client (OpenSearch): The OpenSearch client
        index_name (str): Name of the index
        dimension (int): Dimension of the embeddings
        embedder (Embedder): The embedder instance
        engine (str): KNN engine being used
        space_type (str): Space type for similarity calculation
    """
    def __init__(
        self,
        index_name: str,
        dimension: int,
        hosts: List[Dict[str, Any]],
        embedder: Optional[Embedder] = None,
        engine: Literal["nmslib", "faiss", "lucene"] = "nmslib",
        space_type: Literal["l2", "cosinesimil", "innerproduct"] = "cosinesimil",
        parameters: Optional[Dict[str, Any]] = None,
        http_auth: Optional[tuple] = None,
        use_ssl: bool = True,
        verify_certs: bool = True,
        connection_class: Any = RequestsHttpConnection,
        timeout: int = 30,
        max_retries: int = 10,
        retry_on_timeout: bool = True,
        reranker: Optional[Reranker] = None,
    ):
        self._client = None
        self.index_name = index_name
        self.dimension = dimension
        self.engine = engine
        self.space_type = space_type

        self.parameters = self._get_default_parameters(engine)
        if parameters:
            self.parameters.update(parameters)

        self.hosts = hosts
        self.http_auth = http_auth
        self.use_ssl = use_ssl
        self.verify_certs = verify_certs
        self.connection_class = connection_class
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_on_timeout = retry_on_timeout

        self.mapping = self._create_mapping()

        # Initialize embedder
        _embedder = embedder
        if _embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            _embedder = OpenAIEmbedder()
        self.embedder = _embedder
        self.reranker = reranker

    def _get_default_parameters(self, engine: str) -> Dict[str, Any]:
        """Get default parameters for the specified engine.

        Args:
            engine (str): The KNN engine being used

        Returns:
            Dict[str, Any]: Default parameters for the engine
        """
        if engine == "nmslib":
            return {"ef_construction": 512, "m": 16, "ef_search": 512}
        elif engine == "faiss":
            return {"ef_construction": 512, "m": 16, "ef_search": 512}
        elif engine == "lucene":
            return {"ef_construction": 512, "m": 16, "ef_search": 512}
        else:
            raise ValueError(f"Unsupported engine: {engine}")

    def _create_mapping(self) -> Dict[str, Any]:
        """Create the index mapping based on the configured engine and parameters.

        Returns:
            Dict[str, Any]: The index mapping configuration
        """
        knn_method = {
            "name": "hnsw",
            "space_type": self.space_type,
            "engine": self.engine,
            "parameters": self.parameters,
        }

        return {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": self.parameters.get("ef_search", 512),
                }
            },
            "mappings": {
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self.dimension,
                        "method": knn_method,
                    },
                    "content": {"type": "text"},
                    "meta_data": {"type": "object"},
                }
            },
        }

    @property
    def client(self) -> OpenSearch:
        """
        Get or create OpenSearch client.

        Returns:
            Opensearch: The OpenSearch Client
        """
        if self._client is None:
            logger.debug("Creating an Opensearch client")
            self._client = OpenSearch(
                hosts=self.hosts,
                http_auth=self.http_auth,
                use_ssl=self.use_ssl,
                verify_certs=self.verify_certs,
                connection_class=self.connection_class,
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_on_timeout=self.retry_on_timeout
            )
        return self._client
    
    def exists(self) -> bool:
        """
        Check if the index exists

        Returns:
            bool: True if the index exists, False otherwise
        """
        return self.client.exists(index=self.index_name)

    def create(self) -> None:
        """Create the index if it does not exist."""
        if not self.exists():
            logger.debug(f"Creating index: {self.index_name}")

            self.client.create(
                index=self.index_name,
                body=self.mapping
            )

    def drop(self) -> None:
        """Delete the index if it exists."""
        if self.exists():
            logger.debug(f"Deleting index: {self.index_name}")
            return self.client.delete(index=self.index_name)
        
    def doc_exists(self, document) -> bool:
        """Check if a document exists in the index.

        Args:
            document (Document): The document to check.

        Returns:
            bool: True if the document exists, False otherwise.

        """
        return self.client.exists(
            index=self.index_name,
            id=document.id
        )
    
    
