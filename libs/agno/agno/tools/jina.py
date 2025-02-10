from os import getenv
from typing import Dict, Optional

import httpx
from pydantic import BaseModel, Field, HttpUrl

from agno.tools import Toolkit
from agno.utils.log import logger


class JinaReaderToolsConfig(BaseModel):
    api_key: Optional[str] = Field(None, description="API key for Jina Reader")
    base_url: HttpUrl = Field("https://r.jina.ai/", description="Base URL for Jina Reader API")  # type: ignore
    search_url: HttpUrl = Field("https://s.jina.ai/", description="Search URL for Jina Reader API")  # type: ignore
    max_content_length: int = Field(10000, description="Maximum content length in characters")
    timeout: Optional[int] = Field(None, description="Timeout for Jina Reader API requests")


class JinaReaderTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = getenv("JINA_API_KEY"),
        base_url: str = "https://r.jina.ai/",
        search_url: str = "https://s.jina.ai/",
        max_content_length: int = 10000,
        timeout: Optional[int] = None,
        read_url: bool = True,
        search_query: bool = False,
    ):
        super().__init__(name="jina_reader_tools")

        self.config: JinaReaderToolsConfig = JinaReaderToolsConfig(
            api_key=api_key,
            base_url=base_url,
            search_url=search_url,
            max_content_length=max_content_length,
            timeout=timeout,
        )

        if read_url:
            self.register(self.read_url)
        if search_query:
            self.register(self.search_query)

    def read_url(self, url: str) -> str:
        """Reads a URL and returns the truncated content using Jina Reader API."""
        full_url = f"{self.config.base_url}{url}"
        logger.info(f"Reading URL: {full_url}")
        try:
            response = httpx.get(full_url, headers=self._get_headers())
            response.raise_for_status()
            content = response.json()
            return self._truncate_content(str(content))
        except Exception as e:
            error_msg = f"Error reading URL: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def search_query(self, query: str) -> str:
        """Performs a web search using Jina Reader API and returns the truncated results."""
        full_url = f"{self.config.search_url}{query}"
        logger.info(f"Performing search: {full_url}")
        try:
            response = httpx.get(full_url, headers=self._get_headers())
            response.raise_for_status()
            content = response.json()
            return self._truncate_content(str(content))
        except Exception as e:
            error_msg = f"Error performing search: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-With-Links-Summary": "true",
            "X-With-Images-Summary": "true",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.timeout:
            headers["X-Timeout"] = str(self.config.timeout)

        return headers

    def _truncate_content(self, content: str) -> str:
        """Truncate content to the maximum allowed length."""
        if len(content) > self.config.max_content_length:
            truncated = content[: self.config.max_content_length]
            return truncated + "... (content truncated)"
        return content
