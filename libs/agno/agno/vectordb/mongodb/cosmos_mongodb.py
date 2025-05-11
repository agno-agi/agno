# Add this to libs/agno/agno/vectordb/mongodb/cosmosdb.py

import time
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, errors
from pymongo.collection import Collection

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.mongodb.mongodb import MongoDb


class CosmosMongoDb(MongoDb):
    """
    Azure Cosmos DB for MongoDB implementation with fallback search mechanisms.
    This class handles compatibility issues between MongoDB Atlas and Azure Cosmos DB.
    """

    def __init__(
        self,
        collection_name: str,
        db_url: Optional[str] = None,
        database: str = "agno",
        embedder: Optional[Embedder] = None,
        overwrite: bool = False,
        wait_after_insert: Optional[float] = None,
        max_pool_size: int = 100,
        retry_writes: bool = False,  # Set to False for Cosmos DB
        client: Optional[MongoClient] = None,
        **kwargs,
    ):
        """Initialize the Cosmos DB wrapper with appropriate defaults."""
        super().__init__(
            collection_name=collection_name,
            db_url=db_url,
            database=database,
            embedder=embedder,
            overwrite=overwrite,
            wait_after_insert=wait_after_insert,
            max_pool_size=max_pool_size,
            retry_writes=retry_writes,  # Cosmos DB doesn't support retry_writes
            client=client,
            # Skip these features as they're not supported
            wait_until_index_ready=None,
            search_index_name=None,
            **kwargs,
        )
        self.is_cosmos_db = True
        log_info("Using Azure Cosmos DB for MongoDB compatibility mode")

    def _get_client(self) -> MongoClient:
        """
        Override to handle Cosmos DB specific connection issues.
        Follow Azure Cosmos DB connection patterns.
        """
        if self._client is None:
            try:
                log_debug("Creating MongoDB Client for Cosmos DB")
                # Cosmos DB specific settings
                cosmos_kwargs = {
                    "retryWrites": False,  # Cosmos DB doesn't support retryWrites
                    "ssl": True,
                    "tlsAllowInvalidCertificates": True,
                    "maxPoolSize": 100,
                    "maxIdleTimeMS": 30000,
                }

                self._client = MongoClient(self.connection_string, **cosmos_kwargs)

                # Test connection
                self._client.admin.command("ping")
                log_info("Connected to Azure Cosmos DB successfully.")

                # Get database using the get_database method as shown in the example
                self._db = self._client.get_database(self.database)
                log_info(f"Using database: {self.database}")

            except errors.ConnectionFailure as e:
                logger.error(f"Failed to connect to Azure Cosmos DB: {e}")
                raise ConnectionError(f"Failed to connect to Azure Cosmos DB: {e}")
            except Exception as e:
                logger.error(f"An error occurred while connecting to Azure Cosmos DB: {e}")
                raise
        return self._client

    def _get_collection(self) -> Collection:
        """Get the collection following Azure Cosmos DB patterns."""
        if self._collection is None:
            if self._client is None:
                self._get_client()

            # Use get_collection as shown in the example
            self._collection = self._db.get_collection(self.collection_name)
            log_info(f"Using collection: {self.collection_name}")
        return self._collection

    def _get_or_create_collection(self) -> Collection:
        """Get or create the MongoDB collection without vector search index creation."""
        self._collection = self._db[self.collection_name]  # type: ignore

        if not self.collection_exists():
            log_info(f"Creating collection '{self.collection_name}'.")
            self._db.create_collection(self.collection_name)  # type: ignore
            # Create regular text index for text searches
            self._create_regular_index()
        else:
            log_info(f"Using existing collection '{self.collection_name}'.")
            # Check if text index exists
            if not self._text_index_exists():
                self._create_regular_index()

        return self._collection  # type: ignore

    def _create_regular_index(self) -> None:
        """Create regular indexes for better search performance."""
        try:
            collection = self._get_collection()
            # Create a regular index on name field - text indexes are not supported in Cosmos DB
            log_info("Creating regular index on 'name' field")
            collection.create_index("name")
            log_info("Created index on 'name' field")
        except Exception as e:
            logger.error(f"Error creating regular indexes: {e}")

    def _text_index_exists(self) -> bool:
        """Check if a text index exists on the collection."""
        return False
        # try:
        #     collection = self._get_collection()
        #     indexes = collection.index_information()
        #     for index_info in indexes.values():
        #         for key, direction in index_info.get('key', []):
        #             if key == 'content' and direction == 'text':
        #                 return True
        #     return False
        # except Exception as e:
        #     logger.error(f"Error checking text index existence: {e}")
        #     return False

    def _create_search_index(self, overwrite: bool = True) -> None:
        """Override to skip vector index creation which isn't supported in Cosmos DB."""
        log_info("Vector search indexes not supported in Azure Cosmos DB - skipping creation")
        return

    def _search_index_exists(self) -> bool:
        """Override to avoid checking for vector search indexes."""
        return False

    def _wait_for_index_ready(self) -> None:
        """Override to skip waiting for index - not needed for Cosmos DB."""
        return

    def create(self) -> None:
        """Create the collection with appropriate indexes for Cosmos DB."""
        self._get_or_create_collection()
        self._create_regular_index()

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the MongoDB collection with Cosmos DB compatibility."""
        log_info(f"Inserting {len(documents)} documents")
        collection = self._get_collection()

        prepared_docs = []
        for document in documents:
            try:
                doc_data = self.prepare_doc(document, filters)
                prepared_docs.append(doc_data)
            except ValueError as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if prepared_docs:
            # Insert in smaller batches for Cosmos DB
            batch_size = 10  # Smaller batch size for Cosmos DB
            for i in range(0, len(prepared_docs), batch_size):
                batch = prepared_docs[i : i + batch_size]
                try:
                    # Use ordered=False to continue after errors
                    collection.insert_many(batch, ordered=False)
                    log_info(f"Inserted batch of {len(batch)} documents")
                    if self.wait_after_insert and self.wait_after_insert > 0:
                        time.sleep(self.wait_after_insert)
                except errors.BulkWriteError as e:
                    # Some documents may have failed but others succeeded
                    logger.warning(f"Bulk write error: {str(e)}")
                except Exception as e:
                    logger.error(f"Error inserting documents: {e}")

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents with Cosmos DB compatibility."""
        log_info(f"Upserting {len(documents)} documents")
        collection = self._get_collection()

        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                collection.update_one(
                    {"_id": doc_data["_id"]},
                    {"$set": doc_data},
                    upsert=True,
                )
                log_info(f"Upserted document: {doc_data['_id']}")
            except Exception as e:
                logger.error(f"Error upserting document '{document.name}': {e}")

    def search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None, min_score: float = 0.0
    ) -> List[Document]:
        """
        Simple keyword-based search implementation for Cosmos DB.
        """
        try:
            collection = self._get_collection()

            # Start with basic keyword regex search
            keyword_query = {"content": {"$regex": query, "$options": "i"}}

            # Add filters if provided
            if filters:
                for key, value in filters.items():
                    if not key.startswith("meta_data.") and "." not in key:
                        keyword_query[f"meta_data.{key}"] = value
                    else:
                        keyword_query[key] = value

            cursor = collection.find(keyword_query, {"_id": 1, "name": 1, "content": 1, "meta_data": 1}).limit(limit)

            docs = []
            for doc in cursor:
                docs.append(
                    Document(
                        id=str(doc["_id"]),
                        name=doc.get("name"),
                        content=doc["content"],
                        meta_data=doc.get("meta_data", {}),
                    )
                )

            # If no results, try individual keywords
            if not docs:
                log_info("No results with exact phrase, trying individual keywords")
                keywords = query.split()
                if keywords:
                    keyword_pattern = "|".join(keywords)
                    keyword_query["content"] = {"$regex": keyword_pattern, "$options": "i"}

                    cursor = collection.find(keyword_query, {"_id": 1, "name": 1, "content": 1, "meta_data": 1}).limit(
                        limit
                    )

                    for doc in cursor:
                        docs.append(
                            Document(
                                id=str(doc["_id"]),
                                name=doc.get("name"),
                                content=doc["content"],
                                meta_data=doc.get("meta_data", {}),
                            )
                        )

            log_info(f"Search completed. Found {len(docs)} documents.")
            return docs

        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Fallback to regular search for vector search."""
        log_info("Vector search not available in Cosmos DB - using text search")
        return self.search(query, limit=limit)

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a keyword-based search using Cosmos DB compatible methods."""
        return self.search(query, limit=limit)

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Fallback to regular search for hybrid search."""
        log_info("Hybrid search not available in Cosmos DB - using text search")
        return self.search(query, limit=limit)

    def prepare_doc(self, document: Document, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Prepare document for insertion with Cosmos DB compatibility.
        We still calculate embeddings for future compatibility.
        """
        # Calculate embeddings for future compatibility
        document.embed(embedder=self.embedder)
        if document.embedding is None:
            log_info(f"No embedding for document {document.id or document.name}, using empty list")
            document.embedding = []  # Empty list instead of None

        # Add filters to document metadata if provided
        if filters:
            meta_data = document.meta_data.copy() if document.meta_data else {}
            meta_data.update(filters)
            document.meta_data = meta_data

        from hashlib import md5

        # Create a clean content without null bytes
        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode("utf-8")).hexdigest()

        # Create document data
        doc_data = {
            "_id": doc_id,
            "name": document.name,
            "content": cleaned_content,
            "meta_data": document.meta_data or {},
            "embedding": document.embedding,  # Keep for compatibility
        }
        return doc_data
