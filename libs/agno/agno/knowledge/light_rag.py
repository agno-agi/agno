from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Union

import textract
from pydantic import Field

from agno.document import Document
from agno.document.reader.markdown_reader import MarkdownReader
from agno.document.reader.pdf_reader import PDFUrlReader
from agno.document.reader.url_reader import URLReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_debug, log_info, logger


class LightRagKnowledgeBase(AgentKnowledge):
    """LightRAG-based knowledge base for document processing and retrieval."""

    # Constants
    DEFAULT_SERVER_URL: ClassVar[str] = "http://localhost:9621"
    SUPPORTED_EXTENSIONS: ClassVar[List[str]] = [".pdf", ".md", ".txt"]

    lightrag_server_url: str = DEFAULT_SERVER_URL
    path: Optional[Union[str, Path, List[Dict[str, Union[str, Dict[str, Any]]]]]] = None
    urls: Optional[Union[List[str], List[Dict[str, Union[str, Dict[str, Any]]]]]] = None
    exclude_files: List[str] = Field(default_factory=list)

    pdf_url_reader: PDFUrlReader = PDFUrlReader()
    markdown_reader: MarkdownReader = MarkdownReader()
    url_reader: URLReader = URLReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over documents and yield lists of Document objects."""
        # Convert text lists to Document objects to match parent class signature
        for text_list in self._text_document_lists():
            documents = [Document(content=text) for text in text_list]
            yield documents

    def _text_document_lists(self) -> Iterator[List[str]]:
        """Internal method to iterate over documents and yield lists of text content."""
        if self.path is not None:
            yield from self._process_paths()

        if self.urls is not None:
            yield from self._process_urls()

        if self.urls is None and self.path is None:
            raise ValueError("Path or URLs are not set")

    def _process_paths(self) -> Iterator[List[str]]:
        """Process path-based documents."""
        if self.path is None:
            return

        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict) and "path" in item:
                    path_value = item["path"]
                    if isinstance(path_value, (str, Path)):
                        yield from self._process_single_path(Path(path_value))
        else:
            yield from self._process_single_path(Path(self.path))

    def _process_single_path(self, path: Path) -> Iterator[List[str]]:
        """Process a single path (file or directory)."""
        if path.is_dir():
            for file_path in path.glob("**/*"):
                if file_path.is_file():
                    text_str = textract.process(str(file_path)).decode("utf-8")
                    yield [text_str]
        elif path.exists() and path.is_file():
            if path.suffix == ".md":
                documents = self.markdown_reader.read(file=path)
                text_contents = [doc.content for doc in documents]
                yield text_contents
            elif path.suffix == ".pdf":
                text_str = textract.process(str(path)).decode("utf-8")
                yield [text_str]
            else:
                text_str = textract.process(str(path)).decode("utf-8")
                yield [text_str]

    def _process_urls(self) -> Iterator[List[str]]:
        """Process URL-based documents."""
        if self.urls is None:
            return

        log_info(f"Processing URLs: {self.urls}")
        for item in self.urls:
            if isinstance(item, dict) and "url" in item:
                url = item["url"]
                config = item.get("metadata", {})
                if isinstance(url, str) and isinstance(config, dict):
                    yield from self._process_url_with_metadata(url, config)
            elif isinstance(item, str):
                yield from self._process_simple_url(item)

    def _process_url_with_metadata(self, url: str, config: Dict[str, Any]) -> Iterator[List[str]]:
        """Process URL with metadata configuration."""
        log_debug(f"Processing URL with metadata - URL: {url}, Config: {config}")
        if self._is_valid_url(url):
            if url.endswith(".pdf"):
                log_info(f"READING PDF URL: {url}")
                documents = self.pdf_url_reader.read(url=url)
                text_contents = [doc.content for doc in documents]
                yield text_contents
            else:
                log_debug(f"URL is valid, reading documents from: {url}")
                documents = self.url_reader.read(url=url)
                text_contents = []
                for doc in documents:
                    if config:
                        log_debug(f"Adding metadata {config} to document from URL: {url}")
                        doc.meta_data.update(config)
                    text_contents.append(doc.content)
                yield text_contents

    def _process_simple_url(self, url: str) -> Iterator[List[str]]:
        """Process a simple URL without metadata."""
        log_info(f"Processing simple URL: {url}")
        if self._is_valid_url(url):
            log_info(f"Simple URL is valid, reading documents from: {url}")
            if url.endswith(".pdf"):
                documents = self.pdf_url_reader.read(url=url)
                text_contents = [doc.content for doc in documents]
                yield text_contents
            else:
                documents = self.url_reader.read(url=url)
                text_contents = [doc.content for doc in documents]
                yield text_contents

    async def load(
        self,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load the knowledge base to the LightRAG server asynchronously.

        Note: The LightRAG implementation is inherently async.
        """
        logger.debug("Loading LightRagKnowledgeBase")
        for text_list in self._text_document_lists():
            for text in text_list:
                await self._insert_text(text)

    async def aload(
        self,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load all documents into the LightRAG server asynchronously."""
        # Delegate to load() since both are async for LightRAG
        await self.load(recreate=recreate, upsert=upsert, skip_existing=skip_existing)

    async def load_text(
        self, text: str, upsert: bool = False, skip_existing: bool = True, filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Load a single text into the LightRAG server asynchronously."""
        await self._insert_text(text)

    async def async_search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Override the async_search method from AgentKnowledge to query the LightRAG server."""
        import httpx

        logger.info(f"Querying LightRAG server with query: {query}")
        mode = "hybrid"  # Default mode, can be "local", "global", or "hybrid"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.lightrag_server_url}/query",
                json={"query": query, "mode": mode},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Query result: {result}")

            # Convert result to Document objects to match parent class signature
            if isinstance(result, dict) and "response" in result:
                return [Document(content=result["response"], meta_data={"query": query, "mode": mode})]
            elif isinstance(result, list):
                return [Document(content=str(item), meta_data={"query": query, "mode": mode}) for item in result]
            else:
                return [Document(content=str(result), meta_data={"query": query, "mode": mode})]

    async def _insert_text(self, text: str) -> Dict[str, Any]:
        """Insert text into the LightRAG server."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.lightrag_server_url}/documents/text",
                json={"text": text},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            logger.debug(f"Text insertion result: {result}")
            return result

    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        if not any(url.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS):
            logger.error(f"Unsupported URL: {url}. Supported file types: {', '.join(self.SUPPORTED_EXTENSIONS)}")
            return False
        return True


async def lightrag_retriever(
    query: str,
    num_documents: int = 5,
    mode: str = "hybrid",  # Default mode, can be "local", "global", or "hybrid"
    lightrag_server_url: str = "http://localhost:9621",
) -> Optional[List[Dict[str, Any]]]:
    """
    Custom retriever function to search the LightRAG server for relevant documents.

    Args:
        query: The search query string
        num_documents: Number of documents to retrieve (currently unused by LightRAG)
        mode: Query mode - "local", "global", or "hybrid"
        lightrag_server_url: URL of the LightRAG server

    Returns:
        List of retrieved documents or None if search fails
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{lightrag_server_url}/query",
                json={"query": query, "mode": mode},
                headers={"Content-Type": "application/json"},
            )

            response.raise_for_status()
            result = response.json()

            return _format_lightrag_response(result, query, mode)

    except httpx.RequestError as e:
        logger.error(f"HTTP Request Error: {type(e).__name__}: {str(e)}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during LightRAG server search: {type(e).__name__}: {str(e)}")
        import traceback

        logger.error(f"Full traceback: {traceback.format_exc()}")
        return None


def _format_lightrag_response(result: Any, query: str, mode: str) -> List[Dict[str, Any]]:
    """Format LightRAG server response to expected document format."""
    # LightRAG server returns a dict with 'response' key, but we expect a list of documents
    # Convert the response to the expected format
    if isinstance(result, dict) and "response" in result:
        # Wrap the response in a document-like structure
        return [{"content": result["response"], "source": "lightrag", "metadata": {"query": query, "mode": mode}}]
    elif isinstance(result, list):
        return result
    else:
        # If it's a string or other format, wrap it
        return [{"content": str(result), "source": "lightrag", "metadata": {"query": query, "mode": mode}}]
