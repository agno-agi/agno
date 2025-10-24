import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from tavily import TavilyClient
except ImportError:
    raise ImportError("`tavily-python` not installed. Please install using `pip install tavily-python`")


class TavilyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        enable_search_context: bool = False,
        all: bool = False,
        max_tokens: int = 6000,
        include_answer: bool = True,
        search_depth: Literal["basic", "advanced"] = "advanced",
        format: Literal["json", "markdown"] = "markdown",
        auto_parameters: bool = False,
        topic: Optional[Literal["general", "news", "finance"]] = None,
        chunks_per_source: Optional[int] = None,
        time_range: Optional[Literal["day", "week", "month", "year", "d", "w", "m", "y"]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_raw_content: bool = False,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        country: Optional[str] = None,
        **kwargs,
    ):
        self.api_key = api_key or getenv("TAVILY_API_KEY")
        if not self.api_key:
            logger.error("TAVILY_API_KEY not provided")

        self.client: TavilyClient = TavilyClient(api_key=self.api_key)
        self.search_depth: Literal["basic", "advanced"] = search_depth
        self.max_tokens: int = max_tokens
        self.include_answer: bool = include_answer
        self.format: Literal["json", "markdown"] = format
        self.auto_parameters = auto_parameters
        self.topic = topic
        self.chunks_per_source = chunks_per_source
        self.time_range = time_range
        self.start_date = start_date
        self.end_date = end_date
        self.include_raw_content = include_raw_content
        self.include_domains = include_domains
        self.exclude_domains = exclude_domains
        self.country = country

        tools: List[Any] = []

        if enable_search or all:
            if enable_search_context:
                tools.append(self.web_search_with_tavily)
            else:
                tools.append(self.web_search_using_tavily)

        super().__init__(name="tavily_tools", tools=tools, **kwargs)

    def web_search_using_tavily(self, query: str, max_results: int = 5) -> str:
        """Use this function to search the web for a given query.
        This function uses the Tavily API to provide realtime online information about the query.

        Args:
            query (str): Query to search for.
            max_results (int): Maximum number of results to return. Defaults to 5.

        Returns:
            str: JSON string of results related to the query.
        """

        response = self.client.search(
            query=query,
            search_depth=self.search_depth,
            include_answer=self.include_answer,
            max_results=max_results,
            auto_parameters=self.auto_parameters,
            topic=self.topic,
            chunks_per_source=self.chunks_per_source,
            time_range=self.time_range,
            start_date=self.start_date,
            end_date=self.end_date,
            include_raw_content=self.include_raw_content,
            include_domains=self.include_domains,
            exclude_domains=self.exclude_domains,
            country=self.country,
        )

        clean_response: Dict[str, Any] = {"query": query}
        if "answer" in response:
            clean_response["answer"] = response["answer"]
        if "response_time" in response:
            clean_response["response_time"] = response["response_time"]
        if "auto_parameters" in response:
            clean_response["auto_parameters"] = response["auto_parameters"]
        if "request_id" in response:
            clean_response["request_id"] = response["request_id"]

        clean_results = []
        current_token_count = len(json.dumps(clean_response))
        for result in response.get("results", []):
            _result = {
                "title": result["title"],
                "url": result["url"],
                "content": result["content"],
                "score": result["score"],
            }
            current_token_count += len(json.dumps(_result))
            if current_token_count > self.max_tokens:
                break
            clean_results.append(_result)
        clean_response["results"] = clean_results

        if self.format == "json":
            return json.dumps(clean_response) if clean_response else "No results found."
        elif self.format == "markdown":
            _markdown = ""
            _markdown += f"# {query}\n\n"
            if "answer" in clean_response:
                _markdown += "### Summary\n"
                _markdown += f"{clean_response.get('answer')}\n\n"
            if "response_time" in clean_response:
                _markdown += f"**Response Time:** {clean_response['response_time']} seconds\n\n"
            if "auto_parameters" in clean_response:
                _markdown += f"**Auto Parameters:** {clean_response['auto_parameters']}\n\n"
            if "request_id" in clean_response:
                _markdown += f"**Request ID:** {clean_response['request_id']}\n\n"
            for result in clean_response["results"]:
                _markdown += f"### [{result['title']}]({result['url']})\n"
                _markdown += f"{result['content']}\n\n"
            return _markdown

    def web_search_with_tavily(self, query: str) -> str:
        """Use this function to search the web for a given query.
        This function uses the Tavily API to provide realtime online information about the query.

        Args:
            query (str): Query to search for.

        Returns:
            str: JSON string of results related to the query.
        """

        return self.client.get_search_context(
            query=query, search_depth=self.search_depth, max_tokens=self.max_tokens, include_answer=self.include_answer
        )
