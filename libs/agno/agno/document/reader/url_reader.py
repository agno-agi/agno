import asyncio
from time import sleep
from typing import List
from urllib.parse import urlparse

import httpx

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import log_debug, log_info, logger


class URLReader(Reader):
    """Reader for general URL content"""

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        log_info(f"Reading: {url}")
        # Retry the request up to 3 times with exponential backoff
        for attempt in range(3):
            try:
                response = httpx.get(url)
                break
            except httpx.RequestError as e:
                if attempt == 2:  # Last attempt
                    logger.error(f"Failed to fetch URL after 3 attempts: {e}")
                    raise
                wait_time = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                logger.warning(f"Request failed, retrying in {wait_time} seconds...")
                sleep(wait_time)

        try:
            log_debug(f"Status: {response.status_code}")
            log_debug(f"Content size: {len(response.content)} bytes")
        except Exception:
            pass

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            raise

        document = self._create_document(url, response.text)
        if self.chunk:
            return self.chunk_document(document)
        return [document]

    async def async_read(self, url: str) -> List[Document]:
        """Async version of read method"""
        if not url:
            raise ValueError("No url provided")

        log_info(f"Reading async: {url}")
        async with httpx.AsyncClient() as client:
            for attempt in range(3):
                try:
                    response = await client.get(url)
                    break
                except httpx.RequestError as e:
                    if attempt == 2:  # Last attempt
                        logger.error(f"Failed to fetch URL after 3 attempts: {e}")
                        raise
                    wait_time = 2**attempt
                    logger.warning(f"Request failed, retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)

            try:
                log_debug(f"Status: {response.status_code}")
                log_debug(f"Content size: {len(response.content)} bytes")
            except Exception:
                pass

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
                raise

            document = self._create_document(url, response.text)
            if self.chunk:
                return await self.chunk_documents_async([document])
            return [document]

    def _create_document(self, url: str, content: str) -> Document:
        """Helper method to create a document from URL content"""
        parsed_url = urlparse(url)
        doc_name = parsed_url.path.strip("/").replace("/", "_").replace(" ", "_")
        if not doc_name:
            doc_name = parsed_url.netloc

        return Document(
            name=doc_name,
            id=doc_name,
            meta_data={"url": url},
            content=content,
        )
