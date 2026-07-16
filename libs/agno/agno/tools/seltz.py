import json
from inspect import Parameter, signature
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

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

    try:
        from seltz import Includes
    except ImportError:
        Includes = None
except ImportError as exc:
    raise ImportError("`seltz` not installed. Please install using `pip install seltz`") from exc


class SeltzTools(Toolkit):
    """Toolkit for interacting with the Seltz AI-powered search API.

    Args:
        api_key: Seltz API key. If not provided, uses the `SELTZ_API_KEY` env var.
        endpoint: Optional Seltz gRPC endpoint. If not provided, uses SDK default.
        insecure: Use an insecure gRPC channel. Defaults to False.
        max_results: Default maximum number of results to return per search.
        max_documents: Deprecated alias for `max_results`.
        context: Legacy SDK context to improve search quality.
        profile: Legacy SDK search profile to use for ranking.
        show_results: Log search results for debugging.
        enable_search: Enable search tool functionality. Defaults to True.
        all: Enable all tools. Overrides individual flags when True. Defaults to False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        insecure: bool = False,
        max_results: Optional[int] = None,
        max_documents: Optional[int] = None,
        context: Optional[str] = None,
        profile: Optional[str] = None,
        show_results: bool = False,
        enable_search: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        default_max_results = self._resolve_max_results(max_results=max_results, max_documents=max_documents)

        self.api_key = api_key or getenv("SELTZ_API_KEY")
        if not self.api_key:
            log_error("SELTZ_API_KEY not set. Please set the SELTZ_API_KEY environment variable.")

        self.endpoint = endpoint
        self.insecure = insecure
        self.max_results = default_max_results
        self.max_documents = default_max_results
        self.context = context
        self.profile = profile
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
            if url:
                doc_dict["url"] = url
            if content:
                doc_dict["content"] = content
            if doc_dict:
                parsed.append(doc_dict)
        return json.dumps(parsed, indent=4, ensure_ascii=False)

    @staticmethod
    def _resolve_max_results(max_results: Optional[int] = None, max_documents: Optional[int] = None) -> int:
        """Resolve current and legacy result limit names into a positive integer."""
        limit = max_results if max_results is not None else max_documents if max_documents is not None else 10
        parameter_name = "max_results" if max_results is not None else "max_documents"

        if limit <= 0:
            raise ValueError(f"{parameter_name} must be greater than 0")

        return limit

    def _client_supports_search_parameter(self, parameter_name: str) -> bool:
        """Return whether the installed Seltz SDK search method accepts a parameter."""
        if not self.client:
            return False

        try:
            search_parameters = signature(self.client.search).parameters
        except (TypeError, ValueError):
            return True

        return parameter_name in search_parameters or any(
            parameter.kind == Parameter.VAR_KEYWORD for parameter in search_parameters.values()
        )

    def _search_current_sdk(
        self,
        query: str,
        max_results: int,
        scope: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Any:
        """Search with the current Seltz SDK API."""
        if not self.client:
            raise ValueError("SELTZ_API_KEY not set. Please set the SELTZ_API_KEY environment variable.")

        search_kwargs: dict[str, Any] = {"query": query, "max_results": max_results}
        if scope is not None:
            search_kwargs["scope"] = scope
        if include_domains is not None:
            search_kwargs["include_domains"] = include_domains
        if exclude_domains is not None:
            search_kwargs["exclude_domains"] = exclude_domains
        if from_date is not None:
            search_kwargs["from_date"] = from_date
        if to_date is not None:
            search_kwargs["to_date"] = to_date

        return self.client.search(**search_kwargs)

    def _search_legacy_sdk(
        self,
        query: str,
        max_results: int,
        context: Optional[str] = None,
        scope: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Any:
        """Search with the legacy Seltz SDK API that uses Includes."""
        if not self.client:
            raise ValueError("SELTZ_API_KEY not set. Please set the SELTZ_API_KEY environment variable.")
        if Includes is None:
            raise ValueError("Installed seltz SDK does not support search result limits. Upgrade seltz.")
        if any(value is not None for value in (scope, include_domains, exclude_domains, from_date, to_date)):
            raise ValueError("scope, include_domains, exclude_domains, from_date, and to_date require seltz>=1.2.0.")

        search_context = context if context is not None else self.context
        includes = Includes(max_documents=max_results)
        return self.client.search(query=query, includes=includes, context=search_context, profile=self.profile)

    def search_seltz(
        self,
        query: str,
        max_results: Optional[int] = None,
        max_documents: Optional[int] = None,
        scope: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        """Use this function to search Seltz for a query.

        Args:
            query: The query to search for.
            max_results: Maximum number of results to return. Defaults to toolkit `max_results`.
            max_documents: Deprecated alias for `max_results`.
            scope: Restrict the search to a supported scope, such as "news".
            include_domains: Only include results from these domains.
            exclude_domains: Exclude results from these domains.
            from_date: Only include results published on or after this ISO 8601 date.
            to_date: Only include results published on or before this ISO 8601 date.
            context: Legacy SDK context. Ignored by current Seltz SDK versions.

        Returns:
            str: Search results in JSON format.
        """
        if not query:
            return "Error: Please provide a query to search for."

        if not self.client:
            return "Error: SELTZ_API_KEY not set. Please set the SELTZ_API_KEY environment variable."

        if max_results is None and max_documents is None:
            limit = self.max_results
        else:
            try:
                limit = self._resolve_max_results(max_results=max_results, max_documents=max_documents)
            except ValueError as exc:
                return f"Error: {exc}."

        try:
            if self.show_results:
                log_info(f"Searching Seltz for: {query}")

            if self._client_supports_search_parameter("max_results"):
                response = self._search_current_sdk(
                    query=query,
                    max_results=limit,
                    scope=scope,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    from_date=from_date,
                    to_date=to_date,
                )
            else:
                response = self._search_legacy_sdk(
                    query=query,
                    max_results=limit,
                    context=context,
                    scope=scope,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    from_date=from_date,
                    to_date=to_date,
                )
            result = self._parse_documents(response.documents)

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
            log_error(f"Seltz error: {exc}")
            return f"Error: {exc}"
        except Exception as exc:
            logger.exception("Failed to search Seltz")
            return f"Error: {exc}"
