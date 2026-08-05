import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, logger

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class PerplexitySearch(Toolkit):
    """
    PerplexitySearch is a toolkit for the Perplexity Search API,
    providing raw ranked web search results with filtering and
    content extraction.

    Args:
        api_key: Perplexity API key. Falls back to PERPLEXITY_API_KEY env var.
        max_results: Default number of results per query. Default 5.
        max_tokens_per_page: Max tokens of content per result page. Default 2048.
        search_recency_filter: Filter by recency ('day', 'week', 'month', 'year').
        search_domain_filter: Restrict/exclude domains. List of domains.
        search_language_filter: Filter by language. List of ISO codes.
        show_results: Log results for debugging. Default False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 5,
        max_tokens_per_page: int = 2048,
        search_recency_filter: Optional[str] = None,
        search_domain_filter: Optional[List[str]] = None,
        search_language_filter: Optional[List[str]] = None,
        show_results: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("PERPLEXITY_API_KEY")
        if not self.api_key:
            log_error("PERPLEXITY_API_KEY not set. Please set the PERPLEXITY_API_KEY environment variable.")

        self.base_url = "https://api.perplexity.ai"
        self.max_results = max_results
        self.max_tokens_per_page = max_tokens_per_page
        self.search_recency_filter = search_recency_filter
        self.search_domain_filter = search_domain_filter
        self.search_language_filter = search_language_filter
        self.show_results = show_results

        super().__init__(
            name="perplexity_search",
            tools=[self.search],
            async_tools=[(self.asearch, "search")],
            **kwargs,
        )

    def search(self, query: str, max_results: Optional[int] = None) -> str:
        """Use this function to search the web using the Perplexity Search API.
        Returns ranked web search results with titles, URLs, snippets, and dates.

        Args:
            query (str): The search query.
            max_results (int, optional): Number of results to return. Defaults to instance setting.

        Returns:
            str: JSON string of search results with url, title, snippet, and date fields.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Source": "agno",
        }

        body: Dict[str, Any] = {
            "query": query,
            "max_results": max_results or self.max_results,
            "max_tokens_per_page": self.max_tokens_per_page,
        }
        if self.search_recency_filter:
            body["search_recency_filter"] = self.search_recency_filter
        if self.search_domain_filter:
            body["search_domain_filter"] = self.search_domain_filter
        if self.search_language_filter:
            body["search_language_filter"] = self.search_language_filter

        try:
            response = httpx.post(
                f"{self.base_url}/search",
                headers=headers,
                json=body,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for r in data.get("results", []):
                result_dict: Dict[str, str] = {"url": r.get("url", "")}
                if r.get("title"):
                    result_dict["title"] = r["title"]
                if r.get("snippet"):
                    result_dict["snippet"] = r["snippet"]
                if r.get("date"):
                    result_dict["date"] = r["date"]
                results.append(result_dict)

            parsed = json.dumps(results, indent=4, ensure_ascii=False)
            if self.show_results:
                logger.info(parsed)
            return parsed

        except Exception as e:
            logger.exception("Perplexity search failed")
            return json.dumps({"error": str(e)})

    async def asearch(self, query: str, max_results: Optional[int] = None) -> str:
        """Use this function to search the web using the Perplexity Search API.
        Returns ranked web search results with titles, URLs, snippets, and dates.

        Args:
            query (str): The search query.
            max_results (int, optional): Number of results to return. Defaults to instance setting.

        Returns:
            str: JSON string of search results with url, title, snippet, and date fields.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Source": "agno",
        }

        body: Dict[str, Any] = {
            "query": query,
            "max_results": max_results or self.max_results,
            "max_tokens_per_page": self.max_tokens_per_page,
        }
        if self.search_recency_filter:
            body["search_recency_filter"] = self.search_recency_filter
        if self.search_domain_filter:
            body["search_domain_filter"] = self.search_domain_filter
        if self.search_language_filter:
            body["search_language_filter"] = self.search_language_filter

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    headers=headers,
                    json=body,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

            results = []
            for r in data.get("results", []):
                result_dict: Dict[str, str] = {"url": r.get("url", "")}
                if r.get("title"):
                    result_dict["title"] = r["title"]
                if r.get("snippet"):
                    result_dict["snippet"] = r["snippet"]
                if r.get("date"):
                    result_dict["date"] = r["date"]
                results.append(result_dict)

            parsed = json.dumps(results, indent=4, ensure_ascii=False)
            if self.show_results:
                logger.info(parsed)
            return parsed

        except Exception as e:
            logger.exception("Perplexity search failed")
            return json.dumps({"error": str(e)})
