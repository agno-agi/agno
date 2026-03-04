import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    from seltz import Seltz
    from seltz.exceptions import (
        SeltzAPIError,
        SeltzAuthenticationError,
        SeltzConfigurationError,
        SeltzConnectionError,
        SeltzError,
        SeltzRateLimitError,
        SeltzTimeoutError,
    )
except ImportError as exc:
    raise ImportError("`seltz` not installed. Please install using `pip install seltz`") from exc


class SeltzTools(Toolkit):
    """Toolkit for interacting with the Seltz AI-powered search API.

    Args:
        api_key: Seltz API key. If not provided, uses the `SELTZ_API_KEY` env var.
        endpoint: Optional Seltz gRPC endpoint. If not provided, uses SDK default.
        insecure: Use an insecure gRPC channel. Defaults to False.
        max_documents: Default maximum number of documents to return per search.
        show_results: Log search results for debugging.
        enable_search: Enable search tool functionality. Defaults to True.
        all: Enable all tools. Overrides individual flags when True. Defaults to False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        insecure: bool = False,
        max_documents: int = 10,
        show_results: bool = False,
        enable_search: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        if max_documents <= 0:
            raise ValueError("max_documents must be greater than 0")

        self.api_key = api_key or getenv("SELTZ_API_KEY")
        if not self.api_key:
            logger.error("SELTZ_API_KEY not set. Please set the SELTZ_API_KEY environment variable.")

        self.endpoint = endpoint
        self.insecure = insecure
        self.max_documents = max_documents
        self.show_results = show_results

        self.client: Optional[Seltz] = None
        if self.api_key:
            client_kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.endpoint:
                client_kwargs["endpoint"] = self.endpoint
            if self.insecure:
                client_kwargs["insecure"] = self.insecure
            self.client = Seltz(**client_kwargs)

        tools: List[Any] = []
        if all or enable_search:
            tools.append(self.search_seltz)

        super().__init__(name="seltz", tools=tools, **kwargs)

    def _parse_documents(self, documents: Any) -> str:
        """Convert Seltz documents into JSON for the agent."""
        parsed: List[dict[str, Any]] = []
        for doc in documents or []:
            doc_dict: dict[str, Any] = {}
            url = getattr(doc, "url", None)
            content = getattr(doc, "content", None)

            if url is not None:
                doc_dict["url"] = url
            if content:
                doc_dict["content"] = content
            if doc_dict:
                parsed.append(doc_dict)
        return json.dumps(parsed, indent=4, ensure_ascii=False)

    def search_seltz(self, query: str, max_documents: Optional[int] = None) -> str:
        """Use this function to search Seltz for a query.

        Args:
            query: The query to search for.
            max_documents: Maximum number of documents to return. Defaults to toolkit `max_documents`.

        Returns:
            str: Search results in JSON format.
        """
        if not query:
            return "Error: Please provide a query to search for."

        if not self.client:
            return "Error: SELTZ_API_KEY not set. Please set the SELTZ_API_KEY environment variable."

        limit = max_documents if max_documents is not None else self.max_documents
        if limit <= 0:
            return "Error: max_documents must be greater than 0."

        try:
            if self.show_results:
                log_info(f"Searching Seltz for: {query}")

            response = self.client.search(query, max_documents=limit)
            result = self._parse_documents(getattr(response, "documents", []))

            if self.show_results:
                log_info(result)

            return result
        except (
            SeltzConfigurationError,
            SeltzAuthenticationError,
            SeltzConnectionError,
            SeltzTimeoutError,
            SeltzRateLimitError,
            SeltzAPIError,
            SeltzError,
        ) as exc:
            logger.error(f"Seltz error: {exc}")
            return f"Error: {exc}"
        except Exception as exc:
            logger.error(f"Failed to search Seltz: {exc}")
            return f"Error: {exc}"
