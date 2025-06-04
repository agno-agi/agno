import json
from hashlib import md5
from typing import Any, Dict, List, Optional, Union

try:
    import asyncio

    from pymilvus import AsyncMilvusClient, MilvusClient  # type: ignore
except ImportError:
    raise ImportError("The `pymilvus` package is not installed. Please install it via `pip install pymilvus`.")

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

MILVUS_DISTANCE_MAP = {
    Distance.cosine: "COSINE",
    Distance.l2: "L2",
    Distance.max_inner_product: "IP",
}


class Milvus(VectorDb):
    def __init__(
        self,
        collection: str,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        uri: str = "http://localhost:19530",
        token: Optional[str] = None,
        search_type: SearchType = SearchType.vector,
        reranker: Optional[Reranker] = None,
        sparse_vector_dimensions: int = 10000,
        **kwargs,
    ):
        """
        Milvus vector database.

        Args:
            collection (str): Name of the Milvus collection.
            embedder (Embedder): Embedder to use for embedding documents.
            distance (Distance): Distance metric to use for vector similarity.
            uri (Optional[str]): URI of the Milvus server.
                - If you only need a local vector database for small scale data or prototyping,
                  setting the uri as a local file, e.g.`./milvus.db`, is the most convenient method,
                  as it automatically utilizes [Milvus Lite](https://milvus.io/docs/milvus_lite.md)
                  to store all data in this file.
                - If you have large scale of data, say more than a million vectors, you can set up
                  a more performant Milvus server on [Docker or Kubernetes](https://milvus.io/docs/quickstart.md).
                  In this setup, please use the server address and port as your uri, e.g.`http://localhost:19530`.
                  If you enable the authentication feature on Milvus,
                  use "<your_username>:<your_password>" as the token, otherwise don't set the token.
                - If you use [Zilliz Cloud](https://zilliz.com/cloud), the fully managed cloud
                  service for Milvus, adjust the `uri` and `token`, which correspond to the
                  [Public Endpoint and API key](https://docs.zilliz.com/docs/on-zilliz-cloud-console#cluster-details)
                  in Zilliz Cloud.
            token (Optional[str]): Token for authentication with the Milvus server.
            search_type (SearchType): Type of search to perform (vector, keyword, or hybrid)
            reranker (Optional[Reranker]): Reranker to use for hybrid search results
            **kwargs: Additional keyword arguments to pass to the MilvusClient.
        """
        self.collection: str = collection

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        self.distance: Distance = distance
        self.uri: str = uri
        self.token: Optional[str] = token
        self._client: Optional[MilvusClient] = None
        self._async_client: Optional[AsyncMilvusClient] = None
        self.search_type: SearchType = search_type
        self.reranker: Optional[Reranker] = reranker
        self.sparse_vector_dimensions = sparse_vector_dimensions
        self.kwargs = kwargs

    @property
    def client(self) -> MilvusClient:
        if self._client is None:
            log_debug("Creating Milvus Client")
            self._client = MilvusClient(
                uri=self.uri,
                token=self.token,
                **self.kwargs,
            )
        return self._client

    @property
    def async_client(self) -> AsyncMilvusClient:
        if not hasattr(self, "_async_client") or self._async_client is None:
            log_debug("Creating Async Milvus Client")
            self._async_client = AsyncMilvusClient(
                uri=self.uri,
                token=self.token,
                **self.kwargs,
            )
        return self._async_client

    def _get_sparse_vector(self, text: str) -> Dict[int, float]:
        """
        Convert text into a sparse vector representation using a simple TF-IDF-like scoring.

        This method creates a sparse vector by:
        1. Converting text to lowercase and splitting into words
        2. Computing word frequencies
        3. Creating a hash-based word ID (modulo 10000)
        4. Computing a TF-IDF-like score for each word

        Args:
            text: Input text to convert to sparse vector

        Returns:
            Dictionary mapping word IDs (int) to their TF-IDF-like scores (float)
        """
        from collections import Counter

        import numpy as np

        # Simple word-based sparse vector creation
        words = text.lower().split()
        word_counts = Counter(words)

        # Create sparse vector (word_id: tf-idf_score)
        sparse_vector = {}
        for word, count in word_counts.items():
            word_id = hash(word) % self.sparse_vector_dimensions
            # Simple tf-idf-like score
            score = count * np.log(1 + len(words))
            sparse_vector[word_id] = float(score)

        return sparse_vector

    def _create_hybrid_schema(self) -> Any:
        """Create a schema for hybrid collection with all necessary fields."""
        from pymilvus import DataType

        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
        )

        # Define field configurations
        fields = [
            ("id", DataType.VARCHAR, 128, True),  # (name, type, max_length, is_primary)
            ("name", DataType.VARCHAR, 1000, False),
            ("content", DataType.VARCHAR, 65535, False),
            ("text", DataType.VARCHAR, 1000, False),
            ("meta_data", DataType.VARCHAR, 65535, False),
            ("usage", DataType.VARCHAR, 65535, False),
        ]

        # Add VARCHAR fields
        for field_name, datatype, max_length, is_primary in fields:
            schema.add_field(field_name=field_name, datatype=datatype, max_length=max_length, is_primary=is_primary)

        # Add vector fields
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=self.dimensions)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

        return schema

    def _prepare_hybrid_index_params(self) -> Any:
        """Prepare index parameters for both dense and sparse vectors."""
        index_params = self.client.prepare_index_params()

        # Add indexes for both vector types
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_index",
            index_type="IVF_FLAT",
            metric_type=self._get_metric_type(),
            params={"nlist": 1024},
        )

        index_params.add_index(
            field_name="sparse_vector",
            index_name="sparse_index",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
            params={"drop_ratio_build": 0.2},
        )

        return index_params

    def _prepare_document_data(
        self, document: Document, include_vectors: bool = True
    ) -> Dict[str, Union[str, List[float], Dict[int, float], None]]:
        """
        Prepare document data for insertion.

        Args:
            document: Document to prepare data for
            include_vectors: Whether to include vector data

        Returns:
            Dictionary with document data where values can be strings, vectors (List[float]),
            sparse vectors (Dict[int, float]), or None
        """
        # Ensure document is embedded if vectors are needed
        if include_vectors and document.embedding is None:
            document.embed(embedder=self.embedder)
            if document.embedding is None:
                raise ValueError(f"Failed to embed document: {document.name}")

        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()

        # Convert dictionary fields to JSON strings
        meta_data_str = json.dumps(document.meta_data) if document.meta_data else "{}"
        usage_str = json.dumps(document.usage) if document.usage else "{}"

        data: Dict[str, Union[str, List[float], Dict[int, float], None]] = {
            "id": doc_id,
            "text": cleaned_content,
            "name": document.name,
            "meta_data": meta_data_str,
            "content": cleaned_content,
            "usage": usage_str,
        }

        if include_vectors:
            if self.search_type == SearchType.hybrid:
                data.update(
                    {
                        "dense_vector": document.embedding,  # List[float] or None # Dict[int, float]
                        "sparse_vector": self._get_sparse_vector(cleaned_content),
                    }
                )
            else:
                vector_data: Optional[List[float]] = document.embedding
                data["vector"] = vector_data

        return data

    def _create_hybrid_collection(self) -> None:
        """Create a collection specifically for hybrid search."""
        log_debug(f"Creating hybrid collection: {self.collection}")

        schema = self._create_hybrid_schema()
        index_params = self._prepare_hybrid_index_params()

        self.client.create_collection(collection_name=self.collection, schema=schema, index_params=index_params)

    async def _async_create_hybrid_collection(self) -> None:
        """Create a hybrid collection asynchronously."""
        log_debug(f"Creating hybrid collection asynchronously: {self.collection}")

        schema = self._create_hybrid_schema()
        index_params = self._prepare_hybrid_index_params()

        await self.async_client.create_collection(
            collection_name=self.collection, schema=schema, index_params=index_params
        )

    def create(self) -> None:
        """Create a collection based on search type if it doesn't exist."""
        if self.exists():
            return

        if self.search_type == SearchType.hybrid:
            self._create_hybrid_collection()
            return

        _distance = self._get_metric_type()
        log_debug(f"Creating collection: {self.collection}")
        self.client.create_collection(
            collection_name=self.collection,
            dimension=self.dimensions,
            metric_type=_distance,
            id_type="string",
            max_length=65_535,
        )

    async def async_create(self) -> None:
        """Create collection asynchronously based on search type."""
        # Use the synchronous client to check if collection exists
        if not self.client.has_collection(self.collection):
            if self.search_type == SearchType.hybrid:
                await self._async_create_hybrid_collection()
            else:
                # Original async create logic for regular vector search
                _distance = self._get_metric_type()
                log_debug(f"Creating collection asynchronously: {self.collection}")
                await self.async_client.create_collection(
                    collection_name=self.collection,
                    dimension=self.dimensions,
                    metric_type=_distance,
                    id_type="string",
                    max_length=65_535,
                )

    def doc_exists(self, document: Document) -> bool:
        """
        Validating if the document exists or not

        Args:
            document (Document): Document to validate
        """
        if self.client:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            collection_points = self.client.get(
                collection_name=self.collection,
                ids=[doc_id],
            )
            return len(collection_points) > 0
        return False

    async def async_doc_exists(self, document: Document) -> bool:
        """
        Check if document exists asynchronously.
        AsyncMilvusClient supports get().
        """
        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()
        collection_points = await self.async_client.get(
            collection_name=self.collection,
            ids=[doc_id],
        )
        return len(collection_points) > 0

    def name_exists(self, name: str) -> bool:
        """
        Validates if a document with the given name exists in the collection.

        Args:
            name (str): The name of the document to check.

        Returns:
            bool: True if a document with the given name exists, False otherwise.
        """
        if self.client:
            expr = f"name == '{name}'"
            scroll_result = self.client.query(
                collection_name=self.collection,
                filter=expr,
                limit=1,
            )
            return len(scroll_result[0]) > 0
        return False

    def id_exists(self, id: str) -> bool:
        if self.client:
            collection_points = self.client.get(
                collection_name=self.collection,
                ids=[id],
            )
            return len(collection_points) > 0
        return False

    def _insert_hybrid_document(self, document: Document) -> None:
        """Insert a document with both dense and sparse vectors."""
        data = self._prepare_document_data(document, include_vectors=True)

        self.client.insert(
            collection_name=self.collection,
            data=data,
        )
        log_debug(f"Inserted hybrid document: {document.name} ({document.meta_data})")

    async def _async_insert_hybrid_document(self, document: Document) -> None:
        """Insert a document with both dense and sparse vectors asynchronously."""
        data = self._prepare_document_data(document, include_vectors=True)

        await self.async_client.insert(
            collection_name=self.collection,
            data=data,
        )
        log_debug(f"Inserted hybrid document asynchronously: {document.name} ({document.meta_data})")

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents based on search type."""
        log_debug(f"Inserting {len(documents)} documents")

        if self.search_type == SearchType.hybrid:
            for document in documents:
                self._insert_hybrid_document(document)
        else:
            for document in documents:
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                doc_id = md5(cleaned_content.encode()).hexdigest()

                meta_data = document.meta_data or {}
                if filters:
                    meta_data.update(filters)

                data = {
                    "id": doc_id,
                    "vector": document.embedding,
                    "name": document.name,
                    "meta_data": meta_data,
                    "content": cleaned_content,
                    "usage": document.usage,
                }
                self.client.insert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Inserted document: {document.name} ({meta_data})")

        log_info(f"Inserted {len(documents)} documents")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously based on search type."""
        log_debug(f"Inserting {len(documents)} documents asynchronously")

        if self.search_type == SearchType.hybrid:
            await asyncio.gather(*[self._async_insert_hybrid_document(doc) for doc in documents])
        else:

            async def process_document(document):
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                doc_id = md5(cleaned_content.encode()).hexdigest()

                meta_data = document.meta_data or {}
                if filters:
                    meta_data.update(filters)

                data = {
                    "id": doc_id,
                    "vector": document.embedding,
                    "name": document.name,
                    "meta_data": meta_data,
                    "content": cleaned_content,
                    "usage": document.usage,
                }
                await self.async_client.insert(
                    collection_name=self.collection,
                    data=data,
                )
                log_debug(f"Inserted document asynchronously: {document.name} ({document.meta_data})")
                return data

            await asyncio.gather(*[process_document(doc) for doc in documents])

        log_info(f"Inserted {len(documents)} documents asynchronously")

    def upsert_available(self) -> bool:
        """
        Check if upsert operation is available.

        Returns:
            bool: Always returns True.
        """
        return True

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert documents into the database.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_debug(f"Upserting {len(documents)} documents")
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            data = {
                "id": doc_id,
                "vector": document.embedding,
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            self.client.upsert(
                collection_name=self.collection,
                data=data,
            )
            log_debug(f"Upserted document: {document.name} ({document.meta_data})")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_debug(f"Upserting {len(documents)} documents asynchronously")

        async def process_document(document):
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            data = {
                "id": doc_id,
                "vector": document.embedding,
                "name": document.name,
                "meta_data": document.meta_data,
                "content": cleaned_content,
                "usage": document.usage,
            }
            await self.async_client.upsert(
                collection_name=self.collection,
                data=data,
            )
            log_debug(f"Upserted document asynchronously: {document.name} ({document.meta_data})")
            return data

        # Process all documents in parallel
        await asyncio.gather(*[process_document(doc) for doc in documents])

        log_debug(f"Upserted {len(documents)} documents asynchronously in parallel")

    def _get_metric_type(self) -> str:
        """
        Get the Milvus metric type string for the current distance setting.

        Returns:
            Milvus metric type string, defaults to "COSINE" if distance not found
        """
        return MILVUS_DISTANCE_MAP.get(self.distance, "COSINE")

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Search for documents matching the query.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search

        Returns:
            List[Document]: List of matching documents
        """
        if self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        results = self.client.search(
            collection_name=self.collection,
            data=[query_embedding],
            filter=self._build_expr(filters),
            output_fields=["*"],
            limit=limit,
        )

        # Build search results
        search_results: List[Document] = []
        for result in results[0]:
            search_results.append(
                Document(
                    id=result["id"],
                    name=result["entity"].get("name", None),
                    meta_data=result["entity"].get("meta_data", {}),
                    content=result["entity"].get("content", ""),
                    embedder=self.embedder,
                    embedding=result["entity"].get("vector", None),
                    usage=result["entity"].get("usage", None),
                )
            )

        log_info(f"Found {len(search_results)} documents")
        return search_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        if self.search_type == SearchType.hybrid:
            return self.hybrid_search(query, limit, filters)

        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        results = await self.async_client.search(
            collection_name=self.collection,
            data=[query_embedding],
            filter=self._build_expr(filters),
            output_fields=["*"],
            limit=limit,
        )

        # Build search results
        search_results: List[Document] = []
        for result in results[0]:
            search_results.append(
                Document(
                    id=result["id"],
                    name=result["entity"].get("name", None),
                    meta_data=result["entity"].get("meta_data", {}),
                    content=result["entity"].get("content", ""),
                    embedder=self.embedder,
                    embedding=result["entity"].get("vector", None),
                    usage=result["entity"].get("usage", None),
                )
            )

        log_info(f"Found {len(search_results)} documents")
        return search_results

    def hybrid_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform a hybrid search combining dense and sparse vector similarity.

        Args:
            query (str): Query string to search for
            limit (int): Maximum number of results to return
            filters (Optional[Dict[str, Any]]): Filters to apply to the search

        Returns:
            List[Document]: List of matching documents
        """
        from pymilvus import AnnSearchRequest, RRFRanker

        # Get query embeddings
        dense_vector = self.embedder.get_embedding(query)
        sparse_vector = self._get_sparse_vector(query)

        if dense_vector is None:
            logger.error(f"Error getting dense embedding for Query: {query}")
            return []

        if self._client is None:
            logger.error("Milvus client not initialized")
            return []

        try:
            # Refer to docs for details- https://milvus.io/docs/multi-vector-search.md

            # Create search request for dense vectors
            dense_search_param = {
                "data": [dense_vector],
                "anns_field": "dense_vector",
                "param": {"metric_type": self._get_metric_type(), "params": {"nprobe": 10}},
                "limit": limit
                * 2,  # Fetch more candidates for better reranking quality - each vector search returns 2x results which are then merged and reranked
            }

            # Create search request for sparse vectors
            sparse_search_param = {
                "data": [sparse_vector],
                "anns_field": "sparse_vector",
                "param": {"metric_type": "IP", "params": {"drop_ratio_build": 0.2}},
                "limit": limit * 2,  # Match dense search limit to ensure balanced candidate pool for reranking
            }

            # Create search requests
            dense_request = AnnSearchRequest(**dense_search_param)
            sparse_request = AnnSearchRequest(**sparse_search_param)
            reqs = [dense_request, sparse_request]

            # Use RRFRanker for balanced importance between vectors
            ranker = RRFRanker(60)  # Default k=60

            log_info("Performing hybrid search")
            results = self._client.hybrid_search(
                collection_name=self.collection, reqs=reqs, ranker=ranker, limit=limit, output_fields=["*"]
            )

            # Build search results
            search_results: List[Document] = []
            for hits in results:
                for hit in hits:
                    entity = hit.get("entity", {})
                    meta_data = json.loads(entity.get("meta_data", "{}")) if entity.get("meta_data") else {}
                    usage = json.loads(entity.get("usage", "{}")) if entity.get("usage") else None

                    search_results.append(
                        Document(
                            id=hit.get("id"),
                            name=entity.get("name", None),
                            meta_data=meta_data,  # Now a dictionary
                            content=entity.get("content", ""),
                            embedder=self.embedder,
                            embedding=entity.get("dense_vector", None),
                            usage=usage,  # Now a dictionary or None
                        )
                    )

            # Apply additional reranking if custom reranker is provided
            if self.reranker and search_results:
                search_results = self.reranker.rerank(query=query, documents=search_results)

            log_info(f"Found {len(search_results)} documents")
            return search_results

        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")
            return []

    def drop(self) -> None:
        if self.exists():
            log_debug(f"Deleting collection: {self.collection}")
            self.client.drop_collection(self.collection)

    async def async_drop(self) -> None:
        """
        Drop collection asynchronously.
        AsyncMilvusClient supports drop_collection().
        """
        # Check using synchronous client
        if self.client.has_collection(self.collection):
            log_debug(f"Deleting collection asynchronously: {self.collection}")
            await self.async_client.drop_collection(self.collection)

    def exists(self) -> bool:
        if self.client:
            if self.client.has_collection(self.collection):
                return True
        return False

    async def async_exists(self) -> bool:
        """
        Check if collection exists asynchronously.

        has_collection() is not supported by AsyncMilvusClient,
        so we use the synchronous client.
        """
        return self.client.has_collection(self.collection)

    def get_count(self) -> int:
        return self.client.get_collection_stats(collection_name="test_collection")["row_count"]

    def delete(self) -> bool:
        if self.client:
            self.client.drop_collection(self.collection)
            return True
        return False

    def _build_expr(self, filters: Optional[Dict[str, Any]]) -> Optional[str]:
        """Build Milvus expression from filters."""
        if not filters:
            return None

        expressions = []
        for k, v in filters.items():
            if isinstance(v, (list, tuple)):
                # For array values, use json_contains_any
                values_str = json.dumps(v)
                expr = f'json_contains_any(meta_data, {values_str}, "{k}")'
            elif isinstance(v, str):
                # For string values
                expr = f'meta_data["{k}"] == "{v}"'
            elif isinstance(v, bool):
                # For boolean values
                expr = f'meta_data["{k}"] == {str(v).lower()}'
            elif isinstance(v, (int, float)):
                # For numeric values
                expr = f'meta_data["{k}"] == {v}'
            elif v is None:
                # For null values
                expr = f'meta_data["{k}"] is null'
            else:
                # For other types, convert to string
                expr = f'meta_data["{k}"] == "{str(v)}"'

            expressions.append(expr)

        if expressions:
            return " and ".join(expressions)
        return None

    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
