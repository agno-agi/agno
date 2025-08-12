import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from valyu import Valyu
except ImportError:
    raise ImportError("`valyu` not installed. Please install using `pip install valyu`")


class ValyuTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        text_length: int = 1000,
        max_results: int = 10,
        relevance_threshold: float = 0.5,
        content_category: Optional[str] = None,
        search_start_date: Optional[str] = None,
        search_end_date: Optional[str] = None,
        search_domains: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        max_price: float = 30.0,
        tool_call_mode: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("VALYU_API_KEY")
        if not self.api_key:
            raise ValueError("VALYU_API_KEY not set. Please set the VALYU_API_KEY environment variable.")

        self.valyu = Valyu(api_key=self.api_key)
        self.text_length = text_length
        self.max_results = max_results
        self.relevance_threshold = relevance_threshold
        self.max_price = max_price
        self.content_category = content_category
        self.search_start_date = search_start_date
        self.search_end_date = search_end_date
        self.search_domains = search_domains
        self.sources = sources
        self.tool_call_mode = tool_call_mode

        super().__init__(
            name="valyu_search",
            tools=[self.search_academic_sources, self.search_web, self.search_within_paper],
            **kwargs,
        )

    def _parse_results(self, results: List[Any]) -> str:
        parsed_results = []
        for result in results:
            result_dict = {}

            # Essential fields
            if hasattr(result, "url") and result.url:
                result_dict["url"] = result.url
            if hasattr(result, "title") and result.title:
                result_dict["title"] = result.title
            if hasattr(result, "source") and result.source:
                result_dict["source"] = result.source
            if hasattr(result, "relevance_score"):
                result_dict["relevance_score"] = result.relevance_score

            # Content with length limiting
            if hasattr(result, "content") and result.content:
                content = result.content
                if self.text_length and len(content) > self.text_length:
                    content = content[: self.text_length] + "..."
                result_dict["content"] = content

            # Additional metadata
            if hasattr(result, "description") and result.description:
                result_dict["description"] = result.description

            parsed_results.append(result_dict)

        return json.dumps(parsed_results, indent=2)

    def _valyu_search(
        self,
        query: str,
        search_type: str,
        content_category: Optional[str] = None,
        sources: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        try:
            search_params = {
                "query": query,
                "search_type": search_type,
                "max_num_results": self.max_results,
                "is_tool_call": self.tool_call_mode,
                "relevance_threshold": self.relevance_threshold,
                "max_price": self.max_price,
            }

            # Add optional parameters
            if sources or self.sources:
                search_params["included_sources"] = sources or self.sources
            if content_category or self.content_category:
                search_params["category"] = content_category or self.content_category
            if start_date or self.search_start_date:
                search_params["start_date"] = start_date or self.search_start_date
            if end_date or self.search_end_date:
                search_params["end_date"] = end_date or self.search_end_date

            log_debug(f"Valyu search parameters: {search_params}")
            response = self.valyu.search(**search_params)

            if not response.success:
                log_error(f"Valyu search API error: {response.error}")
                return f"Error: {response.error or 'Search request failed'}"

            return self._parse_results(response.results or [])

        except Exception as e:
            error_msg = f"Valyu search failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def search_academic_sources(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Search academic sources (ArXiv, PubMed, academic publishers).

        Args:
            query: Research question or topic
            start_date: Filter papers after this date (YYYY-MM-DD)
            end_date: Filter papers before this date (YYYY-MM-DD)

        Returns:
            JSON array of academic papers
        """
        sources = ["valyu/valyu-arxiv", "valyu/valyu-pubmed", "wiley/wiley-finance-papers", "wiley/wiley-finance-books"]

        return self._valyu_search(
            query=query,
            search_type="proprietary",
            sources=sources,
            start_date=start_date,
            end_date=end_date,
        )

    def search_web(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        content_category: Optional[str] = None,
    ) -> str:
        """Search web sources for real-time information.

        Args:
            query: Search query
            start_date: Filter content after this date (YYYY-MM-DD)
            end_date: Filter content before this date (YYYY-MM-DD)
            content_category: Description of the category of the query

        Returns:
            JSON array of web search results
        """
        return self._valyu_search(
            query=query,
            search_type="web",
            content_category=content_category,
            start_date=start_date,
            end_date=end_date,
        )

    def search_within_paper(
        self,
        paper_url: str,
        query: str,
    ) -> str:
        """Search within a specific ArXiv paper.

        Args:
            paper_url: ArXiv paper URL
            query: Search query
        Returns:
            JSON array of relevant sections from the paper
        """
        # Validate ArXiv URL
        if not paper_url.startswith("https:/"):
            log_warning(f"Invalid paper URL: {paper_url}")
            return "Error: Invalid paper URL format"

        return self._valyu_search(
            query=query,
            search_type="proprietary",
            sources=[paper_url],
        )
