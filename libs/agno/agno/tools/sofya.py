import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

# Sofya's fetch endpoint is documented as "1 credit per URL, max 10 URLs" per
# https://sofya.co/docs — enforce it client-side to give a clean error instead
# of an opaque 400 from the API.
FETCH_MAX_URLS = 10


class SofyaTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_search: bool = True,
        enable_extract: bool = False,
        enable_research: bool = False,
        all: bool = False,
        max_results: int = 5,
        search_depth: Literal["snippets", "basic"] = "basic",
        include_answer: bool = True,
        format: Literal["json", "markdown"] = "markdown",
        timeout: int = 180,
        **kwargs,
    ):
        """Initialize SofyaTools with search, extract, and research capabilities.

        Sofya (https://sofya.co) is a web tools API for AI agents. Search returns
        extracted page content instead of snippets, extract fetches URLs as clean
        markdown, and research returns a cited multi-source report.

        Args:
            api_key: Sofya API key. If not provided, will use SOFYA_API_KEY env var.
            base_url: Sofya API base URL. If not provided, will use SOFYA_BASE_URL env var. Defaults to https://sofya.co.
            enable_search: Enable web search functionality. Defaults to True.
            enable_extract: Enable URL content extraction functionality. Defaults to False.
            enable_research: Enable multi-source deep research functionality. Defaults to False.
            all: Enable all available tools. Defaults to False.
            max_results: Maximum number of search results to return (1-20). Defaults to 5.
            search_depth: Search depth - snippets (1 credit) or basic (3 credits, full content). Defaults to "basic".
            include_answer: Include an AI-generated answer in search results. Defaults to True.
            format: Output format for search and research results - json or markdown. Defaults to "markdown".
            timeout: Request timeout in seconds. Defaults to 180.
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.api_key: Optional[str] = api_key or getenv("SOFYA_API_KEY")
        if not self.api_key:
            log_error("SOFYA_API_KEY not provided")
        self.base_url: str = (base_url or getenv("SOFYA_BASE_URL") or "https://sofya.co").rstrip("/")
        self.max_results: int = max_results
        self.search_depth: Literal["snippets", "basic"] = search_depth
        self.include_answer: bool = include_answer
        self.format: Literal["json", "markdown"] = format
        self.timeout: int = timeout

        tools: List[Any] = []
        if enable_search or all:
            tools.append(self.search_web)
        if enable_extract or all:
            tools.append(self.extract_url_content)
        if enable_research or all:
            tools.append(self.research)

        super().__init__(name="sofya_tools", tools=tools, **kwargs)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST to the Sofya API and return the parsed JSON response.

        On HTTP errors, re-raises with the response body appended (truncated),
        so callers see the Sofya-side error message instead of just the status.
        """
        url = f"{self.base_url}/v1/{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "agno-sofya",
        }
        log_debug(f"Calling Sofya {path}")
        response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            body = (response.text or "")[:500]
            raise requests.HTTPError(f"{e} - body: {body}", response=response) from e
        return response.json()

    def search_web(self, query: str, max_results: Optional[int] = None) -> str:
        """Search the web with Sofya and get extracted page content, not just snippets.

        Args:
            query (str): Query to search for.
            max_results (Optional[int]): Maximum number of results to return. Defaults to the configured value.

        Returns:
            str: Search results as markdown or a JSON string.
        """
        if not self.api_key:
            return json.dumps({"error": "Please provide a Sofya API key"})
        if not query or not query.strip():
            return json.dumps({"error": "Please provide a query to search for"})

        payload = {
            "query": query.strip(),
            "max_results": max(1, min(max_results or self.max_results, 20)),
            "search_depth": self.search_depth,
            "include_answer": self.include_answer,
        }

        try:
            data = self._post("search", payload)
        except Exception as e:
            log_error(f"Sofya search failed: {e}")
            return json.dumps({"error": str(e)})

        clean: Dict[str, Any] = {"query": query}
        if data.get("answer"):
            clean["answer"] = data["answer"]
        clean["results"] = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "published_date": r.get("published_date"),
            }
            for r in data.get("results", [])
        ]

        if self.format == "json":
            return json.dumps(clean)

        markdown = f"# {query}\n\n"
        if "answer" in clean:
            markdown += f"### Summary\n{clean['answer']}\n\n"
        for r in clean["results"]:
            url = r.get("url") or ""
            title = r.get("title") or url or "Untitled"
            content = r.get("content") or ""
            markdown += f"### [{title}]({url})\n{content}\n\n"
        return markdown

    def extract_url_content(self, urls: str) -> str:
        """Fetch one or more URLs as clean markdown using Sofya. Also handles PDF, DOCX, and more.

        Sofya's fetch endpoint accepts up to 10 URLs per call; extra URLs are dropped
        client-side to avoid an opaque API error.

        Args:
            urls (str): Single URL or multiple comma-separated URLs to fetch.
                Example: "https://example.com" or "https://example.com,https://another.com"

        Returns:
            str: Extracted content as markdown, with one section per URL.
        """
        if not self.api_key:
            return json.dumps({"error": "Please provide a Sofya API key"})

        url_list = [u.strip() for u in urls.split(",") if u.strip()]
        if not url_list:
            return json.dumps({"error": "No valid URLs provided"})
        if len(url_list) > FETCH_MAX_URLS:
            log_debug(f"Sofya fetch capped at {FETCH_MAX_URLS} URLs; dropping {len(url_list) - FETCH_MAX_URLS}")
            url_list = url_list[:FETCH_MAX_URLS]

        try:
            data = self._post("fetch", {"urls": url_list})
        except Exception as e:
            log_error(f"Sofya extract failed: {e}")
            return json.dumps({"error": str(e)})

        results = data.get("results", [])
        if not results:
            return "No content could be extracted from the provided URL(s)."

        output = []
        for r in results:
            url = r.get("url", "Unknown URL")
            if not r.get("success", True):
                output.append(f"## {url}\n\n**Extraction failed**: {r.get('error', 'unknown error')}\n\n")
            elif r.get("content"):
                output.append(f"## {url}\n\n{r['content']}\n\n")
            else:
                output.append(f"## {url}\n\n*No content available*\n\n")
        return "".join(output)

    def research(self, query: str) -> str:
        """Run multi-source deep research with Sofya and get back a cited report.

        Sofya decomposes the question into sub-queries, reads many sources in parallel,
        and synthesizes a single report with citations. Use this for open-ended questions
        that need several sources, not for a single lookup (use search_web for that).

        Args:
            query (str): The research question.

        Returns:
            str: The research report as markdown, or a JSON string.
        """
        if not self.api_key:
            return json.dumps({"error": "Please provide a Sofya API key"})
        if not query or not query.strip():
            return json.dumps({"error": "Please provide a query to research"})

        try:
            data = self._post("research", {"query": query.strip()})
        except Exception as e:
            log_error(f"Sofya research failed: {e}")
            return json.dumps({"error": str(e)})

        if self.format == "json":
            return json.dumps(data)

        report = data.get("report", "")
        markdown = f"# {query}\n\n{report}\n\n"
        sources = data.get("sources", [])
        if sources:
            markdown += "## Sources\n"
            for s in sources:
                if isinstance(s, dict):
                    markdown += f"- [{s.get('title', s.get('url'))}]({s.get('url')})\n"
                else:
                    markdown += f"- {s}\n"
        return markdown
