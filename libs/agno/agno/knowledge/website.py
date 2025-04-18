import asyncio
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from pydantic import model_validator

from agno.document import Document
from agno.document.reader.website_reader import WebsiteReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_debug, log_info, logger


class WebsiteKnowledgeBase(AgentKnowledge):
    urls: List[str] = []
    reader: Optional[WebsiteReader] = None

    # WebsiteReader parameters
    max_depth: int = 3
    max_links: int = 10

    @model_validator(mode="after")
    def set_reader(self) -> "WebsiteKnowledgeBase":
        if self.reader is None:
            self.reader = WebsiteReader(
                max_depth=self.max_depth, max_links=self.max_links, chunking_strategy=self.chunking_strategy
            )
        return self

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        if self.reader is not None:
            for _url in self.urls:
                yield self.reader.read(url=_url)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Asynchronously iterate over urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: AsyncIterator yielding list of documents
        """
        if self.reader is not None:
            for _url in self.urls:
                yield await self.reader.async_read(url=_url)

    def load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load the website contents to the vector db"""

        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if self.reader is None:
            logger.warning("No reader provided")
            return

        if recreate:
            log_debug("Dropping collection")
            self.vector_db.drop()

        log_debug("Creating collection")
        self.vector_db.create()

        log_info("Loading knowledge base")
        num_documents = 0

        # Given that the crawler needs to parse the URL before existence can be checked
        # We check if the website url exists in the vector db if recreate is False
        urls_to_read = self.urls.copy()
        if not recreate:
            for url in urls_to_read:
                log_debug(f"Checking if {url} exists in the vector db")
                if self.vector_db.name_exists(name=url):
                    log_debug(f"Skipping {url} as it exists in the vector db")
                    urls_to_read.remove(url)

        for url in urls_to_read:
            if document_list := self.reader.read(url=url):
                # Filter out documents which already exist in the vector db
                if not recreate:
                    document_list = [document for document in document_list if not self.vector_db.doc_exists(document)]
                if upsert and self.vector_db.upsert_available():
                    self.vector_db.upsert(documents=document_list, filters=filters)
                else:
                    self.vector_db.insert(documents=document_list, filters=filters)
                num_documents += len(document_list)
                log_info(f"Loaded {num_documents} documents to knowledge base")

        if self.optimize_on is not None and num_documents > self.optimize_on:
            log_debug("Optimizing Vector DB")
            self.vector_db.optimize()

    async def async_load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Asynchronously load the website contents to the vector db"""

        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if self.reader is None:
            logger.warning("No reader provided")
            return

        vector_db = self.vector_db
        reader = self.reader

        if recreate:
            log_debug("Dropping collection asynchronously")
            await vector_db.async_drop()

        log_debug("Creating collection asynchronously")
        await vector_db.async_create()

        log_info("Loading knowledge base asynchronously")
        num_documents = 0

        urls_to_read = self.urls.copy()
        if not recreate:
            for url in urls_to_read[:]:
                log_debug(f"Checking if {url} exists in the vector db")
                name_exists = vector_db.async_name_exists(name=url)
                if name_exists:
                    log_debug(f"Skipping {url} as it exists in the vector db")
                    urls_to_read.remove(url)

        async def process_url(url: str) -> List[Document]:
            try:
                document_list = await reader.async_read(url=url)

                if not recreate:
                    filtered_documents = []
                    for document in document_list:
                        if not await vector_db.async_doc_exists(document):
                            filtered_documents.append(document)
                    document_list = filtered_documents

                return document_list
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}")
                return []

        url_tasks = [process_url(url) for url in urls_to_read]
        all_document_lists = await asyncio.gather(*url_tasks)

        for document_list in all_document_lists:
            if document_list:
                if upsert and vector_db.upsert_available():
                    await vector_db.async_upsert(documents=document_list, filters=filters)
                else:
                    await vector_db.async_insert(documents=document_list, filters=filters)
                num_documents += len(document_list)
                log_info(f"Loaded {num_documents} documents to knowledge base asynchronously")

        if self.optimize_on is not None and num_documents > self.optimize_on:
            log_debug("Optimizing Vector DB")
            vector_db.optimize()
