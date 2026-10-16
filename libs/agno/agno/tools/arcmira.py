import json
from math import isfinite
from os import getenv
from typing import Any, Literal, Optional

import httpx

from agno.tools import Toolkit


class ArcmiraTools(Toolkit):
    """Search indexed YouTube transcripts with timestamps and coverage metadata.

    API reference: https://arcmira.com/docs
    Requests use the configured account's search allowance. This toolkit does not
    retrieve full Premium transcripts or create transcription jobs.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        limit: int = 5,
        request_timeout: float = 30,
        enable_search: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("ARCMIRA_API_KEY")
        if not self.api_key:
            raise ValueError("Set ARCMIRA_API_KEY or pass api_key to ArcmiraTools.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20.")
        if not isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("request_timeout must be finite and positive.")
        self.limit = limit
        self.request_timeout = request_timeout
        super().__init__(
            name="arcmira_tools",
            tools=[self.search_transcripts] if enable_search or all else [],
            async_tools=[(self.asearch_transcripts, "search_transcripts")] if enable_search or all else [],
            **kwargs,
        )

    def search_transcripts(
        self,
        query: str,
        channel_ids: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        source: Optional[Literal["arcmira_premium", "creator_captions", "third_party_quick"]] = None,
    ) -> str:
        """Search YouTube transcripts for one topic or phrase and return timestamped passages.

        Cite returned source links and preserve partial, failed_batches, access,
        search_index and note fields. Empty results do not prove absence. Speaker
        attribution is available only where the returned data identifies a speaker.
        Resolve relative watch_url values against https://arcmira.com.

        Args:
            query: One topic or phrase, at least two characters. Search unrelated topics separately.
            channel_ids: Optional comma-separated YouTube channel IDs, at most eight. IDs, not channel names.
            after: Optional inclusive publication date or ISO 8601 instant, interpreted in UTC.
            before: Optional exclusive publication date or ISO 8601 instant, interpreted in UTC.
            source: Optional transcript source class. Premium access can be refused by the account's plan.

        Returns:
            str: Complete JSON response including passages, timestamps, source links and coverage metadata.
        """
        params = self._search_params(query, channel_ids, after, before, source)
        try:
            with httpx.Client(timeout=self.request_timeout, follow_redirects=False) as client:
                response = client.get(
                    "https://api.arcmira.com/v1/search",
                    params=params,
                    headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                )
        except httpx.RequestError:
            raise RuntimeError("Arcmira search request failed. No automatic retry was made.") from None
        return self._response_json(response)

    async def asearch_transcripts(
        self,
        query: str,
        channel_ids: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        source: Optional[Literal["arcmira_premium", "creator_captions", "third_party_quick"]] = None,
    ) -> str:
        """Search YouTube transcripts for one topic or phrase and return timestamped passages.

        Cite returned source links and preserve partial, failed_batches, access,
        search_index and note fields. Empty results do not prove absence. Speaker
        attribution is available only where the returned data identifies a speaker.
        Resolve relative watch_url values against https://arcmira.com.

        Args:
            query: One topic or phrase, at least two characters. Search unrelated topics separately.
            channel_ids: Optional comma-separated YouTube channel IDs, at most eight. IDs, not channel names.
            after: Optional inclusive publication date or ISO 8601 instant, interpreted in UTC.
            before: Optional exclusive publication date or ISO 8601 instant, interpreted in UTC.
            source: Optional transcript source class. Premium access can be refused by the account's plan.

        Returns:
            str: Complete JSON response including passages, timestamps, source links and coverage metadata.
        """
        params = self._search_params(query, channel_ids, after, before, source)
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout, follow_redirects=False) as client:
                response = await client.get(
                    "https://api.arcmira.com/v1/search",
                    params=params,
                    headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                )
        except httpx.RequestError:
            raise RuntimeError("Arcmira search request failed. No automatic retry was made.") from None
        return self._response_json(response)

    def _search_params(
        self, query: str, channel_ids: Optional[str], after: Optional[str], before: Optional[str], source: Optional[str]
    ) -> dict[str, Any]:
        if len(query.strip()) < 2:
            raise ValueError("query must contain at least two non-whitespace characters.")
        params: dict[str, Any] = {"q": query, "limit": self.limit}
        for name, value in (("channel_ids", channel_ids), ("after", after), ("before", before), ("source", source)):
            if value is not None:
                params[name] = value
        return params

    @staticmethod
    def _response_json(response: httpx.Response) -> str:
        try:
            result = response.json()
        except ValueError:
            raise RuntimeError(f"Arcmira returned a non-JSON response (HTTP {response.status_code}).") from None
        if not response.is_success:
            raise RuntimeError(f"Arcmira search failed (HTTP {response.status_code}): {json.dumps(result)}")
        return json.dumps(result)
