from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_debug, logger
from agno.vectordb.base import VectorDb


class LangChainVectorDb(VectorDb):
    def __init__(
        self,
        vectorstore: Optional[Any] = None,
        search_kwargs: Optional[dict] = None,
        knowledge_retriever: Optional[Any] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        """
        Initialize LangChainVectorDb.

        Args:
            vectorstore: The LangChain vectorstore instance
            name (Optional[str]): Name of the vector database.
            description (Optional[str]): Description of the vector database.
            search_kwargs: Additional search parameters for the retriever
            knowledge_retriever: An optional LangChain retriever instance
        """
        self.vectorstore = vectorstore
        # Initialize base class with name and description
        super().__init__(name=name, description=description)

        self.search_kwargs = search_kwargs
        self.knowledge_retriever = knowledge_retriever

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

    def delete_by_content_id(self, content_id: str) -> None:
        raise NotImplementedError

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.warning("LangChainKnowledgeBase.insert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        logger.warning("LangChainKnowledgeBase.async_insert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.warning("LangChainKnowledgeBase.upsert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        logger.warning("LangChainKnowledgeBase.async_upsert() not supported - please check the vectorstore manually.")
        raise NotImplementedError

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Returns relevant documents matching the query"""

        try:
            from langchain_core.documents import Document as LangChainDocument
            from langchain_core.retrievers import BaseRetriever
        except ImportError:
            raise ImportError(
                "The `langchain` package is not installed. Please install it via `pip install langchain`."
            )

        if self.vectorstore is not None and self.knowledge_retriever is None:
            log_debug("Creating knowledge retriever")
            if self.search_kwargs is None:
                self.search_kwargs = {"k": limit}
            if filters is not None:
                self.search_kwargs.update(filters)
            self.knowledge_retriever = self.vectorstore.as_retriever(search_kwargs=self.search_kwargs)

        if self.knowledge_retriever is None:
            logger.error("No knowledge retriever provided")
            return []

        if not isinstance(self.knowledge_retriever, BaseRetriever):
            raise ValueError(f"Knowledge retriever is not of type BaseRetriever: {self.knowledge_retriever}")

        log_debug(f"Getting {limit} relevant documents for query: {query}")
        lc_documents: List[LangChainDocument] = self.knowledge_retriever.invoke(input=query)
        documents = []
        for lc_doc in lc_documents:
            documents.append(
                Document(
                    content=lc_doc.page_content,
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
        logger.warning("LangChainKnowledgeBase.exists() not supported - please check the vectorstore manually.")
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.
        Not implemented for LangChain wrapper.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        raise NotImplementedError("update_metadata not supported for LangChain vectorstores")

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # LangChainVectorDb doesn't use SearchType enum
