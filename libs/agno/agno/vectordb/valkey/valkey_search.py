import json
import asyncio
from hashlib import md5
from typing import Any, Dict, List, Optional, Union, cast

import valkey
import valkey.asyncio as aio_valkey

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class ValkeySearch(VectorDb):
    """Vector DB implementation powered by Valkey Search (Redis Search) - https://valkey.io/topics/search/"""

    def __init__(
        self,
        collection: str,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        host: str = "localhost",
        port: int = 6379,
        password: Optional[str] = None,
        db: int = 0,
        decode_responses: bool = True,
        reranker: Optional[Reranker] = None,
        **kwargs,
    ):
        """
        Args:
            collection (str): Name of the Valkey Search index.
            embedder (Optional[Embedder]): Optional embedder for automatic vector generation.
            distance (Distance): Distance metric to use (default: cosine).
            host (str): Valkey/Redis host (default: localhost).
            port (int): Valkey/Redis port (default: 6379).
            password (Optional[str]): Password for authentication.
            db (int): Database number (default: 0).
            decode_responses (bool): Whether to decode responses (default: True).
            reranker (Optional[Reranker]): Optional reranker for result refinement.
            **kwargs: Additional arguments for Redis client.
        """
        # Collection attributes
        self.collection: str = collection

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")

        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        # Distance metric
        self.distance: Distance = distance

        # Valkey client instances
        self._client: Optional[valkey.Valkey] = None
        self._async_client: Optional[aio_valkey.Valkey] = None
        self._async_binary_client: Optional[aio_valkey.Valkey] = None
        
        # Flag to track if async operations are failing
        self._prefer_sync: bool = False

        # Connection parameters
        self.host: str = host
        self.port: int = port
        self.password: Optional[str] = password
        self.db: int = db
        self.decode_responses: bool = decode_responses
        self.kwargs: Dict[str, Any] = kwargs

        # Reranker
        self.reranker: Optional[Reranker] = reranker

        # Index configuration
        self.prefix: str = f"doc:{collection}:"
        self.vector_field: str = "vector"
        self.content_field: str = "content"
        self.metadata_field: str = "metadata"
        self.id_field: str = "id"
        self.content_hash_field: str = "content_hash"

    @property
    def client(self) -> valkey.Valkey:
        """Get or create the Valkey client."""
        if self._client is None:
            self._client = valkey.Valkey(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.db,
                decode_responses=self.decode_responses,
                **self.kwargs,
            )
        return self._client

    @property
    def binary_client(self) -> valkey.Valkey:
        """Get or create a Valkey client for binary operations (no response decoding)."""
        return valkey.Valkey(
            host=self.host,
            port=self.port,
            password=self.password,
            db=self.db,
            decode_responses=False,
            **self.kwargs,
        )

    @property
    def async_binary_client(self) -> aio_valkey.Valkey:
        """Get or create an async Valkey client for binary operations (no response decoding)."""
        return aio_valkey.Valkey(
            host=self.host,
            port=self.port,
            password=self.password,
            db=self.db,
            decode_responses=False,
            **self.kwargs,
        )

    @property
    def async_binary_client(self) -> aio_valkey.Valkey:
        """Get or create an async Valkey client for binary operations (no response decoding)."""
        if self._async_binary_client is None:
            self._async_binary_client = aio_valkey.Valkey(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.db,
                decode_responses=False,
                **self.kwargs,
            )
        return self._async_binary_client

    @property
    def async_client(self) -> aio_valkey.Valkey:
        """Get or create the async Valkey client."""
        if self._async_client is None:
            self._async_client = aio_valkey.Valkey(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.db,
                decode_responses=self.decode_responses,
                **self.kwargs,
            )
        return self._async_client

    def _get_distance_metric(self) -> str:
        """Convert Distance enum to Valkey Search distance metric."""
        distance_mapping = {
            Distance.cosine: "COSINE",
            Distance.l2: "L2",
            Distance.max_inner_product: "IP",
        }
        return distance_mapping.get(self.distance, "COSINE")

    def _vector_to_bytes(self, vector: List[float]) -> bytes:
        """Convert vector to binary data for Valkey Search."""
        import struct
        return struct.pack(f"{len(vector)}f", *vector)

    def _bytes_to_vector(self, data: bytes) -> List[float]:
        """Convert bytes back to vector."""
        import struct
        return list(struct.unpack(f"{len(data)//4}f", data))

    def create(self) -> None:
        """Create the Valkey Search index."""
        try:
            # Check if index already exists
            if self.exists():
                log_info(f"Index '{self.collection}' already exists.")
                return

            # Create index with vector field
            distance_metric = self._get_distance_metric()
            
            # Create the index with vector field and searchable fields
            result = self.client.execute_command(
                "FT.CREATE",
                self.collection,
                "ON", "HASH",
                "PREFIX", "1", self.prefix,
                "SCHEMA",
                self.vector_field, "VECTOR", "HNSW", "6", "TYPE", "FLOAT32", "DIM", str(self.dimensions), "DISTANCE_METRIC", distance_metric,
                self.content_hash_field, "TAG",  # Index content_hash for existence checks
                self.id_field, "TAG"             # Index id field for lookups
            )
            
            log_info(f"Created Valkey Search index '{self.collection}' with result: {result}")
            
        except Exception as e:
            log_error(f"Error creating Valkey Search index: {e}")
            raise

    async def async_create(self) -> None:
        """Create the Valkey Search index asynchronously."""
        try:
            # Check if index already exists
            if await self.async_exists():
                log_info(f"Index '{self.collection}' already exists.")
                return

            # Create index with vector field
            distance_metric = self._get_distance_metric()
            
            # Create the index with vector field and searchable fields
            result = await self.async_client.execute_command(
                "FT.CREATE",
                self.collection,
                "ON", "HASH",
                "PREFIX", "1", self.prefix,
                "SCHEMA",
                self.vector_field, "VECTOR", "HNSW", "6", "TYPE", "FLOAT32", "DIM", str(self.dimensions), "DISTANCE_METRIC", distance_metric,
                self.content_hash_field, "TAG",  # Index content_hash for existence checks
                self.id_field, "TAG"             # Index id field for lookups
            )
            
            log_info(f"Created Valkey Search index '{self.collection}' with result: {result}")
            
        except Exception as e:
            log_error(f"Error creating Valkey Search index: {e}")
            raise

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists."""
        try:
            # Search for documents with the given name
            # Use proper Redis Search query syntax for tag fields
            result = self.client.execute_command(
                "FT.SEARCH",
                self.collection,
                f"@{self.id_field}:{{{name}}}",
                "LIMIT", "0", "1"
            )
            return len(result) > 1  # Result includes header, so > 1 means documents found
        except Exception as e:
            log_error(f"Error checking if name exists: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists asynchronously."""
        try:
            # Search for documents with the given name
            # Use proper Redis Search query syntax for tag fields
            result = await self.async_client.execute_command(
                "FT.SEARCH",
                self.collection,
                f"@{self.id_field}:{{{name}}}",
                "LIMIT", "0", "1"
            )
            return len(result) > 1  # Result includes header, so > 1 means documents found
        except Exception as e:
            log_error(f"Error checking if name exists: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists."""
        return self.name_exists(id)

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if a document with the given content hash exists."""
        try:
            # Try to get the document directly using Redis key lookup
            # This is more efficient than using FT.SEARCH
            keys = self.client.keys(f"{self.prefix}*")
            for key in keys:
                try:
                    stored_hash = self.client.hget(key, self.content_hash_field)
                    if stored_hash == content_hash:
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            log_error(f"Error checking if content hash exists: {e}")
            return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the Valkey Search index."""
        try:
            for doc in documents:
                # Generate document ID
                doc_id = f"{self.prefix}{doc.id}"
                
                # Embed the document content
                vector = self.embedder.get_embedding(doc.content)
                vector_bytes = self._vector_to_bytes(vector)
                
                # Prepare document data (simplified for vector-only schema)
                doc_data = {
                    self.vector_field: vector_bytes,
                    # Store other data as regular hash fields (not indexed)
                    "content": doc.content,
                    "metadata": json.dumps(doc.meta_data) if doc.meta_data else "{}",
                    "id": doc.id,
                    "content_hash": content_hash,
                }
                
                # Store document in Redis using binary client for the vector field
                # First store non-vector fields with regular client
                regular_data = {k: v for k, v in doc_data.items() if k != self.vector_field}
                if regular_data:
                    self.client.hset(doc_id, mapping=regular_data)
                
                # Then store vector field with binary client
                self.binary_client.hset(doc_id, self.vector_field, vector_bytes)
                
            log_info(f"Inserted {len(documents)} documents into Valkey Search index '{self.collection}'")
            
        except Exception as e:
            log_error(f"Error inserting documents: {e}")
            raise

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insert documents into the Valkey Search index asynchronously."""
        
        # If we've detected async issues, use sync operations directly
        if self._prefer_sync:
            log_debug("Using sync operation due to previous async issues")
            self.insert(content_hash, documents, filters)
            return
            
        try:
            for doc in documents:
                try:
                    # Generate document ID
                    doc_id = f"{self.prefix}{doc.id}"
                    
                    # Embed the document content
                    vector = await self.embedder.async_get_embedding(doc.content)
                    vector_bytes = self._vector_to_bytes(vector)
                    
                    # Prepare document data (simplified for vector-only schema)
                    doc_data = {
                        self.vector_field: vector_bytes,
                        # Store other data as regular hash fields (not indexed)
                        "content": doc.content,
                        "metadata": json.dumps(doc.meta_data) if doc.meta_data else "{}",
                        "id": doc.id,
                        "content_hash": content_hash,
                    }
                    
                    # Store document in Redis using async binary client for the vector field
                    # First store non-vector fields with regular client
                    regular_data = {k: v for k, v in doc_data.items() if k != self.vector_field}
                    if regular_data:
                        await self.async_client.hset(doc_id, mapping=regular_data)
                    
                    # Then store vector field with async binary client
                    await self.async_binary_client.hset(doc_id, self.vector_field, vector_bytes)
                    
                except (RuntimeError, Exception) as e:
                    if "Event loop is closed" in str(e) or "asyncio" in str(e).lower():
                        log_debug(f"Async operation failed for document {doc.id}, switching to sync mode: {e}")
                        # Set flag to prefer sync operations for future calls
                        self._prefer_sync = True
                        # Fall back to sync operation for this document
                        try:
                            self.insert(content_hash, [doc], filters)
                        except Exception as sync_e:
                            log_error(f"Sync fallback also failed for document {doc.id}: {sync_e}")
                            raise
                    else:
                        raise
                except Exception as e:
                    log_error(f"Error inserting document {doc.id}: {e}")
                    raise
                
            log_info(f"Inserted {len(documents)} documents into Valkey Search index '{self.collection}'")
            
        except Exception as e:
            log_error(f"Error inserting documents: {e}")
            raise

    def upsert_available(self) -> bool:
        """Check if upsert is available."""
        return True

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the Valkey Search index."""
        # For Valkey Search, upsert is the same as insert since we use HSET
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Upsert documents into the Valkey Search index asynchronously."""
        # For Valkey Search, upsert is the same as insert since we use HSET
        await self.async_insert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for similar documents."""
        try:
            # Embed the query
            query_vector = self.embedder.get_embedding(query)
            query_vector_bytes = self._vector_to_bytes(query_vector)
            
            # Build search query
            search_query = f"*=>[KNN {limit} @{self.vector_field} $query_vector]"
            
            # Add filters if provided
            if filters:
                filter_parts = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        # For TAG fields, wrap string values in curly braces
                        filter_parts.append(f"@{key}:{{{value}}}")
                    elif isinstance(value, (int, float)):
                        filter_parts.append(f"@{key}:[{value} {value}]")
                    elif isinstance(value, list):
                        if value:
                            filter_parts.append(f"@{key}:{{{','.join(map(str, value))}}}")
                if filter_parts:
                    search_query = f"({search_query}) {' '.join(filter_parts)}"
            
            # Execute search using binary client for vector operations
            result = self.binary_client.execute_command(
                "FT.SEARCH",
                self.collection,
                search_query,
                "PARAMS", "2", "query_vector", query_vector_bytes,
                "LIMIT", "0", str(limit)
            )
            
            # Parse results (handle binary response with scores)
            documents = []
            if len(result) > 1:  # Result includes header
                # Format is: [count, doc_key1, fields1, doc_key2, fields2, ...]
                # Skip the count (result[0]), process document pairs (key, fields)
                for i in range(1, len(result), 2):
                    if i + 1 >= len(result):
                        break
                        
                    doc_key = result[i]      # Document key (bytes)
                    field_values = result[i + 1]  # List of alternating field-value pairs
                    
                    # Parse field-value pairs into a dictionary
                    doc_fields = {}
                    score = 0.0  # Default score
                    
                    if isinstance(field_values, list):
                        for j in range(0, len(field_values), 2):
                            if j + 1 < len(field_values):
                                field_name = field_values[j]
                                field_value = field_values[j + 1]
                                
                                # Decode field name (always text)
                                if isinstance(field_name, bytes):
                                    field_name = field_name.decode('utf-8')
                                
                                # Handle the vector score specially
                                if field_name == "__vector_score":
                                    try:
                                        if isinstance(field_value, bytes):
                                            score = float(field_value.decode('utf-8'))
                                        else:
                                            score = float(field_value)
                                    except (ValueError, TypeError):
                                        score = 0.0
                                    continue  # Don't add this to regular fields
                                
                                # Only decode field value if it's not the vector field (binary data)
                                if isinstance(field_value, bytes) and field_name != self.vector_field:
                                    try:
                                        field_value = field_value.decode('utf-8')
                                    except UnicodeDecodeError:
                                        # Keep as bytes if it can't be decoded
                                        pass
                                
                                doc_fields[field_name] = field_value
                    
                    # Extract document data
                    content = doc_fields.get("content", "")
                    metadata_str = doc_fields.get("metadata", "{}")
                    doc_id = doc_fields.get("id", "")
                    
                    try:
                        metadata = json.loads(metadata_str) if metadata_str else {}
                    except json.JSONDecodeError:
                        metadata = {}
                    
                    # Create document
                    doc = Document(
                        id=doc_id,
                        content=content,
                        meta_data=metadata,
                    )
                    # Set the search score (using reranking_score field)
                    doc.reranking_score = score
                    documents.append(doc)
            
            # Apply reranker if available
            if self.reranker and documents:
                documents = self.reranker.rerank(query, documents)
            
            return documents
            
        except Exception as e:
            log_error(f"Error searching documents: {e}")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search for similar documents asynchronously."""
        try:
            # Embed the query
            query_vector = await self.embedder.async_get_embedding(query)
            query_vector_bytes = self._vector_to_bytes(query_vector)
            
            # Build search query
            search_query = f"*=>[KNN {limit} @{self.vector_field} $query_vector]"
            
            # Add filters if provided
            if filters:
                filter_parts = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        # For TAG fields, wrap string values in curly braces
                        filter_parts.append(f"@{key}:{{{value}}}")
                    elif isinstance(value, (int, float)):
                        filter_parts.append(f"@{key}:[{value} {value}]")
                    elif isinstance(value, list):
                        if value:
                            filter_parts.append(f"@{key}:{{{','.join(map(str, value))}}}")
                if filter_parts:
                    search_query = f"({search_query}) {' '.join(filter_parts)}"
            
            # Execute search using async binary client for vector operations
            result = await self.async_binary_client.execute_command(
                "FT.SEARCH",
                self.collection,
                search_query,
                "PARAMS", "2", "query_vector", query_vector_bytes,
                "LIMIT", "0", str(limit)
            )
            
            # Parse results (handle binary response with scores)
            documents = []
            if len(result) > 1:  # Result includes header
                # Format is: [count, doc_key1, fields1, doc_key2, fields2, ...]
                # Skip the count (result[0]), process document pairs (key, fields)
                for i in range(1, len(result), 2):
                    if i + 1 >= len(result):
                        break
                        
                    doc_key = result[i]      # Document key (bytes)
                    field_values = result[i + 1]  # List of alternating field-value pairs
                    
                    # Parse field-value pairs into a dictionary
                    doc_fields = {}
                    score = 0.0  # Default score
                    
                    if isinstance(field_values, list):
                        for j in range(0, len(field_values), 2):
                            if j + 1 < len(field_values):
                                field_name = field_values[j]
                                field_value = field_values[j + 1]
                                
                                # Decode field name (always text)
                                if isinstance(field_name, bytes):
                                    field_name = field_name.decode('utf-8')
                                
                                # Handle the vector score specially
                                if field_name == "__vector_score":
                                    try:
                                        if isinstance(field_value, bytes):
                                            score = float(field_value.decode('utf-8'))
                                        else:
                                            score = float(field_value)
                                    except (ValueError, TypeError):
                                        score = 0.0
                                    continue  # Don't add this to regular fields
                                
                                # Only decode field value if it's not the vector field (binary data)
                                if isinstance(field_value, bytes) and field_name != self.vector_field:
                                    try:
                                        field_value = field_value.decode('utf-8')
                                    except UnicodeDecodeError:
                                        # Keep as bytes if it can't be decoded
                                        pass
                                
                                doc_fields[field_name] = field_value
                    
                    # Extract document data
                    content = doc_fields.get("content", "")
                    metadata_str = doc_fields.get("metadata", "{}")
                    doc_id = doc_fields.get("id", "")
                    
                    try:
                        metadata = json.loads(metadata_str) if metadata_str else {}
                    except json.JSONDecodeError:
                        metadata = {}
                    
                    # Create document
                    doc = Document(
                        id=doc_id,
                        content=content,
                        meta_data=metadata,
                    )
                    # Set the search score (using reranking_score field)
                    doc.reranking_score = score
                    documents.append(doc)
            
            # Apply reranker if available
            if self.reranker and documents:
                documents = await self.reranker.arerank(query, documents)
            
            return documents
            
        except Exception as e:
            log_error(f"Error searching documents: {e}")
            return []

    def drop(self) -> None:
        """Drop the Valkey Search index."""
        try:
            result = self.client.execute_command("FT.DROPINDEX", self.collection)
            log_info(f"Dropped Valkey Search index '{self.collection}' with result: {result}")
        except Exception as e:
            log_error(f"Error dropping index: {e}")
            raise

    async def async_drop(self) -> None:
        """Drop the Valkey Search index asynchronously."""
        try:
            result = await self.async_client.execute_command("FT.DROPINDEX", self.collection)
            log_info(f"Dropped Valkey Search index '{self.collection}' with result: {result}")
        except Exception as e:
            log_error(f"Error dropping index: {e}")
            raise

    def exists(self) -> bool:
        """Check if the index exists."""
        try:
            result = self.client.execute_command("FT.INFO", self.collection)
            return True
        except Exception:
            return False

    async def async_exists(self) -> bool:
        """Check if the index exists asynchronously."""
        try:
            result = await self.async_client.execute_command("FT.INFO", self.collection)
            return True
        except Exception:
            return False

    def delete(self) -> bool:
        """Delete all documents in the index."""
        try:
            # Get all keys with the prefix
            keys = self.client.keys(f"{self.prefix}*")
            if keys:
                self.client.delete(*keys)
            return True
        except Exception as e:
            log_error(f"Error deleting documents: {e}")
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete a document by ID."""
        try:
            doc_id = f"{self.prefix}{id}"
            result = self.client.delete(doc_id)
            return result > 0
        except Exception as e:
            log_error(f"Error deleting document by ID: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Delete a document by name."""
        return self.delete_by_id(name)

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata."""
        try:
            # Build search query for metadata
            filter_parts = []
            for key, value in metadata.items():
                if isinstance(value, str):
                    # For TAG fields, wrap string values in curly braces
                    filter_parts.append(f"@{key}:{{{value}}}")
                elif isinstance(value, (int, float)):
                    filter_parts.append(f"@{key}:[{value} {value}]")
                elif isinstance(value, list):
                    if value:
                        filter_parts.append(f"@{key}:{{{','.join(map(str, value))}}}")
            
            if not filter_parts:
                return False
            
            search_query = " ".join(filter_parts)
            
            # Search for documents to delete
            result = self.client.execute_command(
                "FT.SEARCH",
                self.collection,
                search_query,
                "LIMIT", "0", "1000"  # Get up to 1000 documents
            )
            
            # Delete found documents
            deleted_count = 0
            if len(result) > 1:  # Result includes header
                for i in range(1, len(result), 2):
                    doc_data = result[i]
                    doc_id = doc_data.get(self.id_field, "")
                    if doc_id:
                        redis_key = f"{self.prefix}{doc_id}"
                        if self.client.delete(redis_key):
                            deleted_count += 1
            
            return deleted_count > 0
            
        except Exception as e:
            log_error(f"Error deleting documents by metadata: {e}")
            return False

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """Update metadata for a document by content ID."""
        try:
            doc_id = f"{self.prefix}{content_id}"
            
            # Check if document exists
            if not self.client.exists(doc_id):
                log_debug(f"Document with ID '{content_id}' not found for metadata update - this is normal during initial content loading")
                return
            
            # Update metadata
            metadata_str = json.dumps(metadata)
            self.client.hset(doc_id, self.metadata_field, metadata_str)
            
            log_debug(f"Updated metadata for document '{content_id}'")
            
        except Exception as e:
            log_error(f"Error updating metadata: {e}")
            raise

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete a document by content ID."""
        try:
            doc_id = f"{self.prefix}{content_id}"
            result = self.client.delete(doc_id)
            return result > 0
        except Exception as e:
            log_error(f"Error deleting document by content ID: {e}")
            return False

    def get_count(self) -> int:
        """Get the number of documents in the collection."""
        try:
            # Get all keys with the collection prefix and count them
            keys = self.client.keys(f"{self.prefix}*")
            return len(keys)
        except Exception as e:
            log_error(f"Error getting document count: {e}")
            return 0

    def optimize(self) -> None:
        """Optimize the Valkey Search index."""
        try:
            # For Valkey Search, we can use FT.OPTIMIZE to optimize the index
            result = self.client.execute_command("FT.OPTIMIZE", self.collection)
            log_info(f"Optimized Valkey Search index '{self.collection}' with result: {result}")
        except Exception as e:
            log_warning(f"Optimization not supported or failed: {e}")
            # Optimization is optional, so we don't raise the exception
