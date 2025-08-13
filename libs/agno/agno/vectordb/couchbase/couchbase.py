import asyncio
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Union

from agno.document import Document
from agno.embedder import Embedder
from agno.embedder.openai import OpenAIEmbedder
from agno.utils.log import log_debug, logger
from agno.vectordb.base import VectorDb

try:
    from hashlib import md5

except ImportError:
    raise ImportError("`hashlib` not installed. Please install using `pip install hashlib`")
try:
    from acouchbase.bucket import AsyncBucket
    from acouchbase.cluster import AsyncCluster
    from acouchbase.collection import AsyncCollection
    from acouchbase.management.search import (
        ScopeSearchIndexManager as AsyncScopeSearchIndexManager,
    )
    from acouchbase.management.search import (
        SearchIndex as AsyncSearchIndex,
    )
    from acouchbase.management.search import (
        SearchIndexManager as AsyncSearchIndexManager,
    )
    from acouchbase.scope import AsyncScope
    from couchbase.bucket import Bucket
    from couchbase.cluster import Cluster
    from couchbase.collection import Collection
    from couchbase.exceptions import (
        CollectionAlreadyExistsException,
        CollectionNotFoundException,
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
        wait_until_index_ready: float = 0,
        batch_limit: int = 500,
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
            wait_until_index_ready (float, optional): Time in seconds to wait until the index is ready. Defaults to 0.
            batch_limit (int, optional): Maximum number of documents to process in a single batch (applies to both sync and async operations). Defaults to 500.
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
        self.batch_limit = batch_limit
        if isinstance(search_index, str):
            self.search_index_name = search_index
            self.search_index_definition = None
        else:
            self.search_index_name = search_index.name
            self.search_index_definition = search_index

        self._cluster: Optional[Cluster] = None
        self._bucket: Optional[Bucket] = None
        self._scope: Optional[Scope] = None
        self._collection: Optional[Collection] = None

        self._async_cluster: Optional[AsyncCluster] = None
        self._async_bucket: Optional[AsyncBucket] = None
        self._async_scope: Optional[AsyncScope] = None
        self._async_collection: Optional[AsyncCollection] = None

    @property
    def cluster(self) -> Cluster:
        """Create or retrieve the Couchbase cluster connection."""
        if self._cluster is None:
            try:
                logger.debug("Creating Couchbase Cluster connection")
                cluster = Cluster(self.connection_string, self.cluster_options)
                # Verify connection
                cluster.wait_until_ready(timeout=timedelta(seconds=60))
                logger.info("Connected to Couchbase successfully.")
                self._cluster = cluster
            except Exception as e:
                logger.error(f"Failed to connect to Couchbase: {e}")
                raise ConnectionError(f"Failed to connect to Couchbase: {e}")
        return self._cluster

    @property
    def bucket(self) -> Bucket:
        """Get the Couchbase bucket."""
        if self._bucket is None:
            self._bucket = self.cluster.bucket(self.bucket_name)
        return self._bucket

    @property
    def scope(self) -> Scope:
        """Get the Couchbase scope."""
        if self._scope is None:
            self._scope = self.bucket.scope(self.scope_name)
        return self._scope

    @property
    def collection(self) -> Collection:
        """Get the Couchbase collection."""
        if self._collection is None:
            self._collection = self.scope.collection(self.collection_name)
        return self._collection

    def _create_collection_and_scope(self):
        """
        Get or create the scope and collection within the bucket.

        Uses EAFP principle: attempts to create scope/collection and handles
        specific exceptions if they already exist or (for collections with overwrite=True)
        if they are not found for dropping.

        Raises:
            Exception: If scope or collection creation/manipulation fails unexpectedly.
        """
        # 1. Ensure Scope Exists
        try:
            self.bucket.collections().create_scope(scope_name=self.scope_name)
            logger.info(f"Created new scope '{self.scope_name}'")
        except ScopeAlreadyExistsException:
            logger.info(f"Scope '{self.scope_name}' already exists. Using existing scope.")
        except Exception as e:
            logger.error(f"Failed to create or ensure scope '{self.scope_name}' exists: {e}")
            raise

        collection_manager = self.bucket.collections()

        # 2. Handle Collection
        if self.overwrite:
            # Attempt to drop the collection first since overwrite is True
            try:
                logger.info(
                    f"Overwrite is True. Attempting to drop collection '{self.collection_name}' in scope '{self.scope_name}'."
                )
                collection_manager.drop_collection(collection_name=self.collection_name, scope_name=self.scope_name)
                logger.info(f"Successfully dropped collection '{self.collection_name}'.")
                time.sleep(1)  # Brief wait after drop, as in original code
            except CollectionNotFoundException:
                logger.info(
                    f"Collection '{self.collection_name}' not found in scope '{self.scope_name}'. No need to drop."
                )
            except Exception as e:
                logger.error(f"Error dropping collection '{self.collection_name}' during overwrite: {e}")
                raise

            # Proceed to create the collection
            try:
                logger.info(f"Creating collection '{self.collection_name}' in scope '{self.scope_name}'.")
                collection_manager.create_collection(scope_name=self.scope_name, collection_name=self.collection_name)
                logger.info(
                    f"Successfully created collection '{self.collection_name}' after drop attempt (overwrite=True)."
                )
            except CollectionAlreadyExistsException:
                # This is an unexpected state if overwrite=True and drop was supposed to clear the way.
                logger.error(
                    f"Failed to create collection '{self.collection_name}' as it already exists, "
                    f"even after drop attempt for overwrite. Overwrite operation may not have completed as intended."
                )
                raise  # Re-raise as the overwrite intent failed
            except Exception as e:
                logger.error(
                    f"Error creating collection '{self.collection_name}' after drop attempt (overwrite=True): {e}"
                )
                raise
        else:  # self.overwrite is False
            try:
                logger.info(
                    f"Overwrite is False. Attempting to create collection '{self.collection_name}' in scope '{self.scope_name}'."
                )
                collection_manager.create_collection(scope_name=self.scope_name, collection_name=self.collection_name)
                logger.info(f"Successfully created new collection '{self.collection_name}'.")
            except CollectionAlreadyExistsException:
                logger.info(
                    f"Collection '{self.collection_name}' already exists in scope '{self.scope_name}'. Using existing collection."
                )
            except Exception as e:
                logger.error(f"Error creating collection '{self.collection_name}': {e}")
                raise

    def _search_indexes_mng(self) -> Union[SearchIndexManager, ScopeSearchIndexManager]:
        """Get the search indexes manager."""
        if self.is_global_level_index:
            return self.cluster.search_indexes()
        else:
            return self.scope.search_indexes()

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
        self._create_collection_and_scope()
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
        log_debug(f"Inserting {len(documents)} documents")

        docs_to_insert: Dict[str, Any] = {}
        for document in documents:
            try:
                doc_data = self.prepare_doc(document)
                if filters:
                    doc_data["filters"] = filters
                # For insert_multi, the key of the dict is the document ID,
                # and the value is the document content itself.
                doc_id = doc_data.pop("_id")
                docs_to_insert[doc_id] = doc_data
            except Exception as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if not docs_to_insert:
            logger.info("No documents prepared for insertion.")
            return

        doc_ids = list(docs_to_insert.keys())
        total_inserted_count = 0
        total_processed_count = len(doc_ids)
        errors_occurred = False

        for i in range(0, len(doc_ids), self.batch_limit):
            batch_doc_ids = doc_ids[i : i + self.batch_limit]
            batch_docs_to_insert = {doc_id: docs_to_insert[doc_id] for doc_id in batch_doc_ids}

            if not batch_docs_to_insert:
                continue

            log_debug(f"Inserting batch of {len(batch_docs_to_insert)} documents.")
            try:
                result = self.collection.insert_multi(batch_docs_to_insert)
                # Check for errors in the batch result
                # The actual way to count successes/failures might depend on the SDK version
                # For Couchbase SDK 3.x/4.x, result.all_ok is a good indicator for the whole batch.
                # If not all_ok, result.exceptions (dict) contains errors for specific keys.

                # Simplistic success counting for this example, assuming partial success is possible
                # and we want to count how many actually made it.
                if result.all_ok:
                    batch_inserted_count = len(batch_docs_to_insert)
                    logger.info(f"Batch of {batch_inserted_count} documents inserted successfully.")
                else:
                    # If not all_ok, count successes by checking which keys are NOT in exceptions
                    # This is a more robust way than just len(batch) - len(exceptions)
                    # as some items might succeed even if others fail.
                    succeeded_ids = set(batch_docs_to_insert.keys()) - set(
                        result.exceptions.keys() if result.exceptions else []
                    )
                    batch_inserted_count = len(succeeded_ids)
                    if batch_inserted_count > 0:
                        logger.info(f"Partially inserted {batch_inserted_count} documents in batch.")
                    logger.warning(f"Bulk write error during batch insert: {result.exceptions}")
                    errors_occurred = True
                total_inserted_count += batch_inserted_count

            except Exception as e:
                logger.error(f"Error during batch bulk insert for {len(batch_docs_to_insert)} documents: {e}")
                errors_occurred = True  # Mark that an error occurred in this batch

        logger.info(f"Finished processing {total_processed_count} documents for insertion.")
        logger.info(f"Total successfully inserted: {total_inserted_count}.")
        if errors_occurred:
            logger.warning("Some errors occurred during the insert operation. Please check logs for details.")

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
                # For upsert_multi, the key of the dict is the document ID,
                # and the value is the document content itself.
                doc_id = doc_data.pop("_id")
                docs_to_upsert[doc_id] = doc_data
            except Exception as e:
                logger.error(f"Error preparing document '{document.name}': {e}")

        if not docs_to_upsert:
            logger.info("No documents prepared for upsert.")
            return

        doc_ids = list(docs_to_upsert.keys())
        total_upserted_count = 0
        total_processed_count = len(doc_ids)
        errors_occurred = False

        for i in range(0, len(doc_ids), self.batch_limit):
            batch_doc_ids = doc_ids[i : i + self.batch_limit]
            batch_docs_to_upsert = {doc_id: docs_to_upsert[doc_id] for doc_id in batch_doc_ids}

            if not batch_docs_to_upsert:
                continue

            logger.info(f"Upserting batch of {len(batch_docs_to_upsert)} documents.")
            try:
                result = self.collection.upsert_multi(batch_docs_to_upsert)
                # Similar to insert_multi, check for errors in the batch result.
                if result.all_ok:
                    batch_upserted_count = len(batch_docs_to_upsert)
                    logger.info(f"Batch of {batch_upserted_count} documents upserted successfully.")
                else:
                    succeeded_ids = set(batch_docs_to_upsert.keys()) - set(
                        result.exceptions.keys() if result.exceptions else []
                    )
                    batch_upserted_count = len(succeeded_ids)
                    if batch_upserted_count > 0:
                        logger.info(f"Partially upserted {batch_upserted_count} documents in batch.")
                    logger.warning(f"Bulk write error during batch upsert: {result.exceptions}")
                    errors_occurred = True
                total_upserted_count += batch_upserted_count

            except Exception as e:
                logger.error(f"Error during batch bulk upsert for {len(batch_docs_to_upsert)} documents: {e}")
                errors_occurred = True

        logger.info(f"Finished processing {total_processed_count} documents for upsert.")
        logger.info(f"Total successfully upserted: {total_upserted_count}.")
        if errors_occurred:
            logger.warning("Some errors occurred during the upsert operation. Please check logs for details.")

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

            # Prepare the options dictionary
            options_dict = {"limit": limit, "fields": ["*"]}
            if filters:
                options_dict["raw"] = filters

            search_args = {
                "index": self.search_index_name,
                "request": request,
                "options": SearchOptions(**options_dict),  # Construct SearchOptions with the dictionary
            }

            if self.is_global_level_index:
                results = self.cluster.search(**search_args)
            else:
                results = self.scope.search(**search_args)

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
        kv_response = self.collection.get_multi(keys=ids)

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
                self.bucket.collections().drop_collection(
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
            scopes = self.bucket.collections().get_all_scopes()
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
            search_indexes = self.cluster.search_indexes()
            if not self.is_global_level_index:
                search_indexes = self.scope.search_indexes()
            return search_indexes.get_indexed_documents_count(self.search_index_name)
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0

    def name_exists(self, name: str) -> bool:
        """Check if a document exists in the bucket based on its name."""
        try:
            # Use N1QL query to check if document with given name exists
            query = f"SELECT name FROM {self.bucket_name}.{self.scope_name}.{self.collection_name} WHERE name = $name LIMIT 1"
            result = self.scope.query(
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
            result = self.collection.exists(id)
            if not result.exists:
                logger.debug(f"Document 'does not exist': {id}")
            return result.exists
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False

    # === ASYNC SUPPORT USING acouchbase ===

    async def _create_async_cluster_instance(self) -> AsyncCluster:
        """Helper method to create and connect an AsyncCluster instance."""
        logger.debug("Creating and connecting new AsyncCluster instance.")
        cluster = await AsyncCluster.connect(self.connection_string, self.cluster_options)
        # AsyncCluster.connect ensures the cluster is ready upon successful await.
        # No explicit wait_until_ready is needed here for AsyncCluster.
        logger.info("AsyncCluster connected successfully.")
        return cluster

    async def get_async_cluster(self) -> AsyncCluster:
        """Gets or creates the cached AsyncCluster instance."""
        if self._async_cluster is None:
            logger.debug("AsyncCluster instance not cached, creating new one.")
            self._async_cluster = await self._create_async_cluster_instance()
        return self._async_cluster

    async def get_async_bucket(self) -> AsyncBucket:
        """Gets or creates the cached AsyncBucket instance."""
        if self._async_bucket is None:
            logger.debug("AsyncBucket instance not cached, creating new one.")
            cluster = await self.get_async_cluster()
            self._async_bucket = cluster.bucket(self.bucket_name)
        return self._async_bucket

    async def get_async_scope(self) -> AsyncScope:
        """Gets or creates the cached AsyncScope instance."""
        if self._async_scope is None:
            logger.debug("AsyncScope instance not cached, creating new one.")
            bucket = await self.get_async_bucket()
            self._async_scope = bucket.scope(self.scope_name)
        return self._async_scope

    async def get_async_collection(self) -> AsyncCollection:
        """Gets or creates the cached AsyncCollection instance."""
        if self._async_collection is None:
            logger.debug("AsyncCollection instance not cached, creating new one.")
            scope = await self.get_async_scope()
            self._async_collection = scope.collection(self.collection_name)
        return self._async_collection

    async def async_create(self) -> None:
        # FTS index creation is not supported in acouchbase as of now, so fallback to sync for index creation
        # This is a limitation of the SDK. You may want to document this.
        await self._async_create_collection_and_scope()
        await self._async_create_fts_index()

    async def _async_create_collection_and_scope(self):
        """
        Get or create the scope and collection within the bucket.

        Uses EAFP principle: attempts to create scope/collection and handles
        specific exceptions if they already exist or (for collections with overwrite=True)
        if they are not found for dropping.

        Raises:
            Exception: If scope or collection creation/manipulation fails unexpectedly.
        """
        # 1. Ensure Scope Exists
        async_bucket_instance = await self.get_async_bucket()
        try:
            await async_bucket_instance.collections().create_scope(self.scope_name)
            logger.info(f"Created new scope '{self.scope_name}'")
        except ScopeAlreadyExistsException:
            logger.info(f"Scope '{self.scope_name}' already exists. Using existing scope.")
        except Exception as e:
            logger.error(f"Failed to create or ensure scope '{self.scope_name}' exists: {e}")
            raise

        collection_manager = async_bucket_instance.collections()

        # 2. Handle Collection
        if self.overwrite:
            # Attempt to drop the collection first since overwrite is True
            try:
                logger.info(
                    f"Overwrite is True. Attempting to drop collection '{self.collection_name}' in scope '{self.scope_name}'."
                )
                await collection_manager.drop_collection(
                    collection_name=self.collection_name, scope_name=self.scope_name
                )
                logger.info(f"Successfully dropped collection '{self.collection_name}'.")
                time.sleep(1)  # Brief wait after drop, as in original code
            except CollectionNotFoundException:
                logger.info(
                    f"Collection '{self.collection_name}' not found in scope '{self.scope_name}'. No need to drop."
                )
            except Exception as e:
                logger.error(f"Error dropping collection '{self.collection_name}' during overwrite: {e}")
                raise

            # Proceed to create the collection
            try:
                logger.info(f"Creating collection '{self.collection_name}' in scope '{self.scope_name}'.")
                await collection_manager.create_collection(
                    scope_name=self.scope_name, collection_name=self.collection_name
                )
                logger.info(
                    f"Successfully created collection '{self.collection_name}' after drop attempt (overwrite=True)."
                )
            except CollectionAlreadyExistsException:
                # This is an unexpected state if overwrite=True and drop was supposed to clear the way.
                logger.error(
                    f"Failed to create collection '{self.collection_name}' as it already exists, "
                    f"even after drop attempt for overwrite. Overwrite operation may not have completed as intended."
                )
                raise  # Re-raise as the overwrite intent failed
            except Exception as e:
                logger.error(
                    f"Error creating collection '{self.collection_name}' after drop attempt (overwrite=True): {e}"
                )
                raise
        else:  # self.overwrite is False
            try:
                logger.info(
                    f"Overwrite is False. Attempting to create collection '{self.collection_name}' in scope '{self.scope_name}'."
                )
                await collection_manager.create_collection(
                    scope_name=self.scope_name, collection_name=self.collection_name
                )
                logger.info(f"Successfully created new collection '{self.collection_name}'.")
            except CollectionAlreadyExistsException:
                logger.info(
                    f"Collection '{self.collection_name}' already exists in scope '{self.scope_name}'. Using existing collection."
                )
            except Exception as e:
                logger.error(f"Error creating collection '{self.collection_name}': {e}")
                raise

    async def _get_async_search_indexes_mng(self) -> Union[AsyncSearchIndexManager, AsyncScopeSearchIndexManager]:
        """Get the async search indexes manager."""
        if self.is_global_level_index:
            cluster = await self.get_async_cluster()
            return cluster.search_indexes()
        else:
            scope = await self.get_async_scope()
            return scope.search_indexes()

    async def _async_create_fts_index(self):
        """Create a FTS index on the collection if it doesn't exist."""
        async_search_mng = await self._get_async_search_indexes_mng()
        try:
            # Check if index exists and handle string index name
            await async_search_mng.get_index(self.search_index_name)
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
                    await async_search_mng.drop_index(self.search_index_name)
                except SearchIndexNotFoundException:
                    logger.warning(f"Index '{self.search_index_name}' does not exist")
                except Exception as e:
                    logger.warning(f"Error dropping index (may not exist): {e}")

            await async_search_mng.upsert_index(self.search_index_definition)
            logger.info(f"Created FTS index '{self.search_index_name}'")

            if self.wait_until_index_ready:
                await self._async_wait_for_index_ready()

        except Exception as e:
            logger.error(f"Error creating FTS index '{self.search_index_name}': {e}")
            raise

    async def _async_wait_for_index_ready(self):
        """Wait until the FTS index is ready."""
        start_time = time.time()
        async_search_mng = await self._get_async_search_indexes_mng()
        while True:
            try:
                count = await async_search_mng.get_indexed_documents_count(self.search_index_name)
                if count > -1:
                    logger.info(f"FTS index '{self.search_index_name}' is ready")
                    break
                # logger.info(f"FTS index '{self.search_index_name}' is not ready yet status: {index['status']}")
            except Exception as e:
                if time.time() - start_time > self.wait_until_index_ready:
                    logger.error(f"Error checking index status: {e}")
                    raise TimeoutError("Timeout waiting for FTS index to become ready")
                await asyncio.sleep(1)

    async def async_doc_exists(self, document: Document) -> bool:
        doc_id = md5(document.content.encode("utf-8")).hexdigest()
        return await self.async_id_exists(doc_id)

    async def async_id_exists(self, id: str) -> bool:
        try:
            async_collection_instance = await self.get_async_collection()
            result = await async_collection_instance.exists(id)
            if not result.exists:
                logger.debug(f"[async] Document does not exist: {id}")
            return result.exists
        except Exception as e:
            logger.error(f"[async] Error checking document existence: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        try:
            query = f"SELECT name FROM {self.bucket_name}.{self.scope_name}.{self.collection_name} WHERE name = $name LIMIT 1"
            async_scope_instance = await self.get_async_scope()
            result = async_scope_instance.query(
                query, QueryOptions(named_parameters={"name": name}, scan_consistency=QueryScanConsistency.REQUEST_PLUS)
            )
            async for row in result.rows():
                return True
            return False
        except Exception as e:
            logger.error(f"[async] Error checking document name existence: {e}")
            return False

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.info(f"[async] Inserting {len(documents)} documents")

        async_collection_instance = await self.get_async_collection()
        all_docs_to_insert: Dict[str, Any] = {}

        for document in documents:
            try:
                # User edit: self.prepare_doc is no longer awaited with to_thread
                doc_data = self.prepare_doc(document)
                if filters:
                    doc_data["filters"] = filters
                doc_id = doc_data.pop("_id")  # Remove _id as it's used as key
                all_docs_to_insert[doc_id] = doc_data
            except Exception as e:
                logger.error(f"[async] Error preparing document '{document.name}': {e}")

        if not all_docs_to_insert:
            logger.info("[async] No documents prepared for insertion.")
            return

        doc_ids = list(all_docs_to_insert.keys())
        total_inserted_count = 0
        total_failed_count = 0
        processed_doc_count = len(all_docs_to_insert)

        for i in range(0, len(doc_ids), self.batch_limit):
            batch_doc_ids = doc_ids[i : i + self.batch_limit]

            logger.info(f"[async] Processing batch of {len(batch_doc_ids)} documents for concurrent insertion.")

            insert_tasks = []
            for doc_id in batch_doc_ids:
                doc_content = all_docs_to_insert[doc_id]
                insert_tasks.append(async_collection_instance.insert(doc_id, doc_content))

            if insert_tasks:
                results = await asyncio.gather(*insert_tasks, return_exceptions=True)
                for idx, result in enumerate(results):
                    # Get the original doc_id for logging, corresponding to the task order
                    current_doc_id = batch_doc_ids[idx]
                    if isinstance(result, Exception):
                        total_failed_count += 1
                        logger.error(f"[async] Error inserting document '{current_doc_id}': {result}")
                    else:
                        # Assuming successful insert doesn't return a specific value we need to check further,
                        # or if it does, the absence of an exception means success.
                        total_inserted_count += 1
                        logger.debug(f"[async] Successfully inserted document '{current_doc_id}'.")

        logger.info(f"[async] Finished processing {processed_doc_count} documents.")
        logger.info(f"[async] Total successfully inserted: {total_inserted_count}, Total failed: {total_failed_count}.")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.info(f"[async] Upserting {len(documents)} documents")

        async_collection_instance = await self.get_async_collection()
        all_docs_to_upsert: Dict[str, Any] = {}

        for document in documents:
            try:
                # Consistent with async_insert, prepare_doc is not awaited with to_thread based on prior user edits
                doc_data = self.prepare_doc(document)
                if filters:
                    doc_data["filters"] = filters
                doc_id = doc_data.pop("_id")  # _id is used as key for upsert
                all_docs_to_upsert[doc_id] = doc_data
            except Exception as e:
                logger.error(f"[async] Error preparing document '{document.name}' for upsert: {e}")

        if not all_docs_to_upsert:
            logger.info("[async] No documents prepared for upsert.")
            return

        doc_ids = list(all_docs_to_upsert.keys())
        total_upserted_count = 0
        total_failed_count = 0
        processed_doc_count = len(all_docs_to_upsert)

        logger.info(f"[async] Prepared {processed_doc_count} documents for upsert.")

        for i in range(0, len(doc_ids), self.batch_limit):
            batch_doc_ids = doc_ids[i : i + self.batch_limit]

            logger.info(f"[async] Processing batch of {len(batch_doc_ids)} documents for concurrent upsert.")

            upsert_tasks = []
            for doc_id in batch_doc_ids:
                doc_content = all_docs_to_upsert[doc_id]
                upsert_tasks.append(async_collection_instance.upsert(doc_id, doc_content))

            if upsert_tasks:
                results = await asyncio.gather(*upsert_tasks, return_exceptions=True)
                for idx, result in enumerate(results):
                    current_doc_id = batch_doc_ids[idx]
                    if isinstance(result, Exception):
                        total_failed_count += 1
                        logger.error(f"[async] Error upserting document '{current_doc_id}': {result}")
                    else:
                        # Assuming successful upsert doesn't return a specific value we need to check further,
                        # or if it does, the absence of an exception means success.
                        total_upserted_count += 1
                        logger.debug(f"[async] Successfully upserted document '{current_doc_id}'.")

        logger.info(f"[async] Finished processing {processed_doc_count} documents for upsert.")
        logger.info(f"[async] Total successfully upserted: {total_upserted_count}, Total failed: {total_failed_count}.")

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"[async] Failed to generate embedding for query: {query}")
            return []
        try:
            # Implement vector search using Couchbase FTS
            vector_search = VectorSearch.from_vector_query(
                VectorQuery(field_name="embedding", vector=query_embedding, num_candidates=limit)
            )
            request = SearchRequest.create(vector_search)

            # Prepare the options dictionary
            options_dict = {"limit": limit, "fields": ["*"]}
            if filters:
                options_dict["raw"] = filters

            search_args = {
                "index": self.search_index_name,
                "request": request,
                "options": SearchOptions(**options_dict),  # Construct SearchOptions with the dictionary
            }

            if self.is_global_level_index:
                async_cluster_instance = await self.get_async_cluster()
                results = async_cluster_instance.search(**search_args)
            else:
                async_scope_instance = await self.get_async_scope()
                results = async_scope_instance.search(**search_args)

            return await self.__async_get_doc_from_kv(results)
        except Exception as e:
            logger.error(f"[async] Error during search: {e}")
            raise

    async def async_drop(self) -> None:
        if await self.async_exists():
            try:
                async_bucket_instance = await self.get_async_bucket()
                await async_bucket_instance.collections().drop_collection(
                    collection_name=self.collection_name, scope_name=self.scope_name
                )
                logger.info(f"[async] Collection '{self.collection_name}' dropped successfully.")
            except Exception as e:
                logger.error(f"[async] Error dropping collection '{self.collection_name}': {e}")
                raise

    async def async_exists(self) -> bool:
        try:
            async_bucket_instance = await self.get_async_bucket()
            scopes = await async_bucket_instance.collections().get_all_scopes()
            for scope in scopes:
                if scope.name == self.scope_name:
                    for collection in scope.collections:
                        if collection.name == self.collection_name:
                            return True
            return False
        except Exception:
            return False

    async def __async_get_doc_from_kv(self, response: AsyncSearchIndex) -> List[Document]:
        """
        Convert search results to Document objects by fetching full documents from KV store concurrently.

        Args:
            response: SearchResult from Couchbase search query

        Returns:
            List of Document objects
        """
        documents: List[Document] = []
        # Assuming search_hits map directly to the order of documents we want to fetch and reconstruct
        search_hits_map = {doc.id: doc.score async for doc in response.rows()}
        doc_ids_to_fetch = list(search_hits_map.keys())

        if not doc_ids_to_fetch:
            return documents

        async_collection_instance = await self.get_async_collection()

        # Process in batches
        for i in range(0, len(doc_ids_to_fetch), self.batch_limit):
            batch_doc_ids = doc_ids_to_fetch[i : i + self.batch_limit]
            if not batch_doc_ids:
                continue

            logger.debug(f"[async] Fetching batch of {len(batch_doc_ids)} documents from KV.")
            get_tasks = [async_collection_instance.get(doc_id) for doc_id in batch_doc_ids]

            # Fetch documents from KV store concurrently for the current batch
            results_from_kv_batch = await asyncio.gather(*get_tasks, return_exceptions=True)

            for batch_idx, get_result in enumerate(results_from_kv_batch):
                # Original doc_id corresponding to this result within the batch
                doc_id = batch_doc_ids[batch_idx]
                # score = search_hits_map[doc_id]  # Retrieve the original score

                if isinstance(get_result, BaseException) or isinstance(get_result, Exception) or get_result is None:
                    logger.warning(f"[async] Document {doc_id} not found or error fetching from KV store: {get_result}")
                    continue

                try:
                    value = get_result.content_as[dict]
                    if not isinstance(value, dict):
                        logger.warning(
                            f"[async] Document {doc_id} content from KV is not a dict: {type(value)}. Skipping."
                        )
                        continue

                    documents.append(
                        Document(
                            id=doc_id,
                            name=value.get("name"),
                            content=value.get("content", ""),
                            meta_data=value.get("meta_data", {}),
                            embedding=value.get("embedding", []),
                        )
                    )
                except Exception as e:
                    logger.warning(
                        f"[async] Error processing document {doc_id} from KV store: {e}. Value: {getattr(get_result, 'content_as', 'N/A')}"
                    )
                    continue

        return documents
