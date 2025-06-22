from os import getenv
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field, HttpUrl

from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class JinaReaderToolsConfig(BaseModel):
    api_key: Optional[str] = Field(None, description="API key for Jina Reader")
    base_url: HttpUrl = Field("https://r.jina.ai/", description="Base URL for Jina Reader API")  # type: ignore
    search_url: HttpUrl = Field("https://s.jina.ai/", description="Search URL for Jina Reader API")  # type: ignore
    max_content_length: int = Field(10000, description="Maximum content length in characters")
    timeout: int = Field(30, description="Timeout for Jina Reader API requests in seconds")


class JinaReaderTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = getenv("JINA_API_KEY"),
        base_url: str = "https://r.jina.ai/",
        search_url: str = "https://s.jina.ai/",
        max_content_length: int = 10000,
        timeout: int = 30,
        read_url: bool = True,
        search_query: bool = False,
        **kwargs,
    ):
        self.config: JinaReaderToolsConfig = JinaReaderToolsConfig(
            api_key=api_key,
            base_url=base_url,
            search_url=search_url,
            max_content_length=max_content_length,
            timeout=timeout,
        )

        tools: List[Any] = []
        if read_url:
            tools.append(self.read_url)
        if search_query:
            tools.append(self.search_query)

        super().__init__(name="jina_reader_tools", tools=tools, **kwargs)

    def read_url(self, url: str) -> str:
        """Reads a URL and returns the truncated content using Jina Reader API.
        Get your Jina AI API key for free: https://jina.ai/?sui=apikey"""
        log_info(f"Reading URL: {url}")
        try:
            with httpx.Client(timeout=self.config.timeout) as client:
                response = client.post(
                    str(self.config.base_url),
                    headers=self._get_reader_headers(),
                    json={"url": url}
                )
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") == 200 and "data" in data:
                    content = data["data"].get("content", "")
                    return self._truncate_content(content)
                else:
                    return f"Error: {data.get('message', 'Unknown error')}"
                    
        except Exception as e:
            error_msg = f"Error reading URL: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def search_query(self, query: str) -> str:
        """Performs a web search using Jina Search API and returns the truncated results.
        Get your Jina AI API key for free: https://jina.ai/?sui=apikey"""
        log_info(f"Performing search: {query}")
        try:
            with httpx.Client(timeout=self.config.timeout) as client:
                response = client.post(
                    str(self.config.search_url),
                    headers=self._get_search_headers(),
                    json={"q": query}
                )
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") == 200 and "data" in data:
                    results = data["data"]
                    formatted_results = []
                    for i, result in enumerate(results[:5]):  # Limit to 5 results
                        title = result.get("title", "")
                        url = result.get("url", "")
                        content = result.get("content", "")[:500]  # Truncate content
                        formatted_results.append(f"{i+1}. {title}\nURL: {url}\nContent: {content}...\n")
                    
                    return self._truncate_content("\n".join(formatted_results))
                else:
                    return f"Error: {data.get('message', 'Unknown error')}"
                    
        except Exception as e:
            error_msg = f"Error performing search: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def _get_reader_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Engine": "direct",  # Use 'direct' for speed, 'browser' for quality
            "X-Timeout": str(self.config.timeout),
            "X-With-Links-Summary": "true",
            "X-Return-Format": "markdown",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _get_search_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json", 
            "Content-Type": "application/json",
            "X-Engine": "direct",  # Use 'direct' for speed
            "X-Timeout": str(self.config.timeout),
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _truncate_content(self, content: str) -> str:
        """Truncate content to the maximum allowed length."""
        if len(content) > self.config.max_content_length:
            truncated = content[: self.config.max_content_length]
            return truncated + "... (content truncated)"
        return content
