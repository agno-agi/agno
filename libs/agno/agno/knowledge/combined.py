from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from agno.document import Document
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_debug, log_error, log_info, logger
from agno.vectordb import VectorDb


class CombinedKnowledgeBase(AgentKnowledge):
    """
    CombinedKnowledgeBase aggregates multiple knowledge bases into a single source.
    It allows for searching across all included knowledge bases and provides.
    The priority sources will set the priority for the knowledge base, the higher the priority,
    the higher the result ranking.
    The priority sources takes effect only when the create_table parameter is False.
    When the create_table is false, a new data table is no longer created, but the settings in each knowledge base are used.
    priority sources be like:
    [
        {
            "source": AgentKnowledge,
            "priority": 0.5  # Optional, default is 0.0
        }
    ]
    Priority suggestion setting range 0～1
    """

    sources: List[Union[AgentKnowledge, Dict[str, Union[AgentKnowledge, float]]]] = []
    create_table: bool = True
    # In the agent's running function, there is a check for whether the knowledge base has db,
    # so VectorDB is used here as a placeholder.
    vector_db: Optional[VectorDb] = VectorDb  # type: ignore

    def _get_sources(self) -> List[AgentKnowledge]:
        """Returns the list of knowledge bases."""
        sources: List[AgentKnowledge] = []
        for source in self.sources:
            if isinstance(source, AgentKnowledge):
                sources.append(source)
            elif isinstance(source, dict) and "source" in source:
                kb = source["source"]
                if isinstance(kb, AgentKnowledge):
                    sources.append(kb)
                else:
                    log_error(f"Invalid source type: {type(kb)}")
            else:
                log_error("Source must be an AgentKnowledge instance or a dictionary with 'source' key")
        return sources

    def _get_priority_sources(self) -> List[Dict[str, Union[AgentKnowledge, float]]]:
        """Returns the priority sources."""
        priority_sources: List[Dict[str, Union[AgentKnowledge, float]]] = []
        for source in self.sources:
            if isinstance(source, dict) and "source" in source:
                kb = source["source"]
                if not isinstance(kb, AgentKnowledge):
                    log_error(f"Invalid source type: {type(kb)}")
                else:
                    if "priority" not in source:
                        source["priority"] = 0.0
                    priority_sources.append(source)
            elif isinstance(source, AgentKnowledge):
                priority_sources.append({"source": source, "priority": 0.0})
            else:
                log_error("Source must be an AgentKnowledge instance or a dictionary with 'source' key")
        return priority_sources

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over knowledge bases and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for kb in self._get_sources():
            log_debug(f"Loading documents from {kb.__class__.__name__}")
            yield from kb.document_lists

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over knowledge bases and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for kb in self._get_sources():
            log_debug(f"Loading documents from {kb.__class__.__name__}")
            async for document in kb.async_document_lists:  # type: ignore
                yield document

    def _load_init(self, recreate: bool, upsert: bool) -> None:
        if self.create_table:
            super()._load_init(recreate=recreate, upsert=upsert)

    async def _aload_init(self, recreate: bool, upsert: bool) -> None:
        if self.create_table:
            await super()._aload_init(recreate=recreate, upsert=upsert)

    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            _num_documents = num_documents or self.num_documents
            log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
            priority_results: List[Document] = []
            if self.create_table:
                if self.vector_db is None:
                    logger.warning("No vector db provided")
                    return []
                return self.vector_db.search(query=query, limit=_num_documents, filters=filters)
            priority_sources = self._get_priority_sources()
            for source in priority_sources:
                kb = source["source"]
                raw_priority = source.get("priority", 0.0)
                priority = raw_priority if isinstance(raw_priority, float) else 0.0
                if not isinstance(kb, AgentKnowledge):
                    log_error(f"Invalid source type: {type(kb)}")
                    continue
                log_debug(f"Searching in knowledge base: {kb.__class__.__name__}")
                results = kb.search(query=query, num_documents=_num_documents, filters=filters)
                if results:
                    for doc in results:
                        if doc.reranking_score is None:
                            doc.priority_score = priority
                        else:
                            doc.priority_score = doc.reranking_score + doc.reranking_score * priority
                        priority_results.append(doc)
            priority_results.sort(
                key=lambda x: x.priority_score if x.priority_score is not None else float("-inf"),
                reverse=True,
            )
            if _num_documents:
                priority_results = priority_results[:_num_documents]
            return priority_results

        except Exception as e:
            logger.error(f"Error searching for documents: {e}")
            return []

    async def async_search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            _num_documents = num_documents or self.num_documents
            log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
            priority_results: List[Document] = []
            if self.create_table:
                if self.vector_db is None:
                    logger.warning("No vector db provided")
                    return []
                try:
                    return await self.vector_db.async_search(query=query, limit=_num_documents, filters=filters)
                except NotImplementedError:
                    log_info("Vector db does not support async search")
                    return self.search(query=query, num_documents=_num_documents, filters=filters)
            priority_sources = self._get_priority_sources()
            for source in priority_sources:
                kb = source["source"]
                raw_priority = source.get("priority", 0.0)
                priority = raw_priority if isinstance(raw_priority, float) else 0.0
                if not isinstance(kb, AgentKnowledge):
                    log_error(f"Invalid source type: {type(kb)}")
                    continue
                log_debug(f"Searching in knowledge base: {kb.__class__.__name__}")
                results = await kb.async_search(query=query, num_documents=_num_documents, filters=filters)
                if results:
                    for doc in results:
                        if doc.reranking_score is None:
                            doc.priority_score = priority
                        else:
                            doc.priority_score = doc.reranking_score + doc.reranking_score * priority
                        priority_results.append(doc)
            priority_results.sort(
                key=lambda x: x.priority_score if x.priority_score is not None else float("-inf"),
                reverse=True,
            )
            if _num_documents:
                priority_results = priority_results[:_num_documents]
            return priority_results

        except Exception as e:
            logger.error(f"Error searching for documents: {e}")
            return []

    def load(
        self,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        if self.create_table:
            super().load(recreate=recreate, upsert=upsert, skip_existing=skip_existing)
        else:
            log_debug("Skipping table creation as create_table is set to False")
            for kb in self._get_sources():
                log_debug(f"Loading knowledge base: {kb.__class__.__name__}")
                kb.load(recreate=recreate, upsert=upsert, skip_existing=skip_existing)

    async def aload(
        self,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        if self.create_table:
            await super().aload(recreate=recreate, upsert=upsert, skip_existing=skip_existing)
        else:
            log_debug("Skipping table creation as create_table is set to False")
            for kb in self._get_sources():
                log_debug(f"Loading knowledge base: {kb.__class__.__name__}")
                await kb.aload(recreate=recreate, upsert=upsert, skip_existing=skip_existing)

    def load_documents(
        self,
        documents: List[Document],
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load documents into the knowledge base."""
        if self.create_table:
            super().load_documents(documents=documents, upsert=upsert, skip_existing=skip_existing, filters=filters)
        else:
            log_error(
                "Cannot load documents because create_table is set to False, loading into individual knowledge bases instead"
            )

    async def async_load_documents(
        self,
        documents: List[Document],
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Asynchronously load documents into the knowledge base."""
        if self.create_table:
            await super().async_load_documents(
                documents=documents, upsert=upsert, skip_existing=skip_existing, filters=filters
            )
        else:
            log_error(
                "Cannot load documents because create_table is set to False, loading into individual knowledge bases instead"
            )

    def exists(self) -> bool:
        """Returns True if the knowledge base exists"""
        if self.create_table:
            if self.vector_db is None:
                logger.warning("No vector db provided")
                return False
            return self.vector_db.exists()
        exist = True
        for kb in self._get_sources():
            log_debug(f"Checking existence in knowledge base: {kb.__class__.__name__}")
            if not kb.exists():
                exist = False
                break
        return exist
