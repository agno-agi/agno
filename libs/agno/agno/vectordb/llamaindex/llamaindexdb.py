from typing import Any, Callable, Dict, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import logger
from agno.vectordb.base import VectorDb

try:
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore
except ImportError:
    raise ImportError(
        "The `llama-index-core` package is not installed. Please install it via `pip install llama-index-core`."
    )


class LlamaIndexVectorDb(VectorDb):
    knowledge_retriever: BaseRetriever
    loader: Optional[Callable] = None

    def __init__(
        self,
        knowledge_retriever: BaseRetriever,
        loader: Optional[Callable] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        # Initialize base class with name and description
        super().__init__(name=name, description=description)

        self.knowledge_retriever = knowledge_retriever
        self.loader = loader

    def create(self) -> None:
        raise NotImplementedError

    async def async_create(self) -> None:
        raise NotImplementedError

    def name_exists(self, name: str) -> bool:
        raise NotImplementedError

    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError

    def id_exists(self, id: str) -> bool:
        raise NotImplementedError

    def content_hash_exists(self, content_hash: str) -> bool:
        raise NotImplementedError

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.warning("LlamaIndexVectorDb.insert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        logger.warning("LlamaIndexVectorDb.async_insert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.warning("LlamaIndexVectorDb.upsert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.warning("LlamaIndexVectorDb.async_upsert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Returns relevant documents matching the query.

        Args:
            query (str): The query string to search for.
            limit (int): The maximum number of documents to return. Defaults to 5.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search. Defaults to None.

        Returns:
            List[Document]: A list of relevant documents matching the query.
        Raises:
            ValueError: If the knowledge retriever is not of type BaseRetriever.
        """
        if not isinstance(self.knowledge_retriever, BaseRetriever):
            raise ValueError(f"Knowledge retriever is not of type BaseRetriever: {self.knowledge_retriever}")

        lc_documents: List[NodeWithScore] = self.knowledge_retriever.retrieve(query)
        if limit is not None:
            lc_documents = lc_documents[:limit]
        documents = []
        for lc_doc in lc_documents:
            documents.append(
                Document(
                    content=lc_doc.text,
                    meta_data=lc_doc.metadata,
                )
            )
        return documents

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        return self.search(query, limit, filters)

    def drop(self) -> None:
        raise NotImplementedError

    async def async_drop(self) -> None:
        raise NotImplementedError

    async def async_exists(self) -> bool:
        raise NotImplementedError

    def delete(self) -> bool:
        raise NotImplementedError

    def delete_by_id(self, id: str) -> bool:
        raise NotImplementedError

    def delete_by_name(self, name: str) -> bool:
        raise NotImplementedError

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def exists(self) -> bool:
        logger.warning("LlamaIndexKnowledgeBase.exists() not supported - please check the vectorstore manually.")
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.
        Not implemented for LlamaIndex wrapper.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        raise NotImplementedError("update_metadata not supported for LlamaIndex vectorstores")

    def delete_by_content_id(self, content_id: str) -> bool:
        """
        Delete documents by content ID.
        Not implemented for LlamaIndex wrapper.

        Args:
            content_id (str): The content ID to delete

        Returns:
            bool: False as this operation is not supported
        """
        logger.warning(
            "LlamaIndexVectorDb.delete_by_content_id() not supported - please check the vectorstore manually."
        )
        return False

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # LlamaIndexVectorDb doesn't use SearchType enum
