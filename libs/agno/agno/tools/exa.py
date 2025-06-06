import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from os import getenv
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

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
        research (bool): Enable research tool functionality. Default is True.
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
        timeout (int): Maximum time in seconds to wait for API responses. Default is 30 seconds.
    """

    def __init__(
        self,
        search: bool = True,
        get_contents: bool = True,
        find_similar: bool = True,
        answer: bool = True,
        research: bool = False,
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
        timeout: int = 30,
        research_model: Literal["exa-research", "exa-research-pro"] = "exa-research",
        **kwargs,
    ):
        self.api_key = api_key or getenv("EXA_API_KEY")
        if not self.api_key:
            logger.error("EXA_API_KEY not set. Please set the EXA_API_KEY environment variable.")

        self.exa = Exa(self.api_key)
        self.show_results = show_results
        self.timeout = timeout

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
        self.research_model: Literal["exa-research", "exa-research-pro"] = research_model

        tools: List[Any] = []
        if search:
            tools.append(self.search_exa)
        if get_contents:
            tools.append(self.get_contents)
        if find_similar:
            tools.append(self.find_similar)
        if answer:
            tools.append(self.exa_answer)
        if research:
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
            if self.highlights:
                try:
                    if result.highlights:  # type: ignore
                        result_dict["highlights"] = result.highlights  # type: ignore
                except Exception as e:
                    log_debug(f"Failed to get highlights {e}")
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
                log_info(f"Searching exa for: {query}")
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

            # Execute search with timeout
            exa_results = self._execute_with_timeout(self.exa.search_and_contents, query, **search_kwargs)

            parsed_results = self._parse_results(exa_results)
            # Extract search results
            if self.show_results:
                log_info(parsed_results)
            return parsed_results
        except TimeoutError as e:
            logger.error(f"Search timed out after {self.timeout} seconds")
            return f"Error: {str(e)}"
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
                log_info(f"Fetching contents for URLs: {urls}")

            # Execute get_contents with timeout
            exa_results = self._execute_with_timeout(self.exa.get_contents, urls=urls, **query_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                log_info(parsed_results)

            return parsed_results
        except TimeoutError as e:
            logger.error(f"Get contents timed out after {self.timeout} seconds")
            return f"Error: {str(e)}"
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
                log_info(f"Finding similar links to: {url}")

            # Execute find_similar with timeout
            exa_results = self._execute_with_timeout(self.exa.find_similar_and_contents, url=url, **query_kwargs)

            parsed_results = self._parse_results(exa_results)
            if self.show_results:
                log_info(parsed_results)

            return parsed_results
        except TimeoutError as e:
            logger.error(f"Find similar timed out after {self.timeout} seconds")
            return f"Error: {str(e)}"
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
            logger.error(f"Answer generation timed out after {self.timeout} seconds")
            return f"Error: {str(e)}"
        except Exception as e:
            logger.error(f"Failed to get answer from Exa: {e}")
            return f"Error: {e}"

    def research(
        self,
        instructions: str,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Perform deep research on a topic.

        Args:
            instructions (str): Research instructions.
            output_schema (Optional[Dict[str, Any]]): JSON schema for structured output. If not provided, the API will auto-infer an appropriate schema.
        Returns:
            str: JSON formatted research results including data and citations.
        """
        try:
            log_debug(f"Creating research task with instructions: {instructions}")
            log_debug(f"Output schema: {output_schema}")

            task_kwargs: Dict[str, Any] = {
                "instructions": instructions,
                "model": self.research_model,
            }

            if output_schema is not None:
                task_kwargs["output_schema"] = output_schema
            else:
                task_kwargs["output_infer_schema"] = True

            task_result = self._execute_with_timeout(self.exa.research.create_task, **task_kwargs)
            task_id = task_result.id

            if self.show_results:
                log_info(f"Research task created with ID: {task_id}")

            # Step 2: Poll until complete (using default polling settings)
            task = self.exa.research.poll_task(task_id)

            # Step 3: Format and return results
            result: Dict[str, Any] = {"data": task.data, "citations": {}}

            # Process citations by field
            for field, sources in task.citations.items():
                result["citations"][field] = [
                    {"url": source.url, "title": source.title, "id": source.id} for source in sources
                ]

            if self.show_results:
                log_info("Research completed successfully")

            return json.dumps(result, indent=4)

        except TimeoutError:
            error_msg = "Research task timed out"
            logger.error(error_msg)
            return json.dumps({"error": error_msg}, indent=4)
        except Exception as e:
            error_msg = f"Research failed: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg}, indent=4)
