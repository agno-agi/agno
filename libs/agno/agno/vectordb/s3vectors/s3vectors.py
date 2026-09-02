from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`")

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


class DataType(str, Enum):
    """
    Supported data types for S3Vectors vector operations.

    Attributes:
        float32: 32-bit floating point data type for vector components
    """

    float32 = "float32"


class DistanceMetric(str, Enum):
    """
    Supported distance metrics for S3Vectors similarity calculations.

    Attributes:
        cosine: Cosine similarity distance metric
        euclidean: Euclidean (L2) distance metric
    """

    cosine = "cosine"
    euclidean = "euclidean"


class S3VectorsDb(VectorDb):
    """
    Amazon S3Vectors vector database implementation with comprehensive search capabilities.

    This class provides a complete vector database solution using Amazon S3Vectors as the backend,
    supporting vector similarity search with sub-second response times and dedicated API operations
    for vector storage and retrieval.

    Features:
        - Multiple distance metrics (cosine, euclidean)
        - Synchronous and asynchronous operations
        - Bulk document operations (insert, upsert, delete)
        - Advanced filtering capabilities via metadata
        - Optional reranking support
        - Comprehensive error handling and logging
        - Pagination support for large datasets

    Attributes:
        bucket_name (str): Name of the S3Vectors bucket
        index_name (str): Name of the vector index within the bucket
        dimension (int): Dimensionality of the vector embeddings
        distance_metric (DistanceMetric): Distance metric for similarity calculations
        data_type (DataType): Data type for vector components
        search_type (SearchType): Default search type (vector only for S3Vectors)
        embedder (Embedder): Embedder instance for generating vector embeddings
        reranker (Optional[Reranker]): Optional reranker for improving search results
    """

    def __init__(
        self,
        bucket_name: str,
        index_name: str,
        dimension: int,
        embedder: Optional[Embedder] = None,
        distance_metric: DistanceMetric = DistanceMetric.cosine,
        data_type: DataType = DataType.float32,
        search_type: SearchType = SearchType.vector,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        region_name: str = "us-east-1",
        endpoint_url: Optional[str] = None,
        reranker: Optional[Reranker] = None,
        non_filterable_metadata_keys: Optional[List[str]] = None,
    ):
        """
        Initialize S3Vectors vector database.

        Args:
            bucket_name: Name of the S3Vectors bucket
            index_name: Name of the vector index within the bucket
            dimension: Dimensionality of the vector embeddings
            embedder: Embedder instance for generating vector embeddings
            distance_metric: Distance metric for similarity calculations
            data_type: Data type for vector components (must be float32)
            search_type: Default search type (only vector supported for S3Vectors)
            aws_access_key_id: AWS access key ID (optional, uses default credentials if not provided)
            aws_secret_access_key: AWS secret access key (optional)
            aws_session_token: AWS session token (optional)
            region_name: AWS region name
            endpoint_url: Custom endpoint URL (optional)
            reranker: Optional reranker for improving search results
            non_filterable_metadata_keys: List of metadata keys that cannot be filtered

        Raises:
            ValueError: If unsupported data type or distance metric is specified
            ImportError: If boto3 is not installed
        """
        self.bucket_name = bucket_name
        self.index_name = index_name
        self.dimension = dimension
        self.distance_metric = distance_metric
        self.data_type = data_type
        self.search_type = search_type
        self.non_filterable_metadata_keys = non_filterable_metadata_keys or []
        self.max_results = 10  # Default max results for search (compatibility with Agent)

        self._validate_configuration()

        self.aws_config = {
            "region_name": region_name,
            "endpoint_url": endpoint_url,
        }

        if aws_access_key_id and aws_secret_access_key:
            self.aws_config.update(
                {
                    "aws_access_key_id": aws_access_key_id,
                    "aws_secret_access_key": aws_secret_access_key,
                }
            )
            if aws_session_token:
                self.aws_config["aws_session_token"] = aws_session_token

        self._client: Optional[Any] = None

        self.embedder = self._initialize_embedder(embedder)
        self.reranker = reranker

        if self.reranker:
            log_debug(f"Reranker configured: {type(self.reranker).__name__}")

    def _validate_configuration(self) -> None:
        """
        Validate configuration parameters.

        Raises:
            ValueError: If configuration is invalid
        """
        if self.data_type != DataType.float32:
            raise ValueError(f"Unsupported data type: {self.data_type}. Only float32 is supported.")

        if self.distance_metric not in [DistanceMetric.cosine, DistanceMetric.euclidean]:
            raise ValueError(f"Unsupported distance metric: {self.distance_metric}")

        if self.search_type != SearchType.vector:
            logger.warning("S3Vectors only supports vector search. Falling back to vector search.")
            self.search_type = SearchType.vector

        if self.dimension <= 0:
            raise ValueError(f"Dimension must be positive, got: {self.dimension}")

    def _initialize_embedder(self, embedder: Optional[Embedder]) -> Embedder:
        """
        Initialize embedder with fallback to default.

        Args:
            embedder: Optional embedder instance

        Returns:
            Embedder: Configured embedder instance

        Note:
            If no embedder is provided, defaults to OpenAIEmbedder
        """
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        else:
            log_info(f"Using provided embedder: {type(embedder).__name__}")
        return embedder

    @property
    def client(self) -> Any:
        """
        Get or create S3Vectors client.

        Returns:
            boto3 S3Vectors client: Configured S3Vectors client instance

        Note:
            Client is lazily initialized and cached for reuse
        """
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> Any:
        """
        Create S3Vectors client with connection testing.

        Returns:
            boto3 client: Configured and tested S3Vectors client

        Raises:
            Exception: If client creation or connection test fails
        """
        log_debug("Creating S3Vectors client")
        try:
            client = boto3.client("s3vectors", **self.aws_config)

            client.list_vector_buckets(maxResults=1)
            log_info("Successfully connected to S3Vectors")
            return client
        except Exception as e:
            logger.error(f"Failed to create S3Vectors client: {e}")
            raise

    def create(self) -> None:
        """
        Create the vector bucket and index if they do not exist.

        Note:
            This is a synchronous operation that will create both the bucket
            and index with the configured settings if they don't already exist.
        """
        self._execute_with_timing("create", self._create_bucket_and_index_impl)

    async def async_create(self) -> None:
        """
        Create the vector bucket and index asynchronously if they do not exist.

        Note:
            Asynchronous version of create() method.
        """
        await self._async_execute_with_timing("async_create", self._async_create_bucket_and_index_impl)

    def _create_bucket_and_index_impl(self) -> None:
        """
        Implementation for synchronous bucket and index creation.

        Creates the bucket and index with the configured settings if they don't exist.
        """
        if not self._bucket_exists():
            log_debug(f"Creating vector bucket: {self.bucket_name}")
            try:
                self.client.create_vector_bucket(
                    vectorBucketName=self.bucket_name, encryptionConfiguration={"sseType": "AES256"}
                )
                log_info(f"Successfully created vector bucket: {self.bucket_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConflictException":
                    log_debug(f"Vector bucket {self.bucket_name} already exists")
                else:
                    raise
        else:
            log_debug(f"Vector bucket {self.bucket_name} already exists")

        if not self._index_exists():
            log_debug(f"Creating vector index: {self.index_name}")
            metadata_config = {}
            if self.non_filterable_metadata_keys:
                metadata_config = {"nonFilterableMetadataKeys": self.non_filterable_metadata_keys}

            self.client.create_index(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                dataType=self.data_type,
                dimension=self.dimension,
                distanceMetric=self.distance_metric,
                metadataConfiguration=metadata_config if metadata_config else None,
            )
            log_info(f"Successfully created vector index: {self.index_name}")
        else:
            log_debug(f"Vector index {self.index_name} already exists")

    async def _async_create_bucket_and_index_impl(self) -> None:
        """
        Implementation for asynchronous bucket and index creation.

        Creates the bucket and index with the configured settings if they don't exist.
        """
        await asyncio.to_thread(self._create_bucket_and_index_impl)

    def exists(self) -> bool:
        """
        Check if the vector bucket and index exist.

        Returns:
            bool: True if both bucket and index exist, False otherwise

        Note:
            Returns False if an error occurs during the check
        """
        try:
            return self._bucket_exists() and self._index_exists()
        except Exception as e:
            logger.error(f"Error checking if bucket and index exist: {e}")
            return False

    async def async_exists(self) -> bool:
        """
        Check if the vector bucket and index exist asynchronously.

        Returns:
            bool: True if both bucket and index exist, False otherwise

        Note:
            Returns False if an error occurs during the check
        """
        try:
            return await asyncio.to_thread(self.exists)
        except Exception as e:
            logger.error(f"Error checking if bucket and index exist: {e}")
            return False

    def _bucket_exists(self) -> bool:
        """
        Check if the vector bucket exists.

        Returns:
            bool: True if bucket exists, False otherwise
        """
        try:
            self.client.get_vector_bucket(vectorBucketName=self.bucket_name)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                return False
            raise

    def _index_exists(self) -> bool:
        """
        Check if the vector index exists.

        Returns:
            bool: True if index exists, False otherwise
        """
        try:
            self.client.get_index(vectorBucketName=self.bucket_name, indexName=self.index_name)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                return False
            raise

    def drop(self) -> None:
        """
        Delete the vector index and optionally the bucket.

        Warning:
            This operation permanently deletes the index and all its data.
            The bucket is only deleted if it contains no other indexes.
        """
        self._execute_with_timing("drop", self._drop_index_and_bucket_impl)

    async def async_drop(self) -> None:
        """
        Delete the vector index and optionally the bucket asynchronously.

        Warning:
            This operation permanently deletes the index and all its data.
            The bucket is only deleted if it contains no other indexes.
        """
        await self._async_execute_with_timing("async_drop", self._async_drop_index_and_bucket_impl)

    def _drop_index_and_bucket_impl(self) -> None:
        """
        Implementation for synchronous index and bucket deletion.

        Deletes the index if it exists, and the bucket if it's empty.
        """
        if self._index_exists():
            log_debug(f"Deleting vector index: {self.index_name}")
            self.client.delete_index(vectorBucketName=self.bucket_name, indexName=self.index_name)
            log_info(f"Successfully deleted vector index: {self.index_name}")
        else:
            log_info(f"Vector index {self.index_name} does not exist, nothing to delete")

        try:
            response = self.client.list_indexes(vectorBucketName=self.bucket_name, maxResults=1)
            if not response.get("indexes"):
                log_debug(f"Deleting vector bucket: {self.bucket_name}")
                self.client.delete_vector_bucket(vectorBucketName=self.bucket_name)
                log_info(f"Successfully deleted vector bucket: {self.bucket_name}")
            else:
                log_info(f"Vector bucket {self.bucket_name} contains other indexes, not deleting")
        except ClientError as e:
            if e.response["Error"]["Code"] != "NotFoundException":
                logger.error(f"Error checking bucket indexes: {e}")

    async def _async_drop_index_and_bucket_impl(self) -> None:
        """
        Implementation for asynchronous index and bucket deletion.

        Deletes the index if it exists, and the bucket if it's empty.
        """
        await asyncio.to_thread(self._drop_index_and_bucket_impl)

    def optimize(self) -> None:
        """
        Optimize the index for better performance.

        Note:
            S3Vectors handles optimization automatically, so this is a no-op.
        """
        log_info("S3Vectors handles optimization automatically, no action needed")

    def count(self) -> int:
        """
        Get the number of vectors in the index.

        Returns:
            int: Number of vectors in the index, 0 if index doesn't exist or on error
        """
        log_debug(f"Counting vectors in index: {self.bucket_name}/{self.index_name}")

        if not self.exists():
            log_debug("Bucket or index does not exist, returning count 0")
            return 0

        try:
            count = 0
            next_token = None

            while True:
                params = {
                    "vectorBucketName": self.bucket_name,
                    "indexName": self.index_name,
                    "maxResults": 500,
                    "returnData": False,
                    "returnMetadata": False,
                }

                if next_token:
                    params["nextToken"] = next_token

                response = self.client.list_vectors(**params)
                vectors = response.get("vectors", [])
                count += len(vectors)

                next_token = response.get("nextToken")
                if not next_token:
                    break

            log_debug(f"Index {self.bucket_name}/{self.index_name} contains {count} vectors")
            return count
        except Exception as e:
            logger.error(f"Error counting vectors: {e}")
            return 0

    def doc_exists(self, document: Document) -> bool:
        """
        Check if a document exists in the index by its ID.

        Args:
            document: Document to check for existence

        Returns:
            bool: True if document exists, False otherwise

        Note:
            Returns False if document ID is None or on error
        """
        if document.id is None:
            logger.warning("Document ID is None, cannot check existence")
            return False

        try:
            log_debug(f"Checking if document exists: {document.id}")
            response = self.client.get_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                keys=[document.id],
                returnData=False,
                returnMetadata=False,
            )
            exists = len(response.get("vectors", [])) > 0
            log_debug(f"Document {document.id} exists: {exists}")
            return exists
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                return False
            logger.error(f"Error checking if document exists: {e}")
            return False
        except Exception as e:
            logger.error(f"Error checking if document exists: {e}")
            return False

    async def async_doc_exists(self, document: Document) -> bool:
        """
        Check if a document exists in the index asynchronously by its ID.

        Args:
            document: Document to check for existence

        Returns:
            bool: True if document exists, False otherwise

        Note:
            Returns False if document ID is None or on error
        """
        return await asyncio.to_thread(self.doc_exists, document)

    def name_exists(self, name: str) -> bool:
        """
        Check if a document with the given name exists.

        Args:
            name: Name to search for

        Returns:
            bool: True if document with name exists, False otherwise

        Note:
            This uses search functionality to find documents by name metadata.
        """
        try:
            response = self.client.query_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                topK=1,
                queryVector={"float32": [0.0] * self.dimension},
                filter={"name": name},
                returnMetadata=True,
            )
            return len(response.get("vectors", [])) > 0
        except Exception as e:
            logger.error(f"Error checking if name exists: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """
        Check if a document with the given name exists asynchronously.

        Args:
            name: Name to search for

        Returns:
            bool: True if document with name exists, False otherwise
        """
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        """
        Check if a document with the given ID exists.

        Args:
            id: Document ID to check

        Returns:
            bool: True if document with ID exists, False otherwise
        """
        try:
            log_debug(f"Checking if document ID exists: {id}")
            response = self.client.get_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                keys=[id],
                returnData=False,
                returnMetadata=False,
            )
            exists = len(response.get("vectors", [])) > 0
            log_debug(f"Document ID '{id}' exists: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if ID exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """
        Check if a document with the given content hash exists.

        Args:
            content_hash: Content hash to check

        Returns:
            bool: True if document with content hash exists, False otherwise

        Note:
            For S3Vectors, this searches for documents with content_hash in metadata.
        """
        try:
            import random

            dummy_vector = [random.uniform(0.0001, 0.001) for _ in range(self.dimension)]

            response = self.client.query_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                topK=1,
                queryVector={"float32": dummy_vector},
                filter={"content_hash": content_hash},
                returnMetadata=True,
            )
            return len(response.get("vectors", [])) > 0
        except Exception as e:
            logger.error(f"Error checking if content hash exists: {e}")
            return False

    def get_count(self) -> int:
        """
        Get the number of vectors in the index.

        Returns:
            int: Number of vectors in the index, 0 if index doesn't exist or on error
        """
        return self.count()

    def validate_filters(self, filters: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Validate filters for search operations.

        Args:
            filters: Filters to validate

        Returns:
            Tuple[Dict[str, Any], List[str]]: Valid filters and list of invalid keys
        """
        if not filters:
            return {}, []

        valid_filters = {}
        invalid_keys = []

        for key, value in filters.items():
            if key in self.non_filterable_metadata_keys:
                invalid_keys.append(key)
            else:
                valid_filters[key] = value

        return valid_filters, invalid_keys

    def table_exists(self) -> bool:
        """
        Check if the vector bucket and index exist (compatibility method).

        Returns:
            bool: True if both bucket and index exist, False otherwise
        """
        return self.exists()

    def _prepare_document_for_indexing(self, doc: Document) -> Dict[str, Any]:
        """
        Prepare a document for indexing by ensuring proper structure and embeddings.

        Args:
            doc: Document to prepare

        Returns:
            Dict[str, Any]: S3Vectors vector structure ready for indexing

        Raises:
            ValueError: If document cannot be prepared for indexing

        Note:
            Generates ID if missing, ensures embedding exists, validates dimensions,
            and builds the final S3Vectors vector structure.
        """
        log_debug(f"Preparing document for indexing: {doc.id}")

        if doc.id is None:
            doc.id = str(uuid.uuid4())
            log_debug(f"Generated new document ID: {doc.id}")

        self._ensure_document_embedding(doc)

        self._validate_embedding_dimensions(doc)

        vector_data = self._build_vector_data(doc)

        log_debug(f"Document {doc.id} prepared for indexing")
        return vector_data

    def _ensure_document_embedding(self, doc: Document) -> None:
        """
        Ensure document has an embedding, generating one if necessary.

        Args:
            doc: Document to ensure has embedding

        Raises:
            ValueError: If no embedder is available or embedding generation fails
        """
        if doc.embedding is None:
            try:
                log_debug(f"Generating embedding for document: {doc.id}")
                embedder_to_use = doc.embedder or self.embedder
                if embedder_to_use is None:
                    raise ValueError(f"No embedder available for document {doc.id}")

                doc.embed(embedder_to_use)
                log_debug(f"Successfully generated embedding for document: {doc.id}")
            except Exception as e:
                logger.error(f"Error generating embedding for document {doc.id}: {e}")
                raise

        if doc.embedding is None:
            raise ValueError(f"Document {doc.id} has no embedding and no embedder is configured")

    def _validate_embedding_dimensions(self, doc: Document) -> None:
        """
        Validate that document embedding dimensions match expected dimension.

        Args:
            doc: Document with embedding to validate

        Raises:
            ValueError: If embedding dimensions don't match expected dimension
        """
        if doc.embedding is None:
            raise ValueError(f"Document {doc.id} has no embedding")
        if len(doc.embedding) != self.dimension:
            error_msg = f"Embedding dimension mismatch for document {doc.id}: expected {self.dimension}, got {len(doc.embedding)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        log_debug(f"Document {doc.id} embedding dimension check passed: {len(doc.embedding)}")

    def _build_vector_data(self, doc: Document) -> Dict[str, Any]:
        """
        Build the S3Vectors vector structure for indexing.

        Args:
            doc: Document to build vector structure for

        Returns:
            Dict[str, Any]: S3Vectors vector structure ready for indexing

        Note:
            Includes key, data (embedding), and metadata fields.
        """
        vector_data = {
            "key": doc.id,
            "data": {"float32": [float(x) for x in doc.embedding] if doc.embedding is not None else []},
        }

        metadata: Dict[str, Any] = {}
        if doc.content:
            metadata["content"] = doc.content
        if doc.name:
            metadata["name"] = doc.name
        if doc.content_id:
            metadata["content_id"] = doc.content_id
        if doc.meta_data:
            metadata.update(doc.meta_data)
        if doc.usage:
            metadata["usage"] = str(doc.usage)
        if doc.reranking_score is not None:
            metadata["reranking_score"] = str(doc.reranking_score)

        if hasattr(doc, "content") and doc.content:
            import hashlib

            content_hash = hashlib.md5(doc.content.encode()).hexdigest()
            metadata["content_hash"] = content_hash

        if metadata:
            vector_data["metadata"] = metadata

        return vector_data

    def _create_document_from_vector(self, vector_data: Dict[str, Any], score: Optional[float] = None) -> Document:
        """
        Create a Document object from an S3Vectors vector response.

        Args:
            vector_data: S3Vectors vector data containing key, data, and metadata
            score: Optional similarity score from search results

        Returns:
            Document: Constructed document with search metadata

        Note:
            Adds search score to document metadata for reference.
        """
        metadata = vector_data.get("metadata", {}).copy()

        if score is not None:
            metadata["search_score"] = score

        content = metadata.pop("content", "")
        name = metadata.pop("name", None)
        content_id = metadata.pop("content_id", None)
        metadata.pop("content_hash", None)

        usage_str = metadata.pop("usage", None)
        usage = eval(usage_str) if usage_str else None
        reranking_score = metadata.pop("reranking_score", None)

        doc = Document(
            id=vector_data["key"],
            content=content,
            name=name,
            content_id=content_id,
            meta_data=metadata,
            embedding=vector_data.get("data", {}).get("float32"),
            usage=usage,
            reranking_score=reranking_score,
        )

        log_debug(f"Created document from vector data: {doc.id}")
        return doc

    def insert(
        self,
        documents: List[Document] = None,
        filters: Optional[Dict[str, Any]] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """
        Insert documents into the index.

        Args:
            documents: List of documents to insert
            filters: Optional filters to merge with document metadata
            content_hash: Optional content hash for tracking (compatibility parameter)

        Note:
            Creates bucket and index if they don't exist. Skips documents that fail preparation.
        """
        if isinstance(documents, str) and content_hash is None:
            content_hash = documents
            documents = filters
            filters = None

        if documents is None:
            documents = []

        if content_hash or filters:
            for doc in documents:
                if not hasattr(doc, "meta_data") or doc.meta_data is None:
                    doc.meta_data = {}
                if content_hash:
                    doc.meta_data["content_hash"] = content_hash
                if filters:
                    doc.meta_data.update(filters)

        self._execute_bulk_operation("insert", documents)

    async def async_insert(
        self,
        documents: List[Document] = None,
        filters: Optional[Dict[str, Any]] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """
        Insert documents into the index asynchronously.

        Args:
            documents: List of documents to insert
            filters: Optional filters to merge with document metadata
            content_hash: Optional content hash for tracking (compatibility parameter)

        Note:
            Creates bucket and index if they don't exist. Skips documents that fail preparation.
        """
        if isinstance(documents, str) and content_hash is None:
            content_hash = documents
            documents = filters
            filters = None

        if documents is None:
            documents = []

        if content_hash or filters:
            for doc in documents:
                if not hasattr(doc, "meta_data") or doc.meta_data is None:
                    doc.meta_data = {}
                if content_hash:
                    doc.meta_data["content_hash"] = content_hash
                if filters:
                    doc.meta_data.update(filters)

        await self._async_execute_bulk_operation("insert", documents)

    def upsert_available(self) -> bool:
        """
        Check if upsert operations are supported.

        Returns:
            bool: Always True for S3Vectors

        Note:
            S3Vectors supports upsert through put_vectors operation.
        """
        log_debug("Upsert operations are supported for S3Vectors")
        return True

    def upsert(
        self,
        documents: List[Document] = None,
        filters: Optional[Dict[str, Any]] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """
        Upsert documents in the index (insert if new, update if exists).

        Args:
            documents: List of documents to upsert
            filters: Optional filters to merge with document metadata
            content_hash: Optional content hash for tracking (compatibility parameter)

        Note:
            Creates bucket and index if they don't exist. Skips documents that fail preparation.
            S3Vectors put_vectors operation automatically handles upsert behavior.
        """
        if isinstance(documents, str) and content_hash is None:
            content_hash = documents
            documents = filters
            filters = None

        if documents is None:
            documents = []

        if content_hash or filters:
            for doc in documents:
                if not hasattr(doc, "meta_data") or doc.meta_data is None:
                    doc.meta_data = {}
                if content_hash:
                    doc.meta_data["content_hash"] = content_hash
                if filters:
                    doc.meta_data.update(filters)

        self._execute_bulk_operation("upsert", documents)

    async def async_upsert(
        self,
        documents: List[Document] = None,
        filters: Optional[Dict[str, Any]] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """
        Upsert documents in the index asynchronously (insert if new, update if exists).

        Args:
            documents: List of documents to upsert
            filters: Optional filters to merge with document metadata
            content_hash: Optional content hash for tracking (compatibility parameter)

        Note:
            Creates bucket and index if they don't exist. Skips documents that fail preparation.
            S3Vectors put_vectors operation automatically handles upsert behavior.
        """
        if isinstance(documents, str) and content_hash is None:
            content_hash = documents
            documents = filters
            filters = None

        if documents is None:
            documents = []

        if content_hash or filters:
            for doc in documents:
                if not hasattr(doc, "meta_data") or doc.meta_data is None:
                    doc.meta_data = {}
                if content_hash:
                    doc.meta_data["content_hash"] = content_hash
                if filters:
                    doc.meta_data.update(filters)

        await self._async_execute_bulk_operation("upsert", documents)

    def get_document_by_id(self, document_id: str) -> Optional[Document]:
        """
        Retrieve a document by its ID.

        Args:
            document_id: ID of the document to retrieve

        Returns:
            Optional[Document]: Document if found, None otherwise

        Note:
            Returns None if bucket/index doesn't exist, document not found, or on error.
        """
        log_debug(f"Retrieving document by ID: {document_id}")

        if not self.exists():
            logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
            return None

        try:
            response = self.client.get_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                keys=[document_id],
                returnData=True,
                returnMetadata=True,
            )

            vectors = response.get("vectors", [])
            if vectors:
                doc = self._create_document_from_vector(vectors[0])
                log_debug(f"Successfully retrieved document: {document_id}")
                return doc
            else:
                log_debug(f"Document {document_id} not found")
                return None
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                log_info(f"Document {document_id} not found in index {self.bucket_name}/{self.index_name}")
                return None
            logger.error(f"Error retrieving document {document_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving document {document_id}: {e}")
            return None

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Args:
            content_id: The content ID of the documents to update
            metadata: The metadata to merge with existing metadata

        Note:
            This method finds all documents with the given content_id and updates their metadata.
            The new metadata is merged with existing metadata (not replaced).
        """
        log_debug(f"Updating metadata for content_id: {content_id}")

        if not self.exists():
            logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
            return

        try:
            # First, find all documents with this content_id
            # Get the actual vectors for this content_id
            # First get the document IDs
            # Create a valid dummy vector (small random values instead of all zeros)
            import random

            dummy_vector = [random.uniform(0.0001, 0.001) for _ in range(self.dimension)]

            response = self.client.query_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                topK=30,
                queryVector={"float32": dummy_vector},
                filter={"content_id": content_id},
                returnMetadata=True,
                returnDistance=True,
            )

            vectors = response.get("vectors", [])
            if not vectors:
                log_info(f"No documents found with content_id: {content_id}")
                return

            # Now get full vector data for each document
            document_ids = [v["key"] for v in vectors]
            response = self.client.get_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                keys=document_ids,
                returnData=True,
                returnMetadata=True,
            )

            vectors = response.get("vectors", [])
            if not vectors:
                log_info(f"No documents found with content_id: {content_id}")
                return

            # Update each document
            updated_count = 0
            for vector_data in vectors:
                try:
                    # Get existing metadata
                    existing_metadata = vector_data.get("metadata", {}).copy()

                    # Merge new metadata with existing
                    existing_metadata.update(metadata)

                    # Prepare updated vector data
                    updated_vector = {
                        "key": vector_data["key"],
                        "data": vector_data.get("data", {"float32": [0.0] * self.dimension}),
                        "metadata": existing_metadata,
                    }

                    # Update the vector
                    self.client.put_vectors(
                        vectorBucketName=self.bucket_name, indexName=self.index_name, vectors=[updated_vector]
                    )
                    updated_count += 1
                    log_debug(f"Updated metadata for document: {vector_data['key']}")

                except Exception as e:
                    logger.error(f"Error updating metadata for document {vector_data.get('key')}: {e}")
                    continue

            log_info(f"Successfully updated metadata for {updated_count} documents with content_id: {content_id}")

        except Exception as e:
            logger.error(f"Error updating metadata for content_id {content_id}: {e}")
            raise

    def delete(self) -> bool:
        """
        Delete all vectors from the index.

        Returns:
            bool: True if deletion was successful, False otherwise

        Warning:
            This operation deletes all vectors but preserves the index structure.
        """
        return self._execute_with_timing("delete_all", self._delete_all_impl, return_result=True)

    def _delete_all_impl(self) -> bool:
        """
        Implementation for deleting all vectors from the index.

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        log_info(f"Deleting all vectors from index: {self.bucket_name}/{self.index_name}")

        try:
            if not self.exists():
                logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
                return False

            deleted_count = 0
            next_token = None

            while True:
                # List vectors to get their keys
                params = {
                    "vectorBucketName": self.bucket_name,
                    "indexName": self.index_name,
                    "maxResults": 500,
                    "returnData": False,
                    "returnMetadata": False,
                }

                if next_token:
                    params["nextToken"] = next_token

                response = self.client.list_vectors(**params)
                vectors = response.get("vectors", [])

                if vectors:
                    # Delete this batch of vectors
                    keys_to_delete = [vector["key"] for vector in vectors]
                    self.client.delete_vectors(
                        vectorBucketName=self.bucket_name, indexName=self.index_name, keys=keys_to_delete
                    )
                    deleted_count += len(keys_to_delete)
                    log_debug(f"Deleted batch of {len(keys_to_delete)} vectors")

                next_token = response.get("nextToken")
                if not next_token:
                    break

            log_info(f"Successfully deleted {deleted_count} vectors from index: {self.bucket_name}/{self.index_name}")
            return True

        except Exception as e:
            logger.error(f"Error deleting vectors from index {self.bucket_name}/{self.index_name}: {e}")
            return False

    def delete_documents(self, document_ids: List[str]) -> None:
        """
        Delete specific documents from the index by their IDs.

        Args:
            document_ids: List of document IDs to delete

        Raises:
            Exception: If delete operation fails

        Note:
            Logs individual errors but continues processing remaining documents.
        """
        self._execute_with_timing("delete_documents", lambda: self._delete_documents_impl(document_ids))

    def delete_by_id(self, id: str) -> bool:
        """
        Delete a document by its ID.

        Args:
            id: Document ID to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            if not self.exists():
                logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
                return False

            self.client.delete_vectors(vectorBucketName=self.bucket_name, indexName=self.index_name, keys=[id])
            log_info(f"Successfully deleted document: {id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document {id}: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """
        Delete documents by name.

        Args:
            name: Document name to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            if not self.exists():
                logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
                return False

            # First find documents with this name
            import random

            dummy_vector = [random.uniform(0.0001, 0.001) for _ in range(self.dimension)]

            response = self.client.query_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                topK=30,
                queryVector={"float32": dummy_vector},
                filter={"name": name},
                returnMetadata=False,
            )

            vectors = response.get("vectors", [])
            if not vectors:
                log_info(f"No documents found with name: {name}")
                return False

            # Delete the found documents
            document_ids = [vector["key"] for vector in vectors]
            self.client.delete_vectors(vectorBucketName=self.bucket_name, indexName=self.index_name, keys=document_ids)
            log_info(f"Successfully deleted {len(document_ids)} documents with name: {name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by name {name}: {e}")
            return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Delete documents by metadata filter.

        Args:
            metadata: Metadata filter to match documents for deletion

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            if not self.exists():
                logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
                return False

            # First find documents matching the metadata filter
            import random

            dummy_vector = [random.uniform(0.0001, 0.001) for _ in range(self.dimension)]

            response = self.client.query_vectors(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                topK=30,
                queryVector={"float32": dummy_vector},
                filter=metadata,
                returnMetadata=False,
            )

            vectors = response.get("vectors", [])
            if not vectors:
                log_info(f"No documents found matching metadata: {metadata}")
                return False

            # Delete the found documents
            document_ids = [vector["key"] for vector in vectors]
            self.client.delete_vectors(vectorBucketName=self.bucket_name, indexName=self.index_name, keys=document_ids)
            log_info(f"Successfully deleted {len(document_ids)} documents matching metadata: {metadata}")
            return True
        except Exception as e:
            logger.error(f"Error deleting documents by metadata {metadata}: {e}")
            return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """
        Delete documents by content ID.

        Args:
            content_id: Content ID to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        return self.delete_by_metadata({"content_id": content_id})

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        """
        Delete documents by content hash.

        Args:
            content_hash: Content hash to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        return self.delete_by_metadata({"content_hash": content_hash})

    def _delete_documents_impl(self, document_ids: List[str]) -> None:
        """
        Implementation for deleting specific documents by ID.

        Args:
            document_ids: List of document IDs to delete

        Raises:
            Exception: If delete operation fails
        """
        log_info(f"Deleting {len(document_ids)} documents from index {self.bucket_name}/{self.index_name}")

        if not self.exists():
            logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
            return

        if not document_ids:
            logger.warning("No document IDs provided for deletion")
            return

        try:
            # S3Vectors delete_vectors can handle batch deletion
            batch_size = 100

            for i in range(0, len(document_ids), batch_size):
                batch_ids = document_ids[i : i + batch_size]

                try:
                    self.client.delete_vectors(
                        vectorBucketName=self.bucket_name, indexName=self.index_name, keys=batch_ids
                    )
                    log_debug(f"Successfully deleted batch of {len(batch_ids)} documents")
                except Exception as e:
                    logger.error(f"Error deleting batch starting at index {i}: {e}")
                    # Continue with next batch

            log_info(f"Completed deletion process for {len(document_ids)} documents")

        except Exception as e:
            logger.error(f"Error executing document deletion: {e}")
            raise

    def _execute_bulk_operation(self, operation: str, documents: List[Document]) -> None:
        """
        Execute bulk operation with comprehensive error handling.

        Args:
            operation: Name of the operation (for logging)
            documents: List of documents to process

        Note:
            Creates bucket and index if they don't exist and handles errors gracefully.
        """
        start_time = time.time()
        log_info(
            f"Starting bulk {operation} of {len(documents)} documents to index {self.bucket_name}/{self.index_name}"
        )

        if not documents:
            logger.warning(f"No documents provided for {operation}")
            return

        if not self.exists():
            log_info(f"Bucket {self.bucket_name} or index {self.index_name} does not exist, creating them")
            self.create()

        try:
            vectors_data, prepared_count = self._prepare_bulk_data(documents)
            if vectors_data:
                self._execute_bulk_request(vectors_data, operation, prepared_count)
        except Exception as e:
            logger.error(f"Error executing bulk {operation} operation: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"Bulk {operation} operation took {end_time - start_time:.2f} seconds")

    async def _async_execute_bulk_operation(self, operation: str, documents: List[Document]) -> None:
        """
        Execute bulk operation asynchronously with comprehensive error handling.

        Args:
            operation: Name of the operation (for logging)
            documents: List of documents to process

        Note:
            Creates bucket and index if they don't exist and handles errors gracefully.
        """
        await asyncio.to_thread(self._execute_bulk_operation, operation, documents)

    def _prepare_bulk_data(self, documents: List[Document]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Prepare bulk data for S3Vectors.

        Args:
            documents: List of documents to prepare

        Returns:
            Tuple[List[Dict[str, Any]], int]: Vector data and count of prepared documents

        Note:
            Skips documents that fail preparation and logs errors.
        """
        vectors_data = []
        prepared_count = 0

        for doc in documents:
            try:
                vector_data = self._prepare_document_for_indexing(doc)
                vectors_data.append(vector_data)
                prepared_count += 1
            except Exception as e:
                logger.error(f"Error preparing document {doc.id} for indexing: {e}")
                continue

        log_debug(f"Prepared {prepared_count}/{len(documents)} documents for bulk operation")
        return vectors_data, prepared_count

    def _execute_bulk_request(self, vectors_data: List[Dict[str, Any]], operation: str, prepared_count: int) -> None:
        """
        Execute bulk request and handle response.

        Args:
            vectors_data: Prepared vector data for S3Vectors
            operation: Operation name for logging
            prepared_count: Number of documents prepared

        Note:
            S3Vectors put_vectors handles both insert and upsert operations.
        """
        log_debug(f"Executing bulk {operation} operation with {len(vectors_data)} vectors")

        try:
            # S3Vectors put_vectors can handle batch operations
            batch_size = 100

            for i in range(0, len(vectors_data), batch_size):
                batch_vectors = vectors_data[i : i + batch_size]

                self.client.put_vectors(
                    vectorBucketName=self.bucket_name, indexName=self.index_name, vectors=batch_vectors
                )
                log_debug(f"Successfully processed batch of {len(batch_vectors)} vectors")

            log_info(
                f"Successfully {operation}ed {prepared_count} documents in index {self.bucket_name}/{self.index_name}"
            )

        except Exception as e:
            logger.error(f"Error executing bulk {operation} request: {e}")
            raise

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Search for documents using vector similarity.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of matching documents

        Note:
            S3Vectors only supports vector search, so this method performs vector similarity search.
        """
        return self.vector_search(query, limit, filters)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Search for documents asynchronously using vector similarity.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of matching documents

        Note:
            Runs the synchronous search in a thread to avoid blocking the event loop.
        """
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform vector similarity search using embeddings.

        Args:
            query: Search query string (will be embedded)
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of documents ordered by similarity score

        Note:
            Generates query embedding and performs vector similarity search.
        """
        return self._execute_search_with_timing("vector", query, limit, filters)

    def keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform keyword-based text search.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: Empty list (not supported by S3Vectors)

        Note:
            S3Vectors does not support keyword search, returns empty list.
        """
        logger.warning("S3Vectors does not support keyword search. Use vector_search instead.")
        return []

    def hybrid_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Perform hybrid search combining vector and keyword search.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            filters: Optional filters to apply to search

        Returns:
            List[Document]: List of documents (same as vector search for S3Vectors)

        Note:
            S3Vectors only supports vector search, so this falls back to vector search.
        """
        logger.warning("S3Vectors does not support hybrid search. Falling back to vector search.")
        return self.vector_search(query, limit, filters)

    def _execute_search_with_timing(
        self, search_type: str, query: str, limit: int, filters: Optional[Dict[str, Any]]
    ) -> List[Document]:
        """
        Execute search with timing and comprehensive error handling.

        Args:
            search_type: Type of search for logging
            query: Search query string
            limit: Maximum number of results
            filters: Optional filters to apply

        Returns:
            List[Document]: Search results with optional reranking applied

        Note:
            Applies reranking if configured and handles all search errors gracefully.
        """
        start_time = time.time()
        log_info(f"Performing {search_type} search for: '{query}' (limit: {limit})")

        if not self.exists():
            logger.warning(f"Bucket {self.bucket_name} or index {self.index_name} does not exist")
            return []

        try:
            # Generate query embedding
            query_embedding, usage = self._get_query_embedding(query)

            # Build query parameters
            query_params = {
                "vectorBucketName": self.bucket_name,
                "indexName": self.index_name,
                "topK": limit,
                "queryVector": {"float32": query_embedding},
                "returnMetadata": True,
                "returnDistance": True,
            }

            # Add filters if provided
            if filters:
                query_params["filter"] = filters

            log_debug(f"Executing {search_type} search query")
            response = self.client.query_vectors(**query_params)

            documents = []
            for vector_data in response.get("vectors", []):
                # Extract distance/score
                distance = vector_data.get("distance", 0.0)
                # Convert distance to similarity score (higher is better)
                score = 1.0 / (1.0 + distance) if distance > 0 else 1.0

                doc = self._create_document_from_vector(vector_data, score)
                documents.append(doc)

            log_debug(f"Retrieved {len(documents)} documents from {search_type} search")

            # Apply reranking if configured
            if self.reranker is not None and documents:
                documents = self._apply_reranking(query, documents)

            log_info(f"{search_type.capitalize()} search returned {len(documents)} documents for query: '{query}'")
            return documents

        except Exception as e:
            logger.error(f"Error during {search_type} search: {e}")
            return []
        finally:
            end_time = time.time()
            log_debug(f"Total {search_type} search operation took {end_time - start_time:.2f} seconds")

    def _get_query_embedding(self, query: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """
        Generate embedding for search query.

        Args:
            query: Search query string

        Returns:
            Tuple[List[float], Optional[Dict[str, Any]]]: Query embedding and usage statistics

        Raises:
            ValueError: If no embedder is configured

        Note:
            Uses the configured embedder to generate query embedding.
        """
        if self.embedder is None:
            raise ValueError("No embedder configured for search")

        log_debug("Generating query embedding")
        query_embedding, usage = self.embedder.get_embedding_and_usage(query)
        log_debug(f"Generated query embedding (dimension: {len(query_embedding)})")

        if usage:
            log_debug(f"Embedding generation usage: {usage}")

        return query_embedding, usage

    def _apply_reranking(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Apply reranking to search results if reranker is configured.

        Args:
            query: Original search query
            documents: List of documents to rerank

        Returns:
            List[Document]: Reranked list of documents

        Note:
            Uses the configured reranker to improve search result ordering.
        """
        log_debug(f"Applying reranking with {type(self.reranker).__name__}")
        rerank_start = time.time()
        if self.reranker is not None:
            reranked_docs = self.reranker.rerank(query, documents)
        else:
            reranked_docs = documents
        rerank_end = time.time()
        log_debug(f"Reranking took {rerank_end - rerank_start:.2f} seconds")
        return reranked_docs

    def _execute_with_timing(self, operation: str, func, return_result: bool = False):
        """
        Execute function with timing and error handling.

        Args:
            operation: Operation name for logging
            func: Function to execute
            return_result: Whether to return function result

        Returns:
            Any: Function result if return_result is True, otherwise None

        Note:
            Provides comprehensive timing and error logging for all operations.
        """
        start_time = time.time()
        try:
            result = func()
            if return_result:
                return result
        except Exception as e:
            logger.error(f"Error during {operation}: {e}")
            if return_result:
                return False
            raise
        finally:
            end_time = time.time()
            log_debug(f"{operation} operation took {end_time - start_time:.2f} seconds")

    def __deepcopy__(self, memo):
        """
        Deep copy method for S3VectorsDb instances.

        Args:
            memo: Memoization dictionary

        Returns:
            S3VectorsDb: Deep copy of the instance
        """
        import copy

        # Create a new instance with the same parameters
        new_instance = S3VectorsDb(
            bucket_name=self.bucket_name,
            index_name=self.index_name,
            dimension=self.dimension,
            embedder=copy.deepcopy(self.embedder, memo),
            distance_metric=self.distance_metric,
            data_type=self.data_type,
            search_type=self.search_type,
            reranker=copy.deepcopy(self.reranker, memo) if self.reranker else None,
            non_filterable_metadata_keys=copy.deepcopy(self.non_filterable_metadata_keys, memo),
            **copy.deepcopy(self.aws_config, memo),
        )
        return new_instance

    async def _async_execute_with_timing(self, operation: str, func):
        """
        Execute async function with timing and error handling.

        Args:
            operation: Operation name for logging
            func: Async function to execute

        Note:
            Provides comprehensive timing and error logging for async operations.
        """
        start_time = time.time()
        try:
            await func()
        except Exception as e:
            logger.error(f"Error during {operation}: {e}")
            raise
        finally:
            end_time = time.time()
            log_debug(f"{operation} operation took {end_time - start_time:.2f} seconds")
