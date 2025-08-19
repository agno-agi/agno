import asyncio
import time
from hashlib import md5
from typing import Any, Optional

from meilisearch import Client
from meilisearch.errors import MeilisearchApiError
from meilisearch.models.task import TaskInfo

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_error, log_exception, log_info
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


class MeiliSearch(VectorDb):
    """MeiliSearch vector database implementation."""

    def __init__(
        self,
        index_name: str,
        url: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        search_type: SearchType = SearchType.vector,
        api_key: Optional[str] = None,
        settings: Optional[dict[str, Any]] = None,
        reranker: Optional[Reranker] = None,
        wait_check_task: bool = False,
        check_task_timeout_ms: int = 5000,
        check_task_interval_ms: int = 50,
        semanticRatio: float = 0.5,
        rankingScoreThreshold: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize MeiliSearch database.

        Args:
            index_name (str): Index name
            url (Optional[str]): MeiliSearch API key
            embedder (Optional[Embedder]): Embedder for document contents
            search_type (SearchType): Type of search to perform.
            api_key (Optional[str]): MeiliSearch API key
            settings (Optional[dict[str, Any]]): MeiliSearch index settings including:
                - stop_words (list[str]): Stop words for index
                - synonyms (dict[str, list[str]]): Synonyms for index
                - separator_tokens (list[str]): Separator tokens
                - ranking_rules (list[str]): Ranking rules
            reranker (Optional[Reranker]): Reranker for search results
            wait_check_task (bool):  wait for the task to complete (Create, Update, Delete)
            check_task_timeout_ms (int): task check timeout
            check_task_interval_ms (int): task check interval
            semanticRatio (float): the proportion between keyword and semantic search results
            rankingScoreThreshold (Optional[float]): excludes results below the specified ranking score.
            **kwargs: Additional arguments for MeiliSearch client
        """
        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder

        # Index setting
        self.index_name: str = index_name

        # Initialize base settings
        self.setting_conf = {
            "searchableAttributes": ["content"],
            "filterableAttributes": ["meta_data", "filters", "name", "create_time", "update_time"],
            "sortableAttributes": ["create_time", "update_time", "meta_data.chunk"],
            "embedders": {"content_embedding": {"source": "userProvided", "dimensions": self.embedder.dimensions}},
        }

        # Update with user provided settings
        if settings:
            self.setting_conf.update(settings)

        # Search type
        self.search_type: SearchType = search_type
        # MeiliSearch client instance
        self.url: Optional[str] = url
        self.api_key: Optional[str] = api_key
        self._client: Optional[Client] = None

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        self.__wait_check_task = wait_check_task

        # Check task interval and timeout
        self.__check_task_interval_ms = check_task_interval_ms
        self.__check_task_timeout_ms = check_task_timeout_ms

        #  Semantic search ratio
        if semanticRatio < 0.0 or semanticRatio > 1.0:
            raise ValueError("Semantic search ratio must be between 0.0 and 1.0")
        self.__semanticRatio = semanticRatio

        # rankingScoreThreshold
        if rankingScoreThreshold is not None:
            if rankingScoreThreshold < 0.0 or rankingScoreThreshold > 1.0:
                raise ValueError("rankingScoreThreshold must be between 0.0 and 1.0")
        self.rankingScoreThreshold = rankingScoreThreshold
        # MeiliSearch client kwargs
        self.kwargs = kwargs

    @property
    def client(self) -> Client:
        """Get MeiliSearch client instance.

        Returns:
            MeiliSearchClient: MeiliSearch client instance
        """
        if self._client is None:
            log_debug("Creating MeiliSearch Client")
            if self.url is None:
                raise ValueError("MeiliSearch URL is not provided")
            self._client = Client(url=self.url, api_key=self.api_key)
        return self._client

    def create(self) -> None:
        """Create the index in MeiliSearch."""
        if self.exists():
            log_info(f"Index '{self.index_name}' already exists, skipping creation")
            return None
        else:
            log_info(f"Creating index '{self.index_name}'")
            create_task = self.client.create_index(self.index_name, options={"primaryKey": "id"})
            if not self.wait_for_task(create_task):
                log_error(f"Failed to create index '{self.index_name}', task_id: {create_task.task_uid}")
                raise MeiliSearchOperationError(f"Failed to create index '{self.index_name}'")
            setting_task = self.client.index(self.index_name).update_settings(self.setting_conf)
            if not self.wait_for_task(setting_task):
                log_error(f"Failed to update settings for index '{self.index_name}', task_id: {setting_task.task_uid}")
                raise MeiliSearchOperationError(f"Failed to update settings for index '{self.index_name}'")
            log_info(f"Successfully created and configured index '{self.index_name}'")

    async def async_create(self) -> None:
        await asyncio.to_thread(self.create)

    def wait_for_task(self, task_info: TaskInfo) -> bool:
        """Wait for a task to complete and check result"""
        if not self.__wait_check_task:
            return True

        if task_info.status == "succeeded":
            log_debug(f"Task {task_info.task_uid} completed successfully")
            return True
        else:
            task = self.client.wait_for_task(
                task_info.task_uid, self.__check_task_timeout_ms, self.__check_task_interval_ms
            )
            if task.status == "succeeded":
                log_debug(f"Task {task_info.task_uid} completed successfully after waiting")
                return True
            else:
                log_error(f"Task {task_info.task_uid} failed - Details: {task.details}, Error: {task.error}")
                return False

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the index."""
        try:
            if document is None:
                raise ValueError("Document cannot be None")
            if document.id is None:
                raise ValueError("Document id cannot be None")
            return self.client.index(self.index_name).get_document(document.id) is not None
        except MeilisearchApiError as apiExe:
            if hasattr(apiExe, "code") and apiExe.code == "document_not_found":
                return False
            log_exception(f"Error in Meilisearch doc_exists for document: {document.id} Error: {apiExe}")
            raise apiExe  # noqa
        except Exception as exe:
            log_exception(f"Error in Meilisearch doc_exists for document: {document.id} Error: {exe}")
            raise exe  # noqa

    async def async_doc_exists(self, document: Document) -> bool:
        return await asyncio.to_thread(self.doc_exists, document)

    def name_exists(self, name: str) -> bool:
        documents = self.client.index(self.index_name).get_documents({"limit": 1, "filter": f"name={name}"})
        return bool(documents and documents.total >= 1)

    async def async_name_exists(self, name: str) -> bool:  # type: ignore
        """Check if name exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        """Check if a document ID exists in the index.

        Args:
            id (str): The document ID to check

        Returns:
            bool: True if the document exists, False otherwise
        """
        if id is None or not id:
            return False
        try:
            return self.client.index(self.index_name).get_document(id) is not None
        except MeilisearchApiError as apiExe:
            if hasattr(apiExe, "code") and apiExe.code == "document_not_found":
                return False
            log_exception(f"Error in Meilisearch id_exists for document: {id} Error: {apiExe}")
            raise apiExe  # noqa
        except Exception as exe:
            log_exception(f"Error in Meilisearch id_exists for document: {id} Error: {exe}")
            raise exe  # noqa

    def insert(self, documents: list[Document], filters: Optional[dict[str, Any]] = None) -> None:
        """Insert documents into the index."""
        docs = []
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = self._clean_content(document.content)
            content_hash = md5(cleaned_content.encode()).hexdigest()
            current_time = int(time.time() * 1000)
            doc = {
                "id": document.id,
                "name": document.name,
                "content": document.content,
                "_vectors": {"content_embedding": document.embedding},
                "meta_data": document.meta_data,
                "filters": filters,
                "usage": document.usage,
                "content_hash": content_hash,
                "create_time": current_time,
                "update_time": current_time,
            }
            docs.append(doc)

        task_info = self.client.index(self.index_name).add_documents(docs)
        if not self.wait_for_task(task_info):
            raise MeiliSearchOperationError(f"Failed to insert documents into index {self.index_name}")

    async def async_insert(self, documents: list[Document], filters: Optional[dict[str, Any]] = None) -> None:
        await asyncio.to_thread(self.insert, documents, filters)

    def upsert_available(self) -> bool:
        return True

    def upsert(self, documents: list[Document], filters: Optional[dict[str, Any]] = None) -> None:
        docs = []
        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = self._clean_content(document.content)
            content_hash = md5(cleaned_content.encode()).hexdigest()
            current_time = int(time.time() * 1000)
            doc = {
                "id": document.id,
                "name": document.name,
                "content": document.content,
                "_vectors": {"content_embedding": document.embedding},
                "meta_data": document.meta_data,
                "filters": filters,
                "usage": document.usage,
                "content_hash": content_hash,
                "update_time": current_time,
            }
            docs.append(doc)

        task_info = self.client.index(self.index_name).update_documents(docs)
        if not self.wait_for_task(task_info):
            raise MeiliSearchOperationError(f"Failed to upsert documents into index {self.index_name}")

    async def async_upsert(self, documents: list[Document], filters: Optional[dict[str, Any]] = None) -> None:
        await asyncio.to_thread(self.upsert, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[dict[str, Any]] = None) -> list[Document]:
        if self.search_type == SearchType.vector:
            return self.vector_search(query=query, limit=limit, filters=filters)
        elif self.search_type == SearchType.keyword:
            return self.keyword_search(query=query, limit=limit, filters=filters)
        elif self.search_type == SearchType.hybrid:
            return self.hybrid_search(query=query, limit=limit, filters=filters)
        else:
            log_error(f"Invalid search type '{self.search_type}'.")
            return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[dict[str, Any]] = None
    ) -> list[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters)

    def vector_search(self, query: str, limit: int = 5, filters: Optional[dict[str, Any]] = None) -> list[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Failed to generate embedding for query: '{query}'")
                return []
            opt_params = {
                "limit": limit,
                "vector": query_embedding,
                "hybrid": {"embedder": "content_embedding"},
                "retrieveVectors": True,
            }
            if self.rankingScoreThreshold:
                opt_params["rankingScoreThreshold"] = self.rankingScoreThreshold
            if filters is not None:
                opt_params["filter"] = self._convert_filter_to_string(filters)
            results = self.client.index(self.index_name).search(query="", opt_params=opt_params)
            docs = self._convert_to_document(results)
            if self.reranker:
                docs = self.reranker.rerank(query=query, documents=docs)
            return docs
        except Exception as e:
            log_exception(f"Error in Meilisearch vector_search for Query: {query} Error: {e}")
            return []

    def keyword_search(self, query: str, limit: int = 5, filters: Optional[dict[str, Any]] = None) -> list[Document]:
        """
        Perform a keyword search on the 'content' column.

        Args:
            query (str): The search query.
            limit (int): Maximum number of results to return.
            filters (Optional[dict[str, Any]]): Filters to apply to the search.

        Returns:
            list[Document]: list of matching documents.
        """
        try:
            opt_params: dict[str, Any] = {"limit": limit, "retrieveVectors": True}
            if self.rankingScoreThreshold:
                opt_params["rankingScoreThreshold"] = self.rankingScoreThreshold
            if filters:
                opt_params["filter"] = self._convert_filter_to_string(filters)
            results = self.client.index(self.index_name).search(query=query, opt_params=opt_params)
            return self._convert_to_document(results)
        except Exception as e:
            log_exception(f"Error in Meilisearch keyword_search for Query: {query} Error: {e}")
        return []

    def hybrid_search(self, query: str, limit: int = 5, filters: Optional[dict[str, Any]] = None) -> list[Document]:
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                log_error(f"Failed to generate embedding for query: '{query}'")
                return []

            opt_params = {
                "limit": limit,
                "vector": query_embedding,
                "hybrid": {"embedder": "content_embedding", "semanticRatio": self.__semanticRatio},
                "retrieveVectors": True,
            }
            if self.rankingScoreThreshold:
                opt_params["rankingScoreThreshold"] = self.rankingScoreThreshold
            if filters is not None:
                opt_params["filter"] = self._convert_filter_to_string(filters)
            results = self.client.index(self.index_name).search(query=query, opt_params=opt_params)
            docs = self._convert_to_document(results)
            if self.reranker:
                docs = self.reranker.rerank(query=query, documents=docs)
            return docs
        except Exception as e:
            log_exception(f"Error in Meilisearch hybrid_search for Query: {query} Error: {e}")
            return []

    def drop(self) -> None:
        """Drop the index."""
        if self.exists():
            task_info = self.client.delete_index(self.index_name)
            if not self.wait_for_task(task_info):
                log_error(f"Failed to delete index '{self.index_name}', task_id: {task_info.task_uid}")
                raise MeiliSearchOperationError(f"Failed to delete index '{self.index_name}'")
            log_info(f"Successfully deleted index '{self.index_name}'")
        else:
            log_info(f"Index '{self.index_name}' does not exist, nothing to delete")

    async def async_drop(self) -> None:
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        try:
            return self.client.get_index(self.index_name) is not None
        except MeilisearchApiError as apiExe:
            if apiExe.code == "index_not_found":
                return False
            log_exception(f"Error in Meilisearch exists for Index: {self.index_name} Error: {apiExe}")
            raise apiExe  # noqa
        except Exception as exe:
            log_exception(f"Error in Meilisearch exists for Index: {self.index_name} Error: {exe}")
            raise exe  # noqa

    async def async_exists(self) -> bool:
        return await asyncio.to_thread(self.exists)

    def optimize(self) -> None:
        pass

    def delete(self) -> bool:
        task_info = self.client.index(self.index_name).delete_all_documents()
        if not self.wait_for_task(task_info):
            log_error(f"Failed to delete all documents from index '{self.index_name}', task_id: {task_info.task_uid}")
            return False
        log_info(f"Successfully deleted all documents from index '{self.index_name}'")
        return True

    def _clean_content(self, content: str) -> str:
        """
        Clean the content by replacing null characters.

        Args:
            content (str): The content to clean.

        Returns:
            str: The cleaned content.
        """
        return content.replace("\x00", "\ufffd")

    def _convert_to_document(self, response: dict[str, Any]) -> list[Document]:
        """
        Convert a MeiliSearch search response to Document instances.

        Args:
            response (dict[str, Any]): The search response from MeiliSearch containing 'hits'.

        Returns:
            list[Document]: A list of converted Document instances.
        """
        documents = []
        for doc_data in response.get("hits", []):
            embedding: Optional[list[float]] = None
            if "_vectors" in doc_data:
                embedding = doc_data["_vectors"]["content_embedding"]["embeddings"]
            document = Document(
                id=doc_data["id"],
                name=doc_data["name"],
                content=doc_data["content"],
                meta_data=doc_data.get("meta_data", {}),
                embedding=embedding,
                embedder=self.embedder,
                usage=doc_data.get("usage"),
            )
            documents.append(document)
        return documents

    def _convert_filter_to_string(self, filters: Optional[dict[str, Any]] = None) -> Optional[str]:
        """
        Convert a dictionary of filters to a MeiliSearch-compatible filter string.

        Args:
            filters (Optional[dict[str, Any]]): Dictionary of filters to convert.

        Returns:
            Optional[str]: MeiliSearch filter string or None if no filters are provided.
        """
        if not filters:
            return None
        filter_conditions = []
        for key, value in filters.items():
            filter_conditions.append(f"filters.{key} = {value}")
        return " AND ".join(filter_conditions)


class MeiliSearchOperationError(Exception):
    """Custom exception for MeiliSearch operations."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return str(self.message)
