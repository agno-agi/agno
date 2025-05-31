from __future__ import annotations

from typing import Any, Dict, List

try:
    from opensearchpy import (
        AsyncOpenSearch,
        Connection,
        OpenSearch,
        RequestsHttpConnection,
        Transport
    )
    from opensearchpy import exceptions as opensearch_exceptions
except ImportError:
    raise ImportError(
        "`opensearch-py` not installed. Please install using `pip install opensearch-py`"
    )

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import logger
from agno.vectordb.base import VectorDb
from agno.vectordb.opensearch.types import SpaceType, Engine


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
        async_client (AsyncOpenSearch): The async OpenSearch client
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
        embedder: Embedder | None = None,
        engine: Engine = "nmslib",
        space_type: SpaceType = "cosinesimil",
        parameters: Dict[str, Any] | None = None,
        http_auth: tuple | None = None,
        use_ssl: bool = False,
        verify_certs: bool = False,
        connection_class: Any = RequestsHttpConnection,
        timeout: int = 30,
        max_retries: int = 10,
        retry_on_timeout: bool = True,
        reranker: Reranker | None = None,
    ):
        self._client = None
        self._async_client = None
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

    def create(self) -> None:
        """Create the index if it does not exist."""
        try:
            if not self.exists():
                logger.debug(f"Creating index: {self.index_name}")
                self.client.indices.create(
                    index=self.index_name,
                    body=self.mapping
                )
                logger.info(f"Successfully created index: {self.index_name}")
            else:
                logger.info(f"Index {self.index_name} already exists")
        except Exception as e:
            logger.error(f"Error creating index {self.index_name}: {e}")
            raise

    async def async_create(self) -> None:
        """Async version of create method."""
        try:
            if not await self.async_exists():
                logger.debug(f"Creating index: {self.index_name}")
                await self.async_client.indices.create(
                    index=self.index_name,
                    body=self.mapping
                )
                logger.info(f"Successfully created index: {self.index_name}")
            else:
                logger.info(f"Index {self.index_name} already exists")
        except Exception as e:
            logger.error(f"Error creating index {self.index_name}: {e}")
            raise

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the index.

        Args:
            document (Document): The document to check.

        Returns:
            bool: True if the document exists, False otherwise.
        """
        if document.id is None:
            logger.warning("Document ID is None, cannot check existence")
            return False

        try:
            return self.client.exists(
                index=self.index_name,
                id=document.id
            )
        except Exception as e:
            logger.error(f"Error checking if document exists: {e}")
            return False

    async def async_doc_exists(self, document: Document) -> bool:
        """Async version of doc_exists method."""
        if document.id is None:
            logger.warning("Document ID is None, cannot check existence")
            return False

        try:
            return await self.async_client.exists(
                index=self.index_name,
                id=document.id
            )
        except Exception as e:
            logger.error(f"Error checking if document exists: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists in metadata.

        Args:
            name (str): The name to search for

        Returns:
            bool: True if a document with this name exists, False otherwise
        """
        try:
            if not self.exists():
                return False

            search_query = {
                "query": {
                    "term": {
                        "name.keyword": name
                    }
                },
                "size": 1
            }

            response = self.client.search(
                index=self.index_name,
                body=search_query
            )

            return response["hits"]["total"]["value"] > 0
        except Exception as e:
            logger.error(f"Error checking if name exists: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Async version of name_exists method."""
        try:
            if not await self.async_exists():
                return False

            search_query = {
                "query": {
                    "term": {
                        "name.keyword": name
                    }
                },
                "size": 1
            }

            response = await self.async_client.search(
                index=self.index_name,
                body=search_query
            )

            return response["hits"]["total"]["value"] > 0
        except Exception as e:
            logger.error(f"Error checking if name exists: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists.

        Args:
            id (str): The document ID to check

        Returns:
            bool: True if the document exists, False otherwise
        """
        try:
            return self.client.exists(
                index=self.index_name,
                id=id
            )
        except Exception as e:
            logger.error(f"Error checking if ID exists: {e}")
            return False

    def _prepare_document_for_indexing(self, doc: Document) -> Dict[str, Any]:
        """Prepare a document for indexing by ensuring it has an embedding."""
        # Generate ID if not present
        if doc.id is None:
            import uuid
            doc.id = str(uuid.uuid4())

        # Get embedding for the document if not already present
        if doc.embedding is None:
            try:
                # Use document's own embedder if available, otherwise use database embedder
                embedder_to_use = doc.embedder or self.embedder
                if embedder_to_use is None:
                    raise ValueError(f"No embedder available for document {doc.id}")

                # Use the document's embed method which handles the embedder logic properly
                doc.embed(embedder_to_use)

            except Exception as e:
                logger.error(f"Error generating embedding for document {doc.id}: {e}")
                raise

        if doc.embedding is None:
            raise ValueError(f"Document {doc.id} has no embedding and no embedder is configured")

        # Check dimensions
        if len(doc.embedding) != self.dimension:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimension}, got {len(doc.embedding)}"
            )

        # Prepare document for indexing
        index_doc = {
            "embedding": doc.embedding,
            "content": doc.content,
            "meta_data": doc.meta_data,
        }

        # Add optional fields if they exist
        if doc.name is not None:
            index_doc["name"] = doc.name
        if doc.usage is not None:
            index_doc["usage"] = doc.usage
        if doc.reranking_score is not None:
            index_doc["reranking_score"] = doc.reranking_score

        return index_doc

    def insert(self, documents: List[Document], filters: Dict[str, Any] | None = None) -> None:
        """
        Insert documents into the index.

        Args:
            documents (List[Document]): The documents to insert
            filters (Optional[Dict[str, Any]]): Optional filters (not used in insert)
        """
        if not documents:
            logger.warning("No documents provided to insert")
            return

        if not self.exists():
            logger.info(f"Index {self.index_name} does not exist, creating it")
            self.create()

        # Prepare bulk operation
        bulk_data = []
        for doc in documents:
            try:
                index_doc = self._prepare_document_for_indexing(doc)

                # Add to bulk operation
                bulk_data.append({"index": {"_index": self.index_name, "_id": doc.id}})
                bulk_data.append(index_doc)

            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for indexing: {e}")
                continue

        if bulk_data:
            try:
                response = self.client.bulk(body=bulk_data, refresh=True)
                # Check for errors in bulk response
                if response.get("errors"):
                    for item in response.get("items", []):
                        if "index" in item and "error" in item["index"]:
                            logger.error(f"Bulk index error: {item['index']['error']}")
                else:
                    logger.info(f"Successfully inserted {len(documents)} documents to index {self.index_name}")
            except Exception as e:
                logger.error(f"Error executing bulk insert operation: {e}")
                raise

    async def async_insert(self, documents: List[Document], filters: Dict[str, Any] | None = None) -> None:
        """Async version of insert method."""
        if not documents:
            logger.warning("No documents provided to insert")
            return

        if not await self.async_exists():
            logger.info(f"Index {self.index_name} does not exist, creating it")
            await self.async_create()

        # Prepare bulk operation
        bulk_data = []
        for doc in documents:
            try:
                index_doc = self._prepare_document_for_indexing(doc)

                # Add to bulk operation
                bulk_data.append({"index": {"_index": self.index_name, "_id": doc.id}})
                bulk_data.append(index_doc)

            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for indexing: {e}")
                continue

        if bulk_data:
            try:
                response = await self.async_client.bulk(body=bulk_data, refresh=True)
                # Check for errors in bulk response
                if response.get("errors"):
                    for item in response.get("items", []):
                        if "index" in item and "error" in item["index"]:
                            logger.error(f"Bulk index error: {item['index']['error']}")
                else:
                    logger.info(f"Successfully inserted {len(documents)} documents to index {self.index_name}")
            except Exception as e:
                logger.error(f"Error executing bulk insert operation: {e}")
                raise

    def upsert_available(self) -> bool:
        """Check if upsert operations are supported."""
        return True

    def upsert(self, documents: List[Document], filters: Dict[str, Any] | None = None) -> None:
        """
        Upsert documents in the index (insert or update).

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Optional filters (not used in upsert)
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            self.create()

        if not documents:
            logger.warning("No documents provided for upsert")
            return

        try:
            # Prepare bulk upsert operation
            bulk_data = []
            for doc in documents:
                try:
                    index_doc = self._prepare_document_for_indexing(doc)

                    # Add to bulk operation
                    bulk_data.append({"update": {"_index": self.index_name, "_id": doc.id}})
                    bulk_data.append({"doc": index_doc, "doc_as_upsert": True})

                except Exception as e:
                    logger.error(f"Error preparing document {doc.id} for upsert: {e}")
                    continue

            if bulk_data:
                response = self.client.bulk(body=bulk_data, refresh=True)
                # Check for errors in bulk response
                if response.get("errors"):
                    for item in response.get("items", []):
                        if "update" in item and "error" in item["update"]:
                            logger.error(f"Bulk upsert error: {item['update']['error']}")
                else:
                    logger.info(f"Successfully upserted {len(documents)} documents in index {self.index_name}")

        except Exception as e:
            logger.error(f"Error executing bulk upsert operation: {e}")
            raise

    async def async_upsert(self, documents: List[Document], filters: Dict[str, Any] | None = None) -> None:
        """Async version of upsert method."""
        if not await self.async_exists():
            logger.warning(f"Index {self.index_name} does not exist")
            await self.async_create()

        if not documents:
            logger.warning("No documents provided for upsert")
            return

        try:
            # Prepare bulk upsert operation
            bulk_data = []
            for doc in documents:
                try:
                    index_doc = self._prepare_document_for_indexing(doc)

                    # Add to bulk operation
                    bulk_data.append({"update": {"_index": self.index_name, "_id": doc.id}})
                    bulk_data.append({"doc": index_doc, "doc_as_upsert": True})

                except Exception as e:
                    logger.error(f"Error preparing document {doc.id} for upsert: {e}")
                    continue

            if bulk_data:
                response = await self.async_client.bulk(body=bulk_data, refresh=True)
                # Check for errors in bulk response
                if response.get("errors"):
                    for item in response.get("items", []):
                        if "update" in item and "error" in item["update"]:
                            logger.error(f"Bulk upsert error: {item['update']['error']}")
                else:
                    logger.info(f"Successfully upserted {len(documents)} documents in index {self.index_name}")

        except Exception as e:
            logger.error(f"Error executing bulk upsert operation: {e}")
            raise

    def _create_document_from_hit(self, hit: Dict[str, Any]) -> Document:
        """Create a Document object from an OpenSearch hit."""
        doc_data = hit["_source"]

        # Store the search score in meta_data
        meta_data = doc_data.get("meta_data", {}).copy()
        meta_data["search_score"] = hit["_score"]

        doc = Document(
            id=hit["_id"],
            content=doc_data["content"],
            name=doc_data.get("name"),
            meta_data=meta_data,
            embedding=doc_data.get("embedding"),
            usage=doc_data.get("usage"),
            reranking_score=doc_data.get("reranking_score")
        )

        return doc

    def _build_filter_conditions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build filter conditions for OpenSearch query.

        Args:
            filters (Dict[str, Any]): Filters to apply

        Returns:
            List[Dict[str, Any]]: List of filter conditions for OpenSearch
        """
        filter_conditions = []

        for key, value in filters.items():
            if isinstance(value, Dict):
                # Handle operators like $in, in, range queries, etc.
                if "$in" in value or "in" in value:
                    # Handle $in or in operators
                    in_value = value.get("$in") or value.get("in")
                    if isinstance(in_value, List):
                        filter_conditions.append({"terms": {f"meta_data.{key}": in_value}})
                    else:
                        logger.warning(f"Invalid value for $in/in operator for key {key}: {in_value}")
                elif any(op in value for op in ["gt", "lt", "gte", "lte"]):
                    # Handle range queries
                    range_conditions = {}
                    for range_op, range_val in value.items():
                        if range_op in ["gt", "lt", "gte", "lte"]:
                            range_conditions[range_op] = range_val
                    filter_conditions.append({"range": {f"meta_data.{key}": range_conditions}})
                else:
                    # Handle other dict-based operators if needed
                    logger.warning(f"Unsupported filter operator for key {key}: {value}")
            elif isinstance(value, List):
                # Handle list values with terms query (direct list support)
                filter_conditions.append({"terms": {f"meta_data.{key}": value}})
            else:
                # Handle exact match
                filter_conditions.append({"term": {f"meta_data.{key}.keyword": value}})

        return filter_conditions

    def search(self, query: str, limit: int = 5, filters: Dict[str, Any] | None = None) -> List[Document]:
        """
        Search for documents similar to the query.

        Args:
            query (str): The query string
            limit (int, optional): Number of results to return. Defaults to 5.
            filters (Optional[Dict[str, Any]], optional): Metadata filters to apply. Defaults to None.

        Returns:
            List[Document]: List of documents matching the query
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return []

        try:
            # Get embedding for the query using the database embedder
            if self.embedder is None:
                raise ValueError("No embedder configured for search")

            # Use the embedder's get_embedding_and_usage method
            query_embedding, _ = self.embedder.get_embedding_and_usage(query)

            # Construct the search query using the correct OpenSearch KNN syntax
            search_query = {
                "size": limit,
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": query_embedding,
                            "k": limit
                        }
                    }
                }
            }

            # Add filters if provided
            if filters:
                filter_conditions = self._build_filter_conditions(filters)

                if filter_conditions:
                    # Combine KNN with filters using bool query
                    search_query = {
                        "size": limit,
                        "query": {
                            "bool": {
                                "must": [
                                    {
                                        "knn": {
                                            "embedding": {
                                                "vector": query_embedding,
                                                "k": limit
                                            }
                                        }
                                    }
                                ],
                                "filter": filter_conditions
                            }
                        }
                    }

            # Execute search
            response = self.client.search(
                index=self.index_name,
                body=search_query
            )

            # Process results
            documents = []
            for hit in response["hits"]["hits"]:
                doc = self._create_document_from_hit(hit)
                documents.append(doc)

            # Apply reranking if a reranker is configured
            if self.reranker and documents:
                documents = self.reranker.rerank(query, documents)

            logger.info(f"Search returned {len(documents)} documents for query: {query}")
            return documents

        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Dict[str, Any] | None = None
    ) -> List[Document]:
        """Async version of search method."""
        if not await self.async_exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return []

        try:
            # Get embedding for the query using the database embedder
            if self.embedder is None:
                raise ValueError("No embedder configured for search")

            # Use the embedder's get_embedding_and_usage method
            query_embedding, _ = self.embedder.get_embedding_and_usage(query)

            # Construct the search query using the correct OpenSearch KNN syntax
            search_query = {
                "size": limit,
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": query_embedding,
                            "k": limit
                        }
                    }
                }
            }

            # Add filters if provided
            if filters:
                filter_conditions = self._build_filter_conditions(filters)

                if filter_conditions:
                    # Combine KNN with filters using bool query
                    search_query = {
                        "size": limit,
                        "query": {
                            "bool": {
                                "must": [
                                    {
                                        "knn": {
                                            "embedding": {
                                                "vector": query_embedding,
                                                "k": limit
                                            }
                                        }
                                    }
                                ],
                                "filter": filter_conditions
                            }
                        }
                    }

            # Execute search
            response = await self.async_client.search(
                index=self.index_name,
                body=search_query
            )

            # Process results
            documents = []
            for hit in response["hits"]["hits"]:
                doc = self._create_document_from_hit(hit)
                documents.append(doc)

            # Apply reranking if a reranker is configured
            if self.reranker and documents:
                documents = self.reranker.rerank(query, documents)

            logger.info(f"Search returned {len(documents)} documents for query: {query}")
            return documents

        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """
        Perform vector-only search using query embeddings.

        Args:
            query (str): The query string
            limit (int): Number of results to return

        Returns:
            List[Document]: List of documents matching the query
        """
        return self.search(query, limit)

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """
        Perform keyword-based search on document content.

        Args:
            query (str): The query string
            limit (int): Number of results to return

        Returns:
            List[Document]: List of documents matching the query
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return []

        try:
            search_query = {
                "size": limit,
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["content", "name"],
                        "type": "best_fields"
                    }
                }
            }

            response = self.client.search(
                index=self.index_name,
                body=search_query
            )

            documents = []
            for hit in response["hits"]["hits"]:
                doc = self._create_document_from_hit(hit)
                documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"Error during keyword search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """
        Perform hybrid search combining vector and keyword search.

        Args:
            query (str): The query string
            limit (int): Number of results to return

        Returns:
            List[Document]: List of documents matching the query
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return []

        try:
            # Get embedding for the query
            if self.embedder is None:
                raise ValueError("No embedder configured for hybrid search")

            query_embedding, _ = self.embedder.get_embedding_and_usage(query)

            search_query = {
                "size": limit,
                "query": {
                    "bool": {
                        "should": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit,
                                        "boost": 0.7
                                    }
                                }
                            },
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["content", "name"],
                                    "type": "best_fields",
                                    "boost": 0.3
                                }
                            }
                        ]
                    }
                }
            }

            response = self.client.search(
                index=self.index_name,
                body=search_query
            )

            documents = []
            for hit in response["hits"]["hits"]:
                doc = self._create_document_from_hit(hit)
                documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")
            return []

    def drop(self) -> None:
        """Delete the index if it exists."""
        try:
            if self.exists():
                logger.debug(f"Deleting index: {self.index_name}")
                self.client.indices.delete(index=self.index_name)
                logger.info(f"Successfully deleted index: {self.index_name}")
            else:
                logger.info(f"Index {self.index_name} does not exist, nothing to delete")
        except Exception as e:
            logger.error(f"Error deleting index {self.index_name}: {e}")
            raise

    async def async_drop(self) -> None:
        """Async version of drop method."""
        try:
            if await self.async_exists():
                logger.debug(f"Deleting index: {self.index_name}")
                await self.async_client.indices.delete(index=self.index_name)
                logger.info(f"Successfully deleted index: {self.index_name}")
            else:
                logger.info(f"Index {self.index_name} does not exist, nothing to delete")
        except Exception as e:
            logger.error(f"Error deleting index {self.index_name}: {e}")
            raise

    def exists(self) -> bool:
        """
        Check if the index exists

        Returns:
            bool: True if the index exists, False otherwise
        """
        try:
            return self.client.indices.exists(index=self.index_name)
        except Exception as e:
            logger.error(f"Error checking if index exists: {e}")
            return False

    async def async_exists(self) -> bool:
        """Async version of exists method."""
        try:
            return await self.async_client.indices.exists(index=self.index_name)
        except Exception as e:
            logger.error(f"Error checking if index exists: {e}")
            return False

    def optimize(self) -> None:
        """Optimize the index for better performance."""
        try:
            if self.exists():
                # Force merge to optimize the index
                self.client.indices.forcemerge(
                    index=self.index_name,
                    max_num_segments=1
                )
                logger.info(f"Successfully optimized index: {self.index_name}")
        except Exception as e:
            logger.error(f"Error optimizing index {self.index_name}: {e}")
            raise

    def delete(self) -> bool:
        """
        Delete all documents from the index.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.exists():
                self.client.delete_by_query(
                    index=self.index_name,
                    body={"query": {"match_all": {}}},
                    refresh=True
                )
                logger.info(f"Successfully deleted all documents from index: {self.index_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting documents from index {self.index_name}: {e}")
            return False

    # Additional helper methods
    def get_document_by_id(self, document_id: str) -> Document | None:
        """
        Retrieve a document by its ID.

        Args:
            document_id (str): The ID of the document to retrieve

        Returns:
            Optional[Document]: The document if found, None otherwise
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return None

        try:
            response = self.client.get(index=self.index_name, id=document_id)
            if response["found"]:
                # Create a mock hit structure for _create_document_from_hit
                hit = {
                    "_id": document_id,
                    "_source": response["_source"],
                    "_score": 1.0  # Default score for direct retrieval
                }
                return self._create_document_from_hit(hit)
            return None
        except opensearch_exceptions.NotFoundError:
            logger.info(f"Document {document_id} not found in index {self.index_name}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving document {document_id}: {e}")
            return None

    def count(self) -> int:
        """
        Get the number of documents in the index.

        Returns:
            int: Number of documents in the index
        """
        if not self.exists():
            return 0

        try:
            response = self.client.count(index=self.index_name)
            return response["count"]
        except Exception as e:
            logger.error(f"Error counting documents: {e}")
            return 0

    def delete_documents(self, document_ids: List[str]) -> None:
        """
        Delete specific documents from the index by their IDs.

        Args:
            document_ids (List[str]): List of document IDs to delete
        """
        if not self.exists():
            logger.warning(f"Index {self.index_name} does not exist")
            return

        if not document_ids:
            logger.warning("No document IDs provided for deletion")
            return

        try:
            # Prepare bulk delete operation
            bulk_data = []
            for doc_id in document_ids:
                bulk_data.append({"delete": {"_index": self.index_name, "_id": doc_id}})

            if bulk_data:
                response = self.client.bulk(body=bulk_data, refresh=True)
                # Check for errors in bulk response
                if response.get("errors"):
                    for item in response.get("items", []):
                        if "delete" in item and "error" in item["delete"]:
                            logger.error(f"Bulk delete error: {item['delete']['error']}")
                else:
                    logger.info(f"Successfully deleted {len(document_ids)} documents from index {self.index_name}")

        except Exception as e:
            logger.error(f"Error executing bulk delete operation: {e}")
            raise

    def _get_default_parameters(self, engine: str) -> Dict[str, Any]:
        """Get default parameters for the specified engine.

        Args:
            engine (str): The KNN engine being used

        Returns:
            Dict[str, Any]: Default parameters for the engine
        """
        if engine == "nmslib":
            return {"ef_construction": 512, "m": 16}
        elif engine == "faiss":
            return {"ef_construction": 512, "m": 16}
        elif engine == "lucene":
            return {"m": 16, "ef_construction": 512}
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
                    "content": {
                        "type": "text",
                        "analyzer": "standard"
                    },
                    "name": {
                        "type": "text",
                        "fields": {
                            "keyword": {
                                "type": "keyword",
                                "ignore_above": 256
                            }
                        }
                    },
                    "meta_data": {
                        "type": "object",
                        "dynamic": True,
                        "properties": {
                            "*": {
                                "type": "text",
                                "fields": {
                                    "keyword": {
                                        "type": "keyword",
                                        "ignore_above": 256
                                    }
                                }
                            }
                        }
                    },
                    "usage": {
                        "type": "object",
                        "enabled": True
                    },
                    "reranking_score": {
                        "type": "float"
                    }
                }
            },
        }

    @property
    def client(self) -> OpenSearch:
        """
        Get or create OpenSearch client.

        Returns:
            OpenSearch: The OpenSearch Client
        """
        if self._client is None:
            logger.debug("Creating an OpenSearch client")
            try:
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
                # Test connection
                self._client.ping()
                logger.info("Successfully connected to OpenSearch")
            except Exception as e:
                logger.error(f"Failed to create OpenSearch client: {e}")
                raise
        return self._client

    @property
    def async_client(self) -> AsyncOpenSearch:
        """
        Get or create async OpenSearch client.

        Returns:
            AsyncOpenSearch: The async OpenSearch Client
        """
        if self._async_client is None:
            logger.debug("Creating an async OpenSearch client")
            try:
                self._async_client = AsyncOpenSearch(
                    hosts=self.hosts,
                    http_auth=self.http_auth,
                    use_ssl=self.use_ssl,
                    verify_certs=self.verify_certs,
                    connection_class=self.connection_class,
                    timeout=self.timeout,
                    max_retries=self.max_retries,
                    retry_on_timeout=self.retry_on_timeout
                )
                logger.info("Successfully created async OpenSearch client")
            except Exception as e:
                logger.error(f"Failed to create async OpenSearch client: {e}")
                raise
        return self._async_client
