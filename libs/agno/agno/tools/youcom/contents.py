import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

DEFAULT_BASE_URL = "https://ydc-index.io"


class YouContentsTools(Toolkit):
    """
    YouContentsTools exposes the You.com Contents API as a first-class Agno tool.

    The Contents API returns the raw content (HTML, Markdown) and metadata
    (site name, favicon) of specified target webpages.

    Get an API key at https://you.com/platform/api-keys and set ``YDC_API_KEY``.

    Reference: https://you.com/docs/api-reference/contents

    Args:
        api_key (Optional[str]): You.com API key. Falls back to the ``YDC_API_KEY`` env var.
        base_url (Optional[str]): Override the API base URL. Falls back to the ``YDC_BASE_URL``
            env var, then defaults to ``https://ydc-index.io``.
        formats (Optional[List[str]]): List of formats to fetch. Allowed values: ``html``,
            ``markdown``, ``metadata``. Defaults to ``["markdown", "metadata"]``.
        crawl_timeout (int): Maximum time in seconds to wait for page content. Must be
            between 1 and 60 seconds. Default is 10 seconds.
        max_age (Optional[int]): Maximum allowed age of cached content in seconds.
            Must be 0 or greater. Defaults to None (no age limit).
        text_length_limit (Optional[int]): Max characters to keep per page content.
            Defaults to None (no truncation).
        timeout (int): Client-side HTTP timeout in seconds. Default is 15.
        format (str): Output format for the agent (``"json"`` or ``"markdown"``).
            Default is ``"json"``.
        show_results (bool): Log the full response for debugging. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        formats: Optional[List[Literal["html", "markdown", "metadata"]]] = None,
        crawl_timeout: int = 10,
        max_age: Optional[int] = None,
        text_length_limit: Optional[int] = None,
        timeout: int = 15,
        format: Literal["json", "markdown"] = "json",
        show_results: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("YDC_API_KEY")
        if not self.api_key:
            log_error("YDC_API_KEY not set. Please set the YDC_API_KEY environment variable.")

        if not (1 <= crawl_timeout <= 60):
            raise ValueError("crawl_timeout must be between 1 and 60 seconds")

        if max_age is not None and max_age < 0:
            raise ValueError("max_age must be 0 or greater")

        self.base_url: str = (base_url or getenv("YDC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.formats: List[str] = [str(f) for f in formats] if formats else ["markdown", "metadata"]
        self.crawl_timeout: int = crawl_timeout
        self.max_age: Optional[int] = max_age
        self.text_length_limit: Optional[int] = text_length_limit
        self.timeout: int = timeout
        self.format: str = format
        self.show_results: bool = show_results

        super().__init__(name="youcom_contents", tools=[self.you_contents], **kwargs)

    def you_contents(
        self,
        urls: Union[str, List[str]],
        crawl_timeout: Optional[int] = None,
        max_age: Optional[int] = None,
    ) -> str:
        """
        Fetches the content of web pages using the You.com Contents API.

        Args:
            urls (Union[str, List[str]]): The URL or list of URLs to fetch the content from.
            crawl_timeout (Optional[int]): Per-call override for maximum time to wait for page content.
            max_age (Optional[int]): Per-call override for maximum allowed age of cached content.

        Returns:
            str: The fetched page content and metadata, formatted as JSON or Markdown.
        """
        logger.debug(f"Fetching contents for: {urls}")

        effective_crawl_timeout = crawl_timeout if crawl_timeout is not None else self.crawl_timeout
        effective_max_age = max_age if max_age is not None else self.max_age

        if not (1 <= effective_crawl_timeout <= 60):
            return "Error: crawl_timeout must be between 1 and 60 seconds"

        if effective_max_age is not None and effective_max_age < 0:
            return "Error: max_age must be 0 or greater"

       
        url_list = [urls] if isinstance(urls, str) else urls

        payload: Dict[str, Any] = {
            "urls": url_list,
            "formats": self.formats,
            "crawl_timeout": effective_crawl_timeout,
        }
        if effective_max_age is not None:
            payload["max_age"] = effective_max_age

        headers = {
            "X-API-Key": self.api_key or "",
            "Content-Type": "application/json",
        }

        try:
            # Ensure the HTTP client timeout is always slightly larger than the crawl_timeout
            # so the client doesn't drop the connection before the API finishes crawling.
            request_timeout = max(self.timeout, effective_crawl_timeout + 5)

            with httpx.Client(timeout=request_timeout) as client:
                response = client.post(
                    f"{self.base_url}/v1/contents",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                if self.show_results:
                    log_info(f"You.com contents response: {json.dumps(data, indent=2)}")

                return self._format_results(data)
        except httpx.HTTPError as e:
            error_msg = f"Failed to run You.com contents fetch: {e}"
            log_error(error_msg)
            # Try to extract detailed error message from response body if available
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_data = e.response.json()
                    return f"Error: {error_data.get('detail', error_msg)}"
                except Exception:
                    pass
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"Failed to run You.com contents fetch: {e}"
            log_error(error_msg)
            return f"Error: {e}"

    def _truncate(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        if self.text_length_limit and len(text) > self.text_length_limit:
            return text[: self.text_length_limit]
        return text

    def _format_results(self, data: List[Dict[str, Any]]) -> str:
        """
        Parses the top-level flat array returned by the API and formats it for the agent.
        """
        if not data:
            return "No contents found."

        if self.format == "json":
            return json.dumps(data, indent=2)

        # Markdown format
        markdown_blocks = []
        for page in data:
            title = page.get("title", "Untitled")
            url = page.get("url", "")
            markdown = self._truncate(page.get("markdown"))
            html = self._truncate(page.get("html"))

            block = f"### [{title}]({url})\n"
            if markdown:
                block += f"\n**Content (Markdown)**:\n{markdown}\n"
            elif html:
                block += f"\n**Content (HTML)**:\n{html}\n"
            else:
                block += "\n*No content available.*\n"

            metadata = page.get("metadata")
            if metadata:
                site_name = metadata.get("site_name")
                favicon_url = metadata.get("favicon_url")

                if site_name:
                    block += f"\n**Site Name**: {site_name}"
                if favicon_url:
                    block += f"\n**Favicon URL**: {favicon_url}"

            markdown_blocks.append(block)

        return "\n---\n".join(markdown_blocks)
