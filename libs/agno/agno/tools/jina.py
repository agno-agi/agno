from os import getenv
from typing import Any, Dict, List, Optional

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
    search_query_content: Optional[bool] = Field(False, description="Toggle full URL content in query search result")


class JinaReaderTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = getenv("JINA_API_KEY"),
        base_url: str = "https://r.jina.ai/",
        search_url: str = "https://s.jina.ai/",
        max_content_length: int = 10000,
        timeout: Optional[int] = None,
        search_query_content: bool = True,
        enable_read_url: bool = True,
        enable_search_query: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("JINA_API_KEY")
        self.config: JinaReaderToolsConfig = JinaReaderToolsConfig(
            api_key=self.api_key,
            base_url=base_url,
            search_url=search_url,
            max_content_length=max_content_length,
            timeout=timeout,
            search_query_content=search_query_content,
        )

        tools: List[Any] = []
        if all or enable_read_url:
            tools.append(self.read_url)
        if all or enable_search_query:
            tools.append(self.search_query)

        super().__init__(name="jina_reader_tools", tools=tools, **kwargs)

    def read_url(self, url: str) -> str:
        """Reads a URL and returns the truncated content using Jina Reader API."""
        full_url = f"{self.config.base_url}{url}"
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
        full_url = f"{self.config.search_url}"
        headers = self._get_headers()
        if not self.config.search_query_content:
            headers["X-Respond-With"] = "no-content"  # to avoid returning full content in search results

        body = {"q": query}
        try:
            response = httpx.post(full_url, headers=headers, json=body)
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
