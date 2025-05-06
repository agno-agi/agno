from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from agno.document import Document
from agno.document.reader.pdf_reader import PDFUrlImageReader, PDFUrlReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_info, logger


class PDFUrlKnowledgeBase(AgentKnowledge):
    urls: Optional[Union[List[str], List[Dict[str, Union[str, Dict[str, Any]]]]]] = None
    formats: List[str] = [".pdf"]
    reader: Union[PDFUrlReader, PDFUrlImageReader] = PDFUrlReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDF URLs and yield lists of documents."""
        if not self.urls:
            raise ValueError("URLs are not set")

        for item in self.urls:
            if isinstance(item, dict) and "url" in item:
                # Handle URL with metadata
                url = item["url"]
                config = item.get("metadata", {})
                if self._is_valid_url(url):  # type: ignore
                    documents = self.reader.read(url=url)  # type: ignore
                    if config:
                        for doc in documents:
                            log_info(f"Adding metadata {config} to document from URL: {url}")
                            doc.meta_data.update(config)  # type: ignore
                    yield documents
            else:
                # Handle simple URL
                if self._is_valid_url(item):  # type: ignore
                    yield self.reader.read(url=item)  # type: ignore

    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        if not url.endswith(".pdf"):
            logger.error(f"Unsupported URL: {url}")
            return False
        return True

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDF URLs and yield lists of documents asynchronously."""
        if not self.urls:
            raise ValueError("URLs are not set")

        for item in self.urls:
            if isinstance(item, dict) and "url" in item:
                # Handle URL with metadata
                url = item["url"]
                config = item.get("metadata", {})
                if self._is_valid_url(url):  # type: ignore
                    documents = await self.reader.async_read(url=url)  # type: ignore
                    if config:
                        for doc in documents:
                            log_info(f"Adding metadata {config} to document from URL: {url}")
                            doc.meta_data.update(config)  # type: ignore
                    yield documents
            else:
                # Handle simple URL
                if self._is_valid_url(item):  # type: ignore
                    yield await self.reader.async_read(url=item)  # type: ignore
