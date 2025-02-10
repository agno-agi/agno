from typing import Any, Callable, Dict, List, Optional

from agno.document import Document
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import logger

try:
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore
except ImportError:
    raise ImportError(
        "The `llama-index-core` package is not installed. Please install it via `pip install llama-index-core`."
    )


class LlamaIndexKnowledgeBase(AgentKnowledge):
    retriever: BaseRetriever
    loader: Optional[Callable] = None

    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Returns relevant documents matching the query.

        Args:
            query (str): The query string to search for.
            num_documents (Optional[int]): The maximum number of documents to return. Defaults to None.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search. Defaults to None.

        Returns:
            List[Document]: A list of relevant documents matching the query.
        Raises:
            ValueError: If the retriever is not of type BaseRetriever.
        """
        if not isinstance(self.retriever, BaseRetriever):
            raise ValueError(f"Retriever is not of type BaseRetriever: {self.retriever}")

        lc_documents: List[NodeWithScore] = self.retriever.retrieve(query)
        if num_documents is not None:
            lc_documents = lc_documents[:num_documents]
        documents = []
        for lc_doc in lc_documents:
            documents.append(
                Document(
                    content=lc_doc.text,
                    meta_data=lc_doc.metadata,
                )
            )
        return documents

    def load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.loader is None:
            logger.error("No loader provided for LlamaIndexKnowledgeBase")
            return
        self.loader()

    def exists(self) -> bool:
        logger.warning("LlamaIndexKnowledgeBase.exists() not supported - please check the vectorstore manually.")
        return True
