import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from os import getenv
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

try:
    from exa_py import Exa
    from exa_py.api import SearchResponse
except ImportError:
    raise ImportError("`exa_py` not installed. Please install using `pip install exa_py`")


class ExaTools(Toolkit):
    """
    ExaTools is a toolkit for interfacing with Exa, one of the best web search APIs for AI, providing
    functionalities to perform categorized searches and retrieve structured results.

    Args:
        search (bool): Enable search functionality. Default is True.
        get_contents (bool): Enable get contents functionality. Default is True.
        find_similar (bool): Enable find similar functionality. Default is True.
        answer (bool): Enable answer generation. Default is True.
        research (bool): Enable research tool functionality. Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        text (bool): Retrieve text content from results. Default is True.
        text_length_limit (int): Max length of text content per result. Default is 1000.
        api_key (Optional[str]): Exa API key. Retrieved from `EXA_API_KEY` env variable if not provided.
        num_results (Optional[int]): Default number of search results. Overrides individual searches if set.
        start_crawl_date (Optional[str]): Include results crawled on/after this date (`YYYY-MM-DD`).
        end_crawl_date (Optional[str]): Include results crawled on/before this date (`YYYY-MM-DD`).
        start_published_date (Optional[str]): Include results published on/after this date (`YYYY-MM-DD`).
        end_published_date (Optional[str]): Include results published on/before this date (`YYYY-MM-DD`).
        type (Optional[str]): Specify content type (e.g., article, blog, video).
        category (Optional[str]): Filter results by category. Options are "company", "research paper", "news", "pdf", "github", "tweet", "personal site", "linkedin profile", "financial report".
        include_domains (Optional[List[str]]): Restrict results to these domains.
        exclude_domains (Optional[List[str]]): Exclude results from these domains.
        show_results (bool): Log search results for debugging. Default is False.
        model (Optional[str]): The search model to use. Options are 'exa' or 'exa-pro'.
        timeout (int): Maximum time in seconds to wait for API responses. Default is 30 seconds.
    """

    def __init__(
        self,
        search: bool = True,
        get_contents: bool = True,
        find_similar: bool = True,
        answer: bool = True,
        research: bool = False,
        all: bool = False,
        text: bool = True,
        text_length_limit: int = 1000,
        summary: bool = False,
        api_key: Optional[str] = None,
        num_results: Optional[int] = None,
        livecrawl: str = "always",
        start_crawl_date: Optional[str] = None,
        end_crawl_date: Optional[str] = None,
        start_published_date: Optional[str] = None,
        end_published_date: Optional[str] = None,
        type: Optional[str] = None,
        category: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        show_results: bool = False,
        model: Optional[str] = None,
        timeout: int = 30,
        **kwargs,
    ):
        self.api_key = api_key or getenv("EXA_API_KEY")
        if not self.api_key:
            log_error("EXA_API_KEY not set. Please set the EXA_API_KEY environment variable.")

        self.exa = Exa(self.api_key)
        self.show_results = show_results
        self.timeout = timeout

        self.text: bool = text
        self.text_length_limit: int = text_length_limit

        self.summary: bool = summary
        self.num_results: Optional[int] = num_results
        self.livecrawl: str = livecrawl
        self.start_crawl_date: Optional[str] = start_crawl_date
        self.end_crawl_date: Optional[str] = end_crawl_date
        self.start_published_date: Optional[str] = start_published_date
        self.end_published_date: Optional[str] = end_published_date
        self.type: Optional[str] = type
        self.category: Optional[str] = category
        self.include_domains: Optional[List[str]] = include_domains
        self.exclude_domains: Optional[List[str]] = exclude_domains
        self.model: Optional[str] = model

        tools: List[Callable] = []
        if all or search:
            tools.append(self.search_exa)
        if all or get_contents:
            tools.append(self.get_contents)
        if all or find_similar:
            tools.append(self.find_similar)
        if all or answer:
            tools.append(self.exa_answer)
        if all or research:
            tools.append(self.research)

        super().__init__(name="exa", tools=tools, **kwargs)

    def _execute_with_timeout(self, func, *args, **kwargs):
        """Execute a function with a timeout using a temporary ThreadPoolExecutor."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=self.timeout)
            except TimeoutError:
                raise TimeoutError(f"Operation timed out after {self.timeout} seconds")
            except Exception as e:
                raise e

    def _parse_results(self, exa_results: SearchResponse) -> str:
        exa_results_parsed = []
        for result in exa_results.results:
            result_dict = {"url": result.url}
            if result.title:
                result_dict["title"] = result.title
            if result.author and result.author != "":
                result_dict["author"] = result.author
            if result.published_date:
                result_dict["published_date"] = result.published_date
            if result.text:
                _text = result.text
                if self.text_length_limit:
                    _text = _text[: self.text_length_limit]
                result_dict["text"] = _text
            exa_results_parsed.append(result_dict)
        return json.dumps(exa_results_parsed, indent=4, ensure_ascii=False)

    def search_exa(self, query: str, num_results: int = 5, category: Optional[str] = None) -> str:
        """Search the web using Exa.

        Args:
            query: The query to search for.
            num_results: Number of results to return. Defaults to 5.
            category: Category filter (company, research paper, news, pdf, github,
                tweet, personal site, linkedin profile, financial report).

        Returns:
            JSON search results.
        """
        try:
            if self.show_results:
                log_info(f"Searching exa for: {query}")
            search_kwargs: Dict[str, Any] = {
                "text": self.text,
                "summary": self.summary,
                "num_results": self.num_results or num_results,
                "start_crawl_date": self.start_crawl_date,
                "end_crawl_date": self.end_crawl_date,
                "start_published_date": self.start_published_date,
                "end_published_date": self.end_published_date,
                "type": self.type,
                "category": self.category or category,  # Prefer a user-set category
                "include_domains": self.include_domains,
                "exclude_domains": self.exclude_domains,
            }
            # Clean up the kwargs
            search_kwargs = {k: v for k, v in search_kwargs.items() if v is not None}

            # Execute search with timeout
            exa_results = self._execute_with_timeout(self.exa.search_and_contents, query, **search_kwargs)

            parsed_results = self._parse_results(exa_results)
            # Extract search results
            if self.show_results:
                log_info(parsed_results)
            return parsed_results
        except TimeoutError as e:
            log_error(f"Search timed out after {self.timeout} seconds: {str(e)}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to search exa")
            return json.dumps({"error": str(e)})

    def get_contents(self, urls: list[str]) -> str:
        """Retrieve detailed content from specific URLs using Exa.

        Args:
            urls: List of URLs to fetch content from.

        Returns:
            JSON with content results.
        """

        query_kwargs: Dict[str, Any] = {
            "text": self.text,
            "summary": self.summary,
        }

        try:
            if self.show_results:
                log_info(f"Fetching contents for URLs: {urls}")

            # Execute get_contents with timeout
            exa_results = self._execute_with_timeout(self.exa.get_contents, urls=urls, **query_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                log_info(parsed_results)

            return parsed_results
        except TimeoutError as e:
            log_error(f"Get contents timed out after {self.timeout} seconds: {str(e)}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to get contents from Exa")
            return json.dumps({"error": str(e)})

    def find_similar(self, url: str, num_results: int = 5) -> str:
        """Find similar links to a given URL using Exa.

        Args:
            url: The URL to find similar links for.
            num_results: Number of similar links to return. Defaults to 5.

        Returns:
            JSON with similar results.
        """

        query_kwargs: Dict[str, Any] = {
            "text": self.text,
            "summary": self.summary,
            "include_domains": self.include_domains,
            "exclude_domains": self.exclude_domains,
            "start_crawl_date": self.start_crawl_date,
            "end_crawl_date": self.end_crawl_date,
            "start_published_date": self.start_published_date,
            "end_published_date": self.end_published_date,
            "num_results": self.num_results or num_results,
        }

        try:
            if self.show_results:
                log_info(f"Finding similar links to: {url}")

            # Execute find_similar with timeout
            exa_results = self._execute_with_timeout(self.exa.find_similar_and_contents, url=url, **query_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                log_info(parsed_results)

            return parsed_results
        except TimeoutError as e:
            log_error(f"Find similar timed out after {self.timeout} seconds: {str(e)}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to get similar links from Exa")
            return json.dumps({"error": str(e)})

    def exa_answer(self, query: str, text: bool = False) -> str:
        """Get an LLM answer to a question informed by Exa search results.

        Args:
            query: The question or query to answer.
            text: Include full text from citation. Defaults to False.

        Returns:
            JSON with answer and source citations.
        """

        if self.model and self.model not in ["exa", "exa-pro"]:
            raise ValueError("Model must be either 'exa' or 'exa-pro'")
        try:
            if self.show_results:
                log_info(f"Generating answer for query: {query}")
            answer_kwargs: Dict[str, Any] = {
                "model": self.model,
                "text": text,
            }
            answer_kwargs = {k: v for k, v in answer_kwargs.items() if v is not None}

            # Execute answer with timeout
            answer = self._execute_with_timeout(self.exa.answer, query=query, **answer_kwargs)

            result = {
                "answer": answer.answer,  # type: ignore
                "citations": [
                    {
                        "id": citation.id,
                        "url": citation.url,
                        "title": citation.title,
                        "published_date": citation.published_date,
                        "author": citation.author,
                        "text": citation.text if text else None,
                    }
                    for citation in answer.citations  # type: ignore
                ],
            }
            if self.show_results:
                log_info(json.dumps(result))

            return json.dumps(result, indent=4)

        except TimeoutError as e:
            log_error(f"Answer generation timed out after {self.timeout} seconds: {str(e)}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to get answer from Exa")
            return json.dumps({"error": str(e)})

    def research(self, instructions: str, num_results: int = 10) -> str:
        """Perform deep research on a topic using Exa's deep-reasoning search.

        Args:
            instructions: Research instructions or query.
            num_results: Number of results to return. Defaults to 10.

        Returns:
            JSON research results with comprehensive analysis.
        """
        try:
            if self.show_results:
                log_info(f"Performing deep research for: {instructions}")

            search_kwargs: Dict[str, Any] = {
                "text": True,
                "summary": True,
                "num_results": self.num_results or num_results,
                "type": "deep-reasoning",
                "start_crawl_date": self.start_crawl_date,
                "end_crawl_date": self.end_crawl_date,
                "start_published_date": self.start_published_date,
                "end_published_date": self.end_published_date,
                "include_domains": self.include_domains,
                "exclude_domains": self.exclude_domains,
            }
            search_kwargs = {k: v for k, v in search_kwargs.items() if v is not None}

            exa_results = self._execute_with_timeout(self.exa.search_and_contents, instructions, **search_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                log_info(parsed_results)

            return parsed_results

        except TimeoutError:
            error_msg = f"Research timed out after {self.timeout} seconds"
            log_error(error_msg)
            return json.dumps({"error": error_msg})
        except Exception as e:
            error_msg = f"Research failed: {str(e)}"
            log_error(error_msg)
            return json.dumps({"error": error_msg})
