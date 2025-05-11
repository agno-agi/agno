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
        max_pool_size: int = 100,
        client: Optional[MongoClient] = None,
        search_index_name: Optional[str] = "vector_index_1",
        **kwargs,
    ):
        """Initialize the Cosmos DB wrapper with appropriate defaults."""
        super().__init__(
            collection_name=collection_name,
            db_url=db_url,
            database=database,
            embedder=embedder,
            overwrite=overwrite,
            max_pool_size=max_pool_size,
            client=client,
            search_index_name=search_index_name,
            **kwargs,
        )
        self.is_cosmos_db = True
        log_info("Using Azure Cosmos DB for MongoDB compatibility mode")

    def _get_client(self) -> MongoClient:
        if self._client is None:
            try:
                log_debug("Creating MongoDB Client for Cosmos DB")
                # Cosmos DB specific settings
                cosmos_kwargs = {
                    "retryWrites": False,
                    "ssl": True,
                    "tlsAllowInvalidCertificates": True,
                    "maxPoolSize": 100,
                    "maxIdleTimeMS": 30000,
                }

                # Suppress UserWarning about CosmosDB
                import warnings

                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", category=UserWarning, message=".*connected to a CosmosDB cluster.*"
                    )
                    self._client = MongoClient(self.connection_string, **cosmos_kwargs)

                    self._client.admin.command("ping")

                log_info("Connected to Azure Cosmos DB successfully.")
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

            self._collection = self._db.get_collection(self.collection_name)
            log_info(f"Using collection: {self.collection_name}")
        return self._collection

    def _get_or_create_collection(self) -> Collection:
        """Get or create the MongoDB collection."""
        self._collection = self._db[self.collection_name]  # type: ignore

        if not self.collection_exists():
            log_info(f"Creating collection '{self.collection_name}'.")
            self._db.create_collection(self.collection_name)  # type: ignore
            self._create_search_index()
        else:
            log_info(f"Using existing collection '{self.collection_name}'.")
            self._create_search_index()

        return self._collection  # type: ignore

    def _create_search_index(self, overwrite: bool = True) -> None:
        """
        Create vector search index for Cosmos DB using IVF (Inverted File).
        """
        try:
            collection = self._get_collection()
            index_name = self.search_index_name or "vector_index_1"

            # Handle overwrite if requested
            if overwrite and index_name in collection.index_information():
                log_info(f"Dropping existing index '{index_name}'")
                collection.drop_index(index_name)

            embedding_dim = getattr(self.embedder, "embedding_dim", 1536)
            log_info(f"Creating vector search index '{index_name}'")

            # Create vector search index using Cosmos DB IVF format
            collection.create_index(
                [("embedding", "cosmosSearch")],
                name=index_name,
                cosmosSearchOptions={
                    "kind": "vector-ivf",
                    "numLists": 1,
                    "dimensions": embedding_dim,
                    "similarity": self._get_cosmos_similarity_metric(),
                },
            )

            log_info(f"Created vector search index '{index_name}' successfully")

        except Exception as e:
            logger.error(f"Error creating vector search index: {e}")
            raise

    def _get_cosmos_similarity_metric(self) -> str:
        """Convert MongoDB distance metric to Cosmos DB format."""
        # Cosmos DB supports: COS (cosine), L2 (Euclidean), IP (inner product)
        metric_mapping = {"cosine": "COS", "euclidean": "L2", "dotProduct": "IP"}
        return metric_mapping.get(self.distance_metric, "COS")

    def search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None, min_score: float = 0.0
    ) -> List[Document]:
        """
        Perform vector search using Cosmos DB's IVF vector search capabilities.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        try:
            collection = self._get_collection()

            # Construct the search pipeline
            search_stage = {
                "$search": {
                    "cosmosSearch": {"vector": query_embedding, "path": "embedding", "k": limit, "nProbes": 2},
                    "returnStoredSource": True,
                }
            }

            pipeline = [
                search_stage,
                {
                    "$project": {
                        "similarityScore": {"$meta": "searchScore"},
                        "_id": 1,
                        "name": 1,
                        "content": 1,
                        "meta_data": 1,
                    }
                },
            ]

            results = list(collection.aggregate(pipeline))
            docs = [
                Document(
                    id=str(doc["_id"]),
                    name=doc.get("name"),
                    content=doc["content"],
                    meta_data={**doc.get("meta_data", {}), "score": doc.get("similarityScore", 0.0)},
                )
                for doc in results
            ]

            log_info(f"Search completed. Found {len(docs)} documents.")
            return docs

        except Exception as e:
            logger.error(f"Error during vector search: {e}")
            return []

    def _search_index_exists(self) -> bool:
        """Override to avoid checking for vector search indexes."""
        return False

    def create(self) -> None:
        """Create the collection with appropriate indexes for Cosmos DB."""
        self._get_or_create_collection()

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        return self.search(query, limit=limit)

    def keyword_search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        try:
            collection = self._get_collection()

            # Create regex pattern from query keywords
            keywords = query.split()
            keyword_pattern = "|".join(keywords) if keywords else query

            # Build search query
            search_query = {
                # Case-insensitive regex search
                "content": {"$regex": keyword_pattern, "$options": "i"}
            }

            # Add any metadata filters
            if filters:
                for key, value in filters.items():
                    if not key.startswith("meta_data.") and "." not in key:
                        search_query[f"meta_data.{key}"] = value
                    else:
                        search_query[key] = value

            cursor = collection.find(search_query, {"_id": 1, "name": 1, "content": 1, "meta_data": 1}).limit(limit)
            docs = [
                Document(
                    id=str(doc["_id"]), name=doc.get("name"), content=doc["content"], meta_data=doc.get("meta_data", {})
                )
                for doc in cursor
            ]

            log_info(f"Search completed. Found {len(docs)} documents.")
            return docs

        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Fallback to regular search for hybrid search."""
        log_info("Hybrid search not implemented in Cosmos DB - using vector search")
        return self.search(query, limit=limit)
