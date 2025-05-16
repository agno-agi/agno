import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Union

from agno.document import Document
from agno.embedder import Embedder
from agno.embedder.openai import OpenAIEmbedder
from agno.utils.log import logger
from agno.vectordb.base import VectorDb

try:
    from hashlib import md5

except ImportError:
    raise ImportError("`hashlib` not installed. Please install using `pip install hashlib`")
try:
    from couchbase.cluster import Cluster
    from couchbase.collection import Collection
    from couchbase.exceptions import (
        BucketDoesNotExistException,
        DocumentNotFoundException,
        ScopeAlreadyExistsException,
        SearchIndexNotFoundException,
    )
    from couchbase.management.search import ScopeSearchIndexManager, SearchIndex, SearchIndexManager
    from couchbase.n1ql import QueryScanConsistency
    from couchbase.options import ClusterOptions, QueryOptions, SearchOptions
    from couchbase.result import SearchResult
    from couchbase.scope import Scope
    from couchbase.search import SearchRequest
    from couchbase.vector_search import VectorQuery, VectorSearch
except ImportError:
    raise ImportError("`couchbase` not installed. Please install using `pip install couchbase`")


class CouchbaseSearch(VectorDb):
    """
    Couchbase Vector Database implementation with FTS (Full Text Search) index support.
    """

    def __init__(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
        couchbase_connection_string: str,
        cluster_options: ClusterOptions,
        search_index: Union[str, SearchIndex],
        embedder: Embedder = OpenAIEmbedder(),
        overwrite: bool = False,
        is_global_level_index: bool = False,
        wait_until_index_ready: Optional[float] = None,
        **kwargs,
    ):
        """
        Initialize the CouchbaseSearch with Couchbase connection details.

        Args:
            bucket_name (str): Name of the Couchbase bucket.
            scope_name (str): Name of the scope within the bucket.
            collection_name (str): Name of the collection within the scope.
            couchbase_connection_string (str): Couchbase connection string.
            cluster_options (ClusterOptions): Options for configuring the Couchbase cluster connection.
            search_index (Union[str, SearchIndex], optional): Search index configuration, either as index name or SearchIndex definition.
            embedder (Embedder): Embedder instance for generating embeddings. Defaults to OpenAIEmbedder.
            overwrite (bool): Whether to overwrite existing collection. Defaults to False.
            wait_until_index_ready (float, optional): Time in seconds to wait until the index is ready. Defaults to None.
            **kwargs: Additional arguments for Couchbase connection.
        """
        if not bucket_name:
            raise ValueError("Bucket name must not be empty.")

        self.bucket_name = bucket_name
        self.scope_name = scope_name
        self.collection_name = collection_name
        self.connection_string = couchbase_connection_string
        self.cluster_options = cluster_options
        self.embedder = embedder
        self.overwrite = overwrite
        self.is_global_level_index = is_global_level_index
        self.wait_until_index_ready = wait_until_index_ready
        self.kwargs = kwargs
        if isinstance(search_index, str):
            self.search_index_name = search_index
            self.search_index_definition = None
        else:
            self.search_index_name = search_index.name
            self.search_index_definition = search_index

        self._cluster = self._get_cluster()
        self._bucket = self._get_bucket()
        self._scope: Scope = None
        self._collection: Collection = None

    def _get_cluster(self) -> Cluster:
        """Create or retrieve the Couchbase cluster connection."""
        try:
            logger.debug("Creating Couchbase Cluster connection")
            cluster = Cluster(self.connection_string, self.cluster_options)
            # Verify connection
            cluster.wait_until_ready(timeout=timedelta(seconds=60))
            logger.info("Connected to Couchbase successfully.")
            return cluster
        except Exception as e:
            logger.error(f"Failed to connect to Couchbase: {e}")
            raise ConnectionError(f"Failed to connect to Couchbase: {e}")

    def _get_bucket(self):
        """Get the Couchbase bucket."""
        try:
            bucket = self._cluster.bucket(self.bucket_name)
            return bucket
        except BucketDoesNotExistException as e:
            logger.error(f"Bucket '{self.bucket_name}': {e}")
            raise

    def _get_or_create_collection_and_scope(self) -> Collection:
        """
        Get or create the scope and collection within the bucket.

        First checks if scope exists, creates it if not. Then lists collections
        in the scope and creates collection if needed.

        Returns:
            Collection: The Couchbase collection object

        Raises:
            Exception: If scope or collection creation fails
        """
        # Get all scopes and check if our scope exists
        scopes = self._bucket.collections().get_all_scopes()
        scope_exists = any(scope.name == self.scope_name for scope in scopes)

        if not scope_exists:
            try:
                # Create new scope
                self._bucket.collections().create_scope(self.scope_name)
                logger.info(f"Created new scope '{self.scope_name}'")
                scopes = self._bucket.collections().get_all_scopes()
            except ScopeAlreadyExistsException:
                logger.info(f"Scope '{self.scope_name}' already exists")
            except Exception as e:
                logger.error(f"Error creating scope '{self.scope_name}': {e}")
                raise

        # Get scope object
        self._scope = self._bucket.scope(self.scope_name)

        # List all collections in the scope
        collections = [scope.collections for scope in scopes if scope.name == self.scope_name][0]
        collection_exists = any(coll.name == self.collection_name for coll in collections)

        if collection_exists and self.overwrite:
            try:
                # Drop existing collection if overwrite is True
                logger.info(f"Dropping existing collection '{self.collection_name}'")
                self._bucket.collections().drop_collection(
                    collection_name=self.collection_name, scope_name=self.scope_name
                )
                collection_exists = False
                time.sleep(1)  # Brief wait after drop
            except Exception as e:
                logger.error(f"Error dropping collection: {e}")
                raise

        if not collection_exists:
            try:
                # Create new collection
                logger.info(f"Creating new collection '{self.collection_name}'")
                self._bucket.collections().create_collection(
                    scope_name=self.scope_name, collection_name=self.collection_name
                )
            except Exception as e:
                logger.error(f"Error creating collection: {e}")
                raise
        else:
            logger.info(f"Using existing collection '{self.collection_name}'")

        return self._scope.collection(self.collection_name)

    def _search_indexes_mng(self) -> Union[SearchIndexManager, ScopeSearchIndexManager]:
        """Get the search indexes manager."""
        if self.is_global_level_index:
            return self._cluster.search_indexes()
        else:
            return self._scope.search_indexes()

    def _create_fts_index(self):
        """Create a FTS index on the collection if it doesn't exist."""
        try:
            # Check if index exists and handle string index name
            self._search_indexes_mng().get_index(self.search_index_name)
            if not self.overwrite:
                return
        except Exception:
            if self.search_index_definition is None:
                raise ValueError(f"Index '{self.search_index_name}' does not exist")

        # Create or update index
        try:
            if self.overwrite:
                try:
                    logger.info(f"Dropping existing FTS index '{self.search_index_name}'")
                    self._search_indexes_mng().drop_index(self.search_index_name)
                except SearchIndexNotFoundException:
                    logger.warning(f"Index '{self.search_index_name}' does not exist")
                except Exception as e:
                    logger.warning(f"Error dropping index (may not exist): {e}")

            self._search_indexes_mng().upsert_index(self.search_index_definition)
            logger.info(f"Created FTS index '{self.search_index_name}'")

            if self.wait_until_index_ready:
                self._wait_for_index_ready()

        except Exception as e:
            logger.error(f"Error creating FTS index '{self.search_index_name}': {e}")
            raise

    def _wait_for_index_ready(self):
        """Wait until the FTS index is ready."""
        start_time = time.time()
        while True:
            try:
                count = self._search_indexes_mng().get_indexed_documents_count(self.search_index_name)
                if count > -1:
                    logger.info(f"FTS index '{self.search_index_name}' is ready")
                    break
                # logger.info(f"FTS index '{self.search_index_name}' is not ready yet status: {index['status']}")
            except Exception as e:
                if time.time() - start_time > self.wait_until_index_ready:
                    logger.error(f"Error checking index status: {e}")
                    raise TimeoutError("Timeout waiting for FTS index to become ready")
                time.sleep(1)

    def create(self) -> None:
        """Create the collection and FTS index if they don't exist."""
        self._collection = self._get_or_create_collection_and_scope()
        self._create_fts_index()

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the bucket based on its content."""
        doc_id = md5(document.content.encode("utf-8")).hexdigest()
        return self.id_exists(doc_id)

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Insert documents into the Couchbase bucket. Fails if any document already exists.

        Args:
            documents: List of documents to insert
            filters: Optional filters to apply to the documents
        """
        logger.info(f"Inserting {len(documents)} documents")

        docs_to_insert: Dict[str, Any] = {}
        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                if filters:
                    doc_data["filters"] = filters
                docs_to_insert[doc_data["_id"]] = doc_data
                del doc_data["_id"]
            except Exception as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if docs_to_insert:
            try:
                result = self._collection.insert_multi(docs_to_insert)
                if result.all_ok:
                    logger.info(f"Inserted {len(docs_to_insert)} documents successfully")
                else:
                    logger.warning(f"Bulk write error while inserting documents: {result.exceptions}")
            except Exception as e:
                logger.error(f"Error during bulk insert: {e}")

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Update existing documents or insert new ones into the Couchbase bucket.

        Args:
            documents: List of documents to upsert
            filters: Optional filters to apply to the documents
        """
        logger.info(f"Upserting {len(documents)} documents")

        docs_to_upsert: Dict[str, Any] = {}
        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                if filters:
                    doc_data["filters"] = filters
                docs_to_upsert[doc_data["_id"]] = doc_data
                del doc_data["_id"]
            except Exception as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if docs_to_upsert:
            try:
                result = self._collection.upsert_multi(docs_to_upsert)
                if result.all_ok:
                    logger.info(f"Upserted {len(docs_to_upsert)} documents successfully")
                else:
                    logger.warning(f"Bulk write error while upserting documents {result.exceptions}")
            except Exception as e:
                logger.error(f"Error during bulk upsert: {e}")

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search the Couchbase bucket for documents relevant to the query."""
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Failed to generate embedding for query: {query}")
            return []

        try:
            # Implement vector search using Couchbase FTS
            vector_search = VectorSearch.from_vector_query(
                VectorQuery(field_name="embedding", vector=query_embedding, num_candidates=limit)
            )
            request = SearchRequest.create(vector_search)

            search_args = {
                "index": self.search_index_name,
                "request": request,
                "options": SearchOptions(limit=limit, fields=["*"]),
            }
            if filters:
                search_args["options"].raw = filters

            if self.is_global_level_index:
                results = self._cluster.search(**search_args)
            else:
                results = self._scope.search(**search_args)

            return self.__get_doc_from_kv(results)
        except Exception as e:
            logger.error(f"Error during search: {e}")
            raise

    def __get_doc_from_kv(self, response: SearchResult) -> List[Document]:
        """
        Convert search results to Document objects by fetching full documents from KV store.

        Args:
            response: SearchResult from Couchbase search query

        Returns:
            List of Document objects
        """
        documents: List[Document] = []
        search_hits = [(doc.id, doc.score) for doc in response.rows()]

        if not search_hits:
            return documents

        # Fetch documents from KV store
        ids = [hit[0] for hit in search_hits]
        kv_response = self._collection.get_multi(keys=ids)

        if not kv_response.all_ok:
            raise Exception(f"Failed to get documents from KV store: {kv_response.exceptions}")

        # Convert results to Documents
        for doc_id, score in search_hits:
            get_result = kv_response.results.get(doc_id)
            if get_result is None or not get_result.success:
                logger.warning(f"Document {doc_id} not found in KV store")
                continue

            value = get_result.value
            documents.append(
                Document(
                    id=doc_id,
                    name=value["name"],
                    content=value["content"],
                    meta_data=value["meta_data"],
                    embedding=value["embedding"],
                )
            )

        return documents

    def drop(self) -> None:
        """Delete the collection from the scope."""
        if self.exists():
            try:
                self._bucket.collections().drop_collection(
                    collection_name=self.collection_name, scope_name=self.scope_name
                )
                logger.info(f"Collection '{self.collection_name}' dropped successfully.")
            except Exception as e:
                logger.error(f"Error dropping collection '{self.collection_name}': {e}")
                raise

    def delete(self) -> bool:
        """Delete the collection from the scope."""
        if self.exists():
            self.drop()
            return True
        return False

    def exists(self) -> bool:
        """Check if the collection exists."""
        try:
            scopes = self._bucket.collections().get_all_scopes()
            for scope in scopes:
                if scope.name == self.scope_name:
                    for collection in scope.collections:
                        if collection.name == self.collection_name:
                            return True
            return False
        except Exception:
            return False

    def prepare_doc(self, document: Document) -> Dict[str, Any]:
        """
        Prepare a document for insertion into Couchbase.

        Args:
            document: Document to prepare

        Returns:
            Dictionary containing document data ready for insertion

        Raises:
            ValueError: If embedding generation fails
        """
        if not document.content:
            raise ValueError(f"Document {document.name} has no content")

        logger.debug(f"Preparing document: {document.name}")

        # Generate embedding if needed
        if document.embedding is None:
            document.embed(embedder=self.embedder)

        if document.embedding is None:
            raise ValueError(f"Failed to generate embedding for document: {document.name}")

        # Clean content and generate ID
        cleaned_content = document.content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode("utf-8")).hexdigest()

        return {
            "_id": doc_id,
            "name": document.name,
            "content": cleaned_content,
            "meta_data": document.meta_data,  # Ensure meta_data is never None
            "embedding": document.embedding,
        }

    def get_count(self) -> int:
        """Get the count of documents in the Couchbase bucket."""
        try:
            search_indexes = self._cluster.search_indexes()
            if not self.is_global_level_index:
                search_indexes = self._scope.search_indexes()
            return search_indexes.get_indexed_documents_count(self.search_index_name)
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0

    def name_exists(self, name: str) -> bool:
        """Check if a document exists in the bucket based on its name."""
        try:
            # Use N1QL query to check if document with given name exists
            query = f"SELECT name FROM {self.bucket_name}.{self.scope_name}.{self.collection_name} WHERE name = $name LIMIT 1"
            result = self._scope.query(
                query, QueryOptions(named_parameters={"name": name}, scan_consistency=QueryScanConsistency.REQUEST_PLUS)
            )
            for row in result.rows():
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking document name existence: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document exists in the bucket based on its ID."""
        try:
            result = self._collection.exists(id)
            if not result.exists:
                logger.debug(f"Document 'does not exist': {id}")
            return result.exists
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False
