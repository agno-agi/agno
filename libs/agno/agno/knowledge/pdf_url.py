from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from agno.document import Document
from agno.document.reader.pdf_reader import PDFUrlImageReader, PDFUrlReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_info, logger


class PDFUrlKnowledgeBase(AgentKnowledge):
    urls: Optional[Union[List[str], List[Dict[str, Dict[str, Any]]]]] = None
    formats: List[str] = [".pdf"]
    reader: Union[PDFUrlReader, PDFUrlImageReader] = PDFUrlReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDF urls and yield lists of documents."""
        if not self.urls:
            raise ValueError("URLs are not set")

        for item in self.urls:
            if isinstance(item, dict):
                # Handle URL with metadata
                for url, config in item.items():
                    if self._is_valid_url(url):
                        documents = self.reader.read(url=url)
                        # Add metadata to documents if provided
                        if config.get("metadata"):
                            for doc in documents:
                                log_info(f"Adding metadata {config.get('metadata')} to document from URL: {url}")
                                doc.meta_data.update(config["metadata"])
                        yield documents
            else:
                # Handle simple URL
                if self._is_valid_url(item):
                    yield self.reader.read(url=item)

    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        if not url.endswith(".pdf"):
            logger.error(f"Unsupported URL: {url}")
            return False
        return True

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDF urls and yield lists of documents asynchronously."""
        if not self.urls:
            raise ValueError("URLs are not set")

        for item in self.urls:
            if isinstance(item, dict):
                # Handle URL with metadata
                for url, config in item.items():
                    if self._is_valid_url(url):
                        documents = await self.reader.async_read(url=url)
                        # Add metadata to documents if provided
                        if config.get("metadata"):
                            for doc in documents:
                                log_info(f"Adding metadata {config.get('metadata')} to document from URL: {url}")
                                doc.meta_data.update(config["metadata"])
                        yield documents
            else:
                # Handle simple URL
                if self._is_valid_url(item):
                    yield await self.reader.async_read(url=item)
