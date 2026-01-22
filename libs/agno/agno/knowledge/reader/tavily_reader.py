import asyncio
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, logger

try:
    from tavily import TavilyClient  # type: ignore[attr-defined]
except ImportError:
    raise ImportError(
        "The `tavily-python` package is not installed. Please install it via `pip install tavily-python`."
    )


@dataclass
class TavilyReader(Reader):
    api_key: Optional[str] = None
    params: Optional[Dict] = None
    extract_format: Literal["markdown", "text"] = "markdown"
    extract_depth: Literal["basic", "advanced"] = "basic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        params: Optional[Dict] = None,
        extract_format: Literal["markdown", "text"] = "markdown",
        extract_depth: Literal["basic", "advanced"] = "basic",
        chunk: bool = True,
        chunk_size: int = 5000,
        chunking_strategy: Optional[ChunkingStrategy] = SemanticChunking(),
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """
        Initialize TavilyReader for extracting content from URLs using Tavily's Extract API.

        Args:
            api_key: Tavily API key (or use TAVILY_API_KEY env var)
            params: Additional parameters to pass to the extract API
            extract_format: Output format - "markdown" or "text"
            extract_depth: Extraction depth - "basic" (1 credit/5 URLs) or "advanced" (2 credits/5 URLs)
            chunk: Whether to chunk the extracted content
            chunk_size: Size of chunks when chunking is enabled
            chunking_strategy: Strategy to use for chunking
            name: Name of the reader
            description: Description of the reader
        """
        # Initialize base Reader (handles chunk_size / strategy)
        super().__init__(
            chunk=chunk, chunk_size=chunk_size, chunking_strategy=chunking_strategy, name=name, description=description
        )

        # Tavily-specific attributes
        self.api_key = api_key
        self.params = params or {}
        self.extract_format = extract_format
        self.extract_depth = extract_depth

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Tavily readers."""
        return [
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def _extract(self, url: str, name: Optional[str] = None) -> List[Document]:
        """
        Internal method to extract content from a URL using Tavily's Extract API.

        Args:
            url: The URL to extract content from
            name: Optional name for the document (defaults to URL)

        Returns:
            A list of documents containing the extracted content
        """
        log_debug(f"Extracting content from: {url}")

        client = TavilyClient(api_key=self.api_key)

        # Prepare extract parameters
        extract_params = {
            "urls": [url],
            "depth": self.extract_depth,
        }

        # Add optional params if provided
        if self.params:
            extract_params.update(self.params)

        try:
            # Call Tavily Extract API
            response = client.extract(**extract_params)

            # Extract content from response
            if not response or "results" not in response:
                logger.warning(f"No results received for URL: {url}")
                return [Document(name=name or url, id=url, content="")]

            results = response.get("results", [])
            if not results:
                logger.warning(f"Empty results for URL: {url}")
                return [Document(name=name or url, id=url, content="")]

            # Get the first result (since we're extracting a single URL)
            result = results[0]

            # Check if extraction failed
            if "failed_reason" in result:
                logger.warning(f"Extraction failed for {url}: {result['failed_reason']}")
                return [Document(name=name or url, id=url, content="")]

            # Get raw content
            content = result.get("raw_content", "")

            if content is None:
                content = ""
                logger.warning(f"No content received for URL: {url}")

            # Debug logging
            log_debug(f"Received content type: {type(content)}")
            log_debug(f"Content length: {len(content) if content else 0}")

            # Create documents
            documents = []
            if self.chunk and content:
                documents.extend(self.chunk_document(Document(name=name or url, id=url, content=content)))
            else:
                documents.append(Document(name=name or url, id=url, content=content))
            return documents

        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}")
            return [Document(name=name or url, id=url, content="")]

    async def _async_extract(self, url: str, name: Optional[str] = None) -> List[Document]:
        """
        Internal async method to extract content from a URL.

        Args:
            url: The URL to extract content from
            name: Optional name for the document

        Returns:
            A list of documents containing the extracted content
        """
        log_debug(f"Async extracting content from: {url}")

        # Use asyncio.to_thread to run the synchronous extract in a thread
        return await asyncio.to_thread(self._extract, url, name)

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
        """
        Reads content from a URL using Tavily Extract API.

        This is the public API method that users should call.

        Args:
            url: The URL to extract content from
            name: Optional name for the document

        Returns:
            A list of documents containing the extracted content
        """
        return self._extract(url, name)

    async def async_read(self, url: str, name: Optional[str] = None) -> List[Document]:
        """
        Asynchronously reads content from a URL using Tavily Extract API.

        This is the public API method that users should call for async operations.

        Args:
            url: The URL to extract content from
            name: Optional name for the document

        Returns:
            A list of documents containing the extracted content
        """
        return await self._async_extract(url, name)
