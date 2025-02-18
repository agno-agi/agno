import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from exa_py import Exa
    from exa_py.api import SearchResponse
except ImportError:
    raise ImportError("`exa_py` not installed. Please install using `pip install exa_py`")


class ExaTools(Toolkit):
    """
    ExaTools is a toolkit for interfacing with the Exa web search engine, providing
    functionalities to perform categorized searches and retrieve structured results.

    Args:
        text (bool): Retrieve text content from results. Default is True.
        text_length_limit (int): Max length of text content per result. Default is 1000.
        highlights (bool): Include highlighted snippets. Default is True.
        answer (bool): Enable answer generation. Default is True.
        api_key (Optional[str]): Exa API key. Retrieved from `EXA_API_KEY` env variable if not provided.
        num_results (Optional[int]): Default number of search results. Overrides individual searches if set.
        start_crawl_date (Optional[str]): Include results crawled on/after this date (`YYYY-MM-DD`).
        end_crawl_date (Optional[str]): Include results crawled on/before this date (`YYYY-MM-DD`).
        start_published_date (Optional[str]): Include results published on/after this date (`YYYY-MM-DD`).
        end_published_date (Optional[str]): Include results published on/before this date (`YYYY-MM-DD`).
        use_autoprompt (Optional[bool]): Enable autoprompt features in queries.
        type (Optional[str]): Specify content type (e.g., article, blog, video).
        category (Optional[str]): Filter results by category. Options are "company", "research paper", "news", "pdf", "github", "tweet", "personal site", "linkedin profile", "financial report".
        include_domains (Optional[List[str]]): Restrict results to these domains.
        exclude_domains (Optional[List[str]]): Exclude results from these domains.
        show_results (bool): Log search results for debugging. Default is False.
        model (Optional[str]): The search model to use. Options are 'exa' or 'exa-pro'.
    """

    def __init__(
        self,
        search: bool = True,
        get_contents: bool = True,
        find_similar: bool = True,
        answer: bool = True,
        text: bool = True,
        text_length_limit: int = 1000,
        highlights: bool = True,
        summary: bool = False,
        api_key: Optional[str] = None,
        num_results: Optional[int] = None,
        livecrawl: str = "always",
        start_crawl_date: Optional[str] = None,
        end_crawl_date: Optional[str] = None,
        start_published_date: Optional[str] = None,
        end_published_date: Optional[str] = None,
        use_autoprompt: Optional[bool] = None,
        type: Optional[str] = None,
        category: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        show_results: bool = False,
        model: Optional[str] = None,
    ):
        super().__init__(name="exa")

        self.api_key = api_key or getenv("EXA_API_KEY")
        if not self.api_key:
            logger.error("EXA_API_KEY not set. Please set the EXA_API_KEY environment variable.")

        self.exa = Exa(self.api_key)
        self.show_results = show_results

        self.text: bool = text
        self.text_length_limit: int = text_length_limit
        self.highlights: bool = highlights
        self.summary: bool = summary
        self.num_results: Optional[int] = num_results
        self.livecrawl: str = livecrawl
        self.start_crawl_date: Optional[str] = start_crawl_date
        self.end_crawl_date: Optional[str] = end_crawl_date
        self.start_published_date: Optional[str] = start_published_date
        self.end_published_date: Optional[str] = end_published_date
        self.use_autoprompt: Optional[bool] = use_autoprompt
        self.type: Optional[str] = type
        self.category: Optional[str] = category
        self.include_domains: Optional[List[str]] = include_domains
        self.exclude_domains: Optional[List[str]] = exclude_domains
        self.model: Optional[str] = model

        if search:
            self.register(self.search_exa)
        if get_contents:
            self.register(self.get_contents)
        if find_similar:
            self.register(self.find_similar)
        if answer:
            self.register(self.exa_answer)

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
            if self.highlights:
                try:
                    if result.highlights:  # type: ignore
                        result_dict["highlights"] = result.highlights  # type: ignore
                except Exception as e:
                    logger.debug(f"Failed to get highlights {e}")
                    result_dict["highlights"] = f"Failed to get highlights {e}"
            exa_results_parsed.append(result_dict)
        return json.dumps(exa_results_parsed, indent=4)

    def search_exa(self, query: str, num_results: int = 5, category: Optional[str] = None) -> str:
        """Use this function to search Exa (a web search engine) for a query.

        Args:
            query (str): The query to search for.
            num_results (int): Number of results to return. Defaults to 5.
            category (Optional[str]): The category to filter search results.
                Options are "company", "research paper", "news", "pdf", "github",
                "tweet", "personal site", "linkedin profile", "financial report".

        Returns:
            str: The search results in JSON format.
        """
        try:
            if self.show_results:
                logger.info(f"Searching exa for: {query}")
            search_kwargs: Dict[str, Any] = {
                "text": self.text,
                "highlights": self.highlights,
                "summary": self.summary,
                "num_results": self.num_results or num_results,
                "start_crawl_date": self.start_crawl_date,
                "end_crawl_date": self.end_crawl_date,
                "start_published_date": self.start_published_date,
                "end_published_date": self.end_published_date,
                "use_autoprompt": self.use_autoprompt,
                "type": self.type,
                "category": self.category or category,  # Prefer a user-set category
                "include_domains": self.include_domains,
                "exclude_domains": self.exclude_domains,
            }
            # Clean up the kwargs
            search_kwargs = {k: v for k, v in search_kwargs.items() if v is not None}
            exa_results = self.exa.search_and_contents(query, **search_kwargs)

            parsed_results = self._parse_results(exa_results)
            # Extract search results
            if self.show_results:
                logger.info(parsed_results)
            return parsed_results
        except Exception as e:
            logger.error(f"Failed to search exa {e}")
            return f"Error: {e}"

    def get_contents(self, urls: list[str]) -> str:
        """
        Retrieve detailed content from specific URLs using the Exa API.

        Args:
            urls (list(str)): A list of URLs from which to fetch content.

        Returns:
            str: The search results in JSON format.
        """

        query_kwargs: Dict[str, Any] = {
            "text": self.text,
            "highlights": self.highlights,
            "summary": self.summary,
        }

        try:
            if self.show_results:
                logger.info(f"Fetching contents for URLs: {urls}")

            exa_results = self.exa.get_contents(urls=urls, **query_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                logger.info(parsed_results)

            return parsed_results
        except Exception as e:
            logger.error(f"Failed to get contents from Exa: {e}")
            return f"Error: {e}"

    def find_similar(self, url: str, num_results: int = 5) -> str:
        """
        Find similar links to a given URL using the Exa API.

        Args:
            url (str): The URL for which to find similar links.
            num_results (int, optional): The number of similar links to return. Defaults to 5.

        Returns:
            str: The search results in JSON format.
        """

        query_kwargs: Dict[str, Any] = {
            "text": self.text,
            "highlights": self.highlights,
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
                logger.info(f"Finding similar links to: {url}")

            exa_results = self.exa.find_similar_and_contents(url=url, **query_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                logger.info(parsed_results)

            return parsed_results
        except Exception as e:
            logger.error(f"Failed to get similar links from Exa: {e}")
            return f"Error: {e}"

    def exa_answer(self, query: str, text: bool = False) -> str:
        """
        Get an LLM answer to a question informed by Exa search results.

        Args:
            query (str): The question or query to answer.
            text (bool): Include full text from citation. Default is False.
        Returns:
            str: The answer results in JSON format with both generated answer and sources.
        """

        if self.model and self.model not in ["exa", "exa-pro"]:
            raise ValueError("Model must be either 'exa' or 'exa-pro'")
        try:
            if self.show_results:
                logger.info(f"Generating answer for query: {query}")
            answer_kwargs: Dict[str, Any] = {
                "model": self.model,
                "text": text,
            }
            answer_kwargs = {k: v for k, v in answer_kwargs.items() if v is not None}
            answer = self.exa.answer(query=query, **answer_kwargs)
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
                logger.info(json.dumps(result))

            return json.dumps(result, indent=4)

        except Exception as e:
            logger.error(f"Failed to get answer from Exa: {e}")
            return f"Error: {e}"
