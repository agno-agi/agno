from typing import List
from urllib.parse import urlparse

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger


class URLReader(Reader):
    """Reader for general URL content"""

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        try:
            import httpx
        except ImportError:
            raise ImportError("`httpx` not installed. Please install it via `pip install httpx`.")

        logger.info(f"Reading: {url}")
        response = httpx.get(url)

        try:
            logger.debug(f"Status: {response.status_code}")
            logger.debug(f"Content size: {len(response.content)} bytes")
        except Exception:
            pass

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            raise

        # Create a clean document name from the URL
        parsed_url = urlparse(url)
        doc_name = parsed_url.path.strip("/").replace("/", "_").replace(" ", "_")
        if not doc_name:
            doc_name = parsed_url.netloc

        # Create a single document with the URL content
        document = Document(
            name=doc_name,
            id=doc_name,
            meta_data={"url": url},
            content=response.text,
        )

        if self.chunk:
            return self.chunk_document(document)
        return [document]
