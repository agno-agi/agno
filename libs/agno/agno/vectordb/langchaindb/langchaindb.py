from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_debug, logger
from agno.vectordb.base import VectorDb


class LangChainVectorDb(VectorDb):
    vectorstore: Optional[Any] = None
    search_kwargs: Optional[dict] = None

    retriever: Optional[Any] = None

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

    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching the query"""

        try:
            from langchain_core.documents import Document as LangChainDocument
            from langchain_core.retrievers import BaseRetriever
        except ImportError:
            raise ImportError(
                "The `langchain` package is not installed. Please install it via `pip install langchain`."
            )

        if self.vectorstore is not None and self.retriever is None:
            log_debug("Creating retriever")
            if self.search_kwargs is None:
                self.search_kwargs = {"k": self.num_documents}
            if filters is not None:
                self.search_kwargs.update(filters)
            self.retriever = self.vectorstore.as_retriever(search_kwargs=self.search_kwargs)

        if self.retriever is None:
            logger.error("No retriever provided")
            return []

        if not isinstance(self.retriever, BaseRetriever):
            raise ValueError(f"Retriever is not of type BaseRetriever: {self.retriever}")

        _num_documents = num_documents or self.num_documents
        log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
        lc_documents: List[LangChainDocument] = self.retriever.invoke(input=query)
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
        self.search(query, limit, filters)

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
