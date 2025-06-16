from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from agno.document import Document
from agno.document.reader.csv_reader import CSVUrlReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_info, logger


class CSVUrlKnowledgeBase(AgentKnowledge):
    urls: Optional[Union[List[str], List[Dict[str, Union[str, Dict[str, Any]]]]]] = None
    formats: List[str] = [".csv"]
    reader: CSVUrlReader = CSVUrlReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over CSV URLs and yield lists of documents."""
        if self.urls is None:
            raise ValueError("URLs are not set")

        for item in self.urls:
            if isinstance(item, dict) and "url" in item:
                # Handle URL with metadata
                url = item["url"]
                if isinstance(url, str):  # Type guard
                    config = item.get("metadata", {})
                    if self._is_valid_csv_url(url):
                        documents = self.reader.read(url=url)
                        if config and isinstance(config, dict):
                            for doc in documents:
                                log_info(f"Adding metadata {config} to document: {doc.name}")
                                doc.meta_data.update(config)  # type: ignore
                        yield documents
            elif isinstance(item, str):
                # Handle plain URL string
                if self._is_valid_csv_url(item):
                    yield self.reader.read(url=item)

    def _is_valid_csv_url(self, url: str) -> bool:
        """Helper to check if URL is a valid CSV URL."""
        return url.endswith(".csv")

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over CSV URLs and yield lists of documents asynchronously."""
        if self.urls is None:
            raise ValueError("URLs are not set")

        for item in self.urls:
            if isinstance(item, dict) and "url" in item:
                # Handle URL with metadata
                url = item["url"]
                if isinstance(url, str):  # Type guard
                    config = item.get("metadata", {})
                    if self._is_valid_csv_url(url):
                        documents = await self.reader.async_read(url=url)
                        if config and isinstance(config, dict):
                            for doc in documents:
                                log_info(f"Adding metadata {config} to document: {doc.name}")
                                doc.meta_data.update(config)  # type: ignore
                        yield documents
            elif isinstance(item, str):
                # Handle plain URL string
                if self._is_valid_csv_url(item):
                    yield await self.reader.async_read(url=item)

    def load_document(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load documents from a single CSV URL with specific metadata into the vector DB."""

        # Validate URL and prepare collection in one step
        if not self.prepare_load(url, self.formats, metadata, recreate, is_url=True):  # type: ignore
            return

        # Read documents
        try:
            documents = self.reader.read(url=url)
        except Exception as e:
            logger.exception(f"Failed to read documents from URL {url}: {e}")
            return

        # Process documents
        self.process_documents(
            documents=documents,
            metadata=metadata,
            upsert=upsert,
            skip_existing=skip_existing,
            source_info=url,
        )

    async def aload_document(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load documents from a single CSV URL with specific metadata into the vector DB."""

        # Validate URL and prepare collection in one step
        if not await self.aprepare_load(url, self.formats, metadata, recreate, is_url=True):  # type: ignore
            return

        # Read documents
        try:
            documents = await self.reader.async_read(url=url)
        except Exception as e:
            logger.exception(f"Failed to read documents from URL {url}: {e}")
            return

        # Process documents
        await self.aprocess_documents(
            documents=documents,
            metadata=metadata,
            upsert=upsert,
            skip_existing=skip_existing,
            source_info=url,
        )
