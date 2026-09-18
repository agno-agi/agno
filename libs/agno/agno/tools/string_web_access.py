import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

DEFAULT_BASE_URL = "https://request.usestring.ai/v1"


class StringWebAccessTools(Toolkit):
    """
    String Web Access gives an agent the live web: search, fetch any URL as clean Markdown, and
    extract structured data from a page. Proxy rotation, anti-bot handling, CAPTCHA solving and
    JavaScript rendering happen server-side, so a rate-limited, geo-gated or bot-blocked page comes
    back as content rather than a block screen.

    Get an API key at https://usestring.ai and set it as STRING_API_KEY.

    Args:
        api_key (Optional[str]): String API key. Defaults to the STRING_API_KEY environment variable.
        enable_search (bool): Enable web search. Default is True.
        enable_fetch (bool): Enable URL fetching. Default is True.
        enable_extract (bool): Enable schema-guided extraction from a page. Default is False.
        all (bool): Enable all tools. Overrides the individual flags when True. Default is False.
        engine (str): Search engine — google, duckduckgo, brave, mojeek or bing. Default is google.
        country (str): ISO 3166-1 alpha-2 country used to localize search results. Default is US.
        markdown_mode (str): Markdown preservation level, "full" or "readable". Default is "full".
        main_content_only (bool): Strip page chrome from fetched Markdown. Default is False.
        execute_js (bool): Render the page in a browser before capturing it. Default is False.
        country_code (Optional[str]): ISO 3166-1 alpha-2 country for the fetch proxy exit IP.
        max_content_length (Optional[int]): Truncate returned page content to this many characters.
        timeout (int): HTTP timeout in seconds. Default is 120.
        base_url (str): API base URL. Default is https://request.usestring.ai/v1.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        enable_fetch: bool = True,
        enable_extract: bool = False,
        all: bool = False,
        engine: str = "google",
        country: str = "US",
        markdown_mode: str = "full",
        main_content_only: bool = False,
        execute_js: bool = False,
        country_code: Optional[str] = None,
        max_content_length: Optional[int] = None,
        timeout: int = 120,
        base_url: str = DEFAULT_BASE_URL,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("STRING_API_KEY")
        if not self.api_key:
            log_error("STRING_API_KEY not set. Please set the STRING_API_KEY environment variable.")

        self.engine: str = engine
        self.country: str = country
        self.markdown_mode: str = markdown_mode
        self.main_content_only: bool = main_content_only
        self.execute_js: bool = execute_js
        self.country_code: Optional[str] = country_code
        self.max_content_length: Optional[int] = max_content_length
        self.timeout: int = timeout
        self.base_url: str = base_url.rstrip("/")

        tools: List[Any] = []
        if all or enable_search:
            tools.append(self.search_web)
        if all or enable_fetch:
            tools.append(self.fetch_url)
        if all or enable_extract:
            tools.append(self.extract_from_url)

        super().__init__(name="string_web_access_tools", tools=tools, **kwargs)

    def search_web(self, query: str, max_results: int = 10) -> str:
        """Search the web and return the organic results as JSON.

        Args:
            query (str): The search query to run.
            max_results (int): Maximum number of organic results to return. Default is 10.

        Returns:
            str: JSON list of results, each with position, title, url, displayUrl and snippet.
        """
        payload: Dict[str, Any] = {"query": query, "engine": self.engine, "country": self.country}

        log_debug(f"Searching String Web Access for: {query}")
        body = self._post("/search", payload)
        if isinstance(body, str):
            return body

        results = body.get("results", [])[:max_results]
        if not results:
            return f"No results found for '{query}'."
        return json.dumps(results, indent=2)

    def fetch_url(self, url: str) -> str:
        """Fetch a URL and return the page as clean, LLM-ready Markdown.

        Works on sites that rate-limit, geo-gate or block automated traffic: proxy rotation,
        anti-bot handling, CAPTCHA solving and JavaScript rendering are handled server-side.

        Args:
            url (str): The http/https URL to fetch.

        Returns:
            str: The page as Markdown.
        """
        payload: Dict[str, Any] = {
            "url": url,
            "format": "markdown",
            "markdownMode": self.markdown_mode,
            "mainContentOnly": self.main_content_only,
        }
        if self.execute_js:
            payload["executeJS"] = True
        if self.country_code:
            payload["countryCode"] = self.country_code

        log_debug(f"Fetching {url} through String Web Access")
        content = self._post("/fetch", payload, expect_json=False)
        return self._truncate(content)

    def extract_from_url(self, url: str, json_schema: Dict[str, Any]) -> str:
        """Fetch a URL and extract structured data from it against a JSON Schema.

        Args:
            url (str): The http/https URL to fetch.
            json_schema (Dict[str, Any]): JSON Schema describing the object to extract.

        Returns:
            str: The extracted object as JSON. If extraction was not possible, the response
                carries "extracted": false and a machine-readable "reason".
        """
        payload: Dict[str, Any] = {"url": url, "format": "json", "jsonSchema": json_schema}
        if self.execute_js:
            payload["executeJS"] = True
        if self.country_code:
            payload["countryCode"] = self.country_code

        log_debug(f"Extracting structured data from {url} through String Web Access")
        body = self._post("/fetch", payload)
        if isinstance(body, str):
            return body
        return self._truncate(json.dumps(body, indent=2))

    def _post(self, path: str, payload: Dict[str, Any], expect_json: bool = True) -> Any:
        if not self.api_key:
            return "STRING_API_KEY not set. Please set the STRING_API_KEY environment variable."

        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json() if expect_json else response.text
        except Exception as e:
            error_msg = f"Error calling String Web Access {path}: {e}"
            log_error(error_msg)
            return error_msg

    def _truncate(self, content: str) -> str:
        if self.max_content_length is None or len(content) <= self.max_content_length:
            return content
        return content[: self.max_content_length] + "..."
