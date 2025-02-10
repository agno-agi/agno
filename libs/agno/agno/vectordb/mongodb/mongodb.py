import time
from typing import Any, Dict, List, Optional

from agno.document import Document
from agno.embedder import Embedder
from agno.embedder.openai import OpenAIEmbedder
from agno.utils.log import logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance

try:
    from hashlib import md5

except ImportError:
    raise ImportError("`hashlib` not installed. Please install using `pip install hashlib`")
try:
    from pymongo import MongoClient, errors
    from pymongo.collection import Collection
    from pymongo.operations import SearchIndexModel

except ImportError:
    raise ImportError("`pymongo` not installed. Please install using `pip install pymongo`")


class MongoDb(VectorDb):
    """
    MongoDB Vector Database implementation with elegant handling of Atlas Search index creation.
    """

    def __init__(
        self,
        collection_name: str,
        db_url: Optional[str] = "mongodb://localhost:27017/",
        database: str = "ai",
        embedder: Embedder = OpenAIEmbedder(),
        distance_metric: str = Distance.cosine,
        overwrite: bool = False,
        wait_until_index_ready: Optional[float] = None,
        wait_after_insert: Optional[float] = None,
        **kwargs,
    ):
        """
        Initialize the MongoDb with MongoDB collection details.

        Args:
            collection_name (str): Name of the MongoDB collection.
            db_url (Optional[str]): MongoDB connection string.
            database (str): Database name.
            embedder (Embedder): Embedder instance for generating embeddings.
            distance_metric (str): Distance metric for similarity.
            overwrite (bool): Overwrite existing collection and index if True.
            wait_until_index_ready (float): Time in seconds to wait until the index is ready.
            **kwargs: Additional arguments for MongoClient.
        """
        if not collection_name:
            raise ValueError("Collection name must not be empty.")
        self.collection_name = collection_name
        self.database = database
        self.embedder = embedder
        self.distance_metric = distance_metric
        self.connection_string = db_url
        self.overwrite = overwrite
        self.wait_until_index_ready = wait_until_index_ready
        self.wait_after_insert = wait_after_insert
        self.kwargs = kwargs

        self._client = self._get_client()
        self._db = self._client[self.database]
        self._collection = self._get_or_create_collection()

    def _get_client(self) -> MongoClient:
        """Create or retrieve the MongoDB client."""
        try:
            logger.debug("Creating MongoDB Client")
            client: MongoClient = MongoClient(self.connection_string, **self.kwargs)
            # Trigger a connection to verify the client
            client.admin.command("ping")
            logger.info("Connected to MongoDB successfully.")
            return client
        except errors.ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise ConnectionError(f"Failed to connect to MongoDB: {e}")
        except Exception as e:
            logger.error(f"An error occurred while connecting to MongoDB: {e}")
            raise

    def _get_or_create_collection(self) -> Collection:
        """Get or create the MongoDB collection, handling Atlas Search index creation."""

        self._collection = self._db[self.collection_name]

        if not self.collection_exists():
            logger.info(f"Creating collection '{self.collection_name}'.")
            self._db.create_collection(self.collection_name)
            self._create_search_index()
        else:
            logger.info(f"Using existing collection '{self.collection_name}'.")
            # check if index exists
            logger.info(f"Checking if search index '{self.collection_name}' exists.")
            if not self._search_index_exists():
                logger.info(f"Search index '{self.collection_name}' does not exist. Creating it.")
                self._create_search_index()
                if self.wait_until_index_ready:
                    self._wait_for_index_ready()
        return self._collection

    def _create_search_index(self, overwrite: bool = True) -> None:
        """Create or overwrite the Atlas Search index."""
        index_name = "vector_index_1"
        try:
            if overwrite and self._search_index_exists():
                logger.info(f"Dropping existing search index '{index_name}'.")
                self._collection.drop_search_index(index_name)

            logger.info(f"Creating search index '{index_name}'.")

            search_index_model = SearchIndexModel(
                definition={
                    "fields": [
                        {
                            "type": "vector",
                            "numDimensions": 1536,
                            "path": "embedding",
                            "similarity": self.distance_metric,  # cosine
                        },
                    ]
                },
                name=index_name,
                type="vectorSearch",
            )

            # Create the Atlas Search index
            self._collection.create_search_index(model=search_index_model)
            logger.info(f"Search index '{index_name}' created successfully.")
        except errors.OperationFailure as e:
            logger.error(f"Failed to create search index: {e}")
            raise

    def _search_index_exists(self) -> bool:
        """Check if the search index exists."""
        index_name = "vector_index_1"
        try:
            indexes = list(self._collection.list_search_indexes())
            exists = any(index["name"] == index_name for index in indexes)
            return exists
        except Exception as e:
            logger.error(f"Error checking search index existence: {e}")
            return False

    def _wait_for_index_ready(self) -> None:
        """Wait until the Atlas Search index is ready."""
        start_time = time.time()
        index_name = "vector_index_1"
        while True:
            try:
                if self._search_index_exists():
                    logger.info(f"Search index '{index_name}' is ready.")
                    break
            except Exception as e:
                logger.error(f"Error checking index status: {e}")
            if time.time() - start_time > self.wait_until_index_ready:  # type: ignore
                raise TimeoutError("Timeout waiting for search index to become ready.")
            time.sleep(1)

    def collection_exists(self) -> bool:
        """Check if the collection exists in the database."""
        return self.collection_name in self._db.list_collection_names()

    def create(self) -> None:
        """Create the MongoDB collection and indexes if they do not exist."""
        self._get_or_create_collection()

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the MongoDB collection based on its content."""
        doc_id = md5(document.content.encode("utf-8")).hexdigest()
        try:
            exists = self._collection.find_one({"_id": doc_id}) is not None
            logger.debug(f"Document {'exists' if exists else 'does not exist'}: {doc_id}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False

    def name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists in the collection."""
        try:
            exists = self._collection.find_one({"name": name}) is not None
            logger.debug(f"Document with name '{name}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document name existence: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with a given ID exists in the collection."""
        try:
            exists = self._collection.find_one({"_id": id}) is not None
            logger.debug(f"Document with ID '{id}' {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking document ID existence: {e}")
            return False

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the MongoDB collection."""
        logger.info(f"Inserting {len(documents)} documents")

        prepared_docs = []
        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                prepared_docs.append(doc_data)
            except ValueError as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if prepared_docs:
            try:
                self._collection.insert_many(prepared_docs, ordered=False)
                logger.info(f"Inserted {len(prepared_docs)} documents successfully.")
                # lets wait for 5 minutes.... just in case
                # feel free to 'optimize'... :)
                if self.wait_after_insert and self.wait_after_insert > 0:
                    time.sleep(self.wait_after_insert)
            except errors.BulkWriteError as e:
                logger.warning(f"Bulk write error while inserting documents: {e.details}")
            except Exception as e:
                logger.error(f"Error inserting documents: {e}")

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the MongoDB collection."""
        logger.info(f"Upserting {len(documents)} documents")

        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                self._collection.update_one(
                    {"_id": doc_data["_id"]},
                    {"$set": doc_data},
                    upsert=True,
                )
                logger.info(f"Upserted document: {doc_data['_id']}")
            except Exception as e:
                logger.error(f"Error upserting document '{document.name}': {e}")

    def upsert_available(self) -> bool:
        """Indicate that upsert functionality is available."""
        return True

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search the MongoDB collection for documents relevant to the query."""
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "vector_index_1",
                        "limit": 10,
                        "numCandidates": 10,
                        "queryVector": self.embedder.get_embedding(query),
                        "path": "embedding",
                    }
                },
                {"$set": {"score": {"$meta": "vectorSearchScore"}}},
            ]
            pipeline.append({"$project": {"embedding": 0}})
            agg = list(self._collection.aggregate(pipeline))  # type: ignore
            docs = []
            for doc in agg:
                docs.append(
                    Document(
                        id=str(doc["_id"]),
                        name=doc.get("name"),
                        content=doc["content"],
                        meta_data=doc.get("meta_data", {}),
                    )
                )
            logger.info(f"Search completed. Found {len(docs)} documents.")
            return docs
        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a vector-based search."""
        logger.debug("Performing vector search.")
        return self.search(query, limit=limit)

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a keyword-based search."""
        try:
            cursor = self._collection.find(
                {"content": {"$regex": query, "$options": "i"}},
                {"_id": 1, "name": 1, "content": 1, "meta_data": 1},
            ).limit(limit)
            results = [
                Document(
                    id=str(doc["_id"]),
                    name=doc.get("name"),
                    content=doc["content"],
                    meta_data=doc.get("meta_data", {}),
                )
                for doc in cursor
            ]
            logger.debug(f"Keyword search completed. Found {len(results)} documents.")
            return results
        except Exception as e:
            logger.error(f"Error during keyword search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
        """Perform a hybrid search combining vector and keyword-based searches."""
        logger.debug("Performing hybrid search is not yet implemented.")
        return []

    def drop(self) -> None:
        """Drop the collection from the database."""
        if self.exists():
            try:
                logger.debug(f"Dropping collection '{self.collection_name}'.")
                self._collection.drop()
                logger.info(f"Collection '{self.collection_name}' dropped successfully.")
                # Add delay to allow lucene index to be deleted
                time.sleep(50)
                """
                pymongo.errors.OperationFailure: Duplicate Index, full error: {'ok': 0.0, 'errmsg': 'Duplicate Index', 'code': 68, 'codeName': 'IndexAlreadyExists', '$clusterTime': {'clusterTime': Timestamp(1733205025, 28), 'signature': {'hash': b'', 'keyId': 7394931654956941332}}, 'operationTime': Timestamp(1733205025, 28)}
                """
            except Exception as e:
                logger.error(f"Error dropping collection '{self.collection_name}': {e}")
                raise
        else:
            logger.info(f"Collection '{self.collection_name}' does not exist.")

    def exists(self) -> bool:
        """Check if the MongoDB collection exists."""
        exists = self.collection_exists()
        logger.debug(f"Collection '{self.collection_name}' existence: {exists}")
        return exists

    def optimize(self) -> None:
        """TODO: not implemented"""
        pass

    def delete(self) -> bool:
        """Delete the entire collection from the database."""
        if self.exists():
            try:
                self._collection.drop()
                logger.info(f"Collection '{self.collection_name}' deleted successfully.")
                return True
            except Exception as e:
                logger.error(f"Error deleting collection '{self.collection_name}': {e}")
                return False
        else:
            logger.warning(f"Collection '{self.collection_name}' does not exist.")
            return False

    def prepare_doc(self, document: Document) -> Dict[str, Any]:
        """Prepare a document for insertion or upsertion into MongoDB."""
        document.embed(embedder=self.embedder)
        if document.embedding is None:
            raise ValueError(f"Failed to generate embedding for document: {document.id}")

        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode("utf-8")).hexdigest()
        doc_data = {
            "_id": doc_id,
            "name": document.name,
            "content": cleaned_content,
            "meta_data": document.meta_data,
            "embedding": document.embedding,
        }
        logger.debug(f"Prepared document: {doc_data['_id']}")
        return doc_data

    def get_count(self) -> int:
        """Get the count of documents in the MongoDB collection."""
        try:
            count = self._collection.count_documents({})
            logger.debug(f"Collection '{self.collection_name}' has {count} documents.")
            return count
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0
