import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

DEFAULT_BASE_URL = "https://api.you.com"
MAX_INPUT_LENGTH = 40000


class YouResearchTools(Toolkit):
    """
    YouResearchTools exposes the You.com Research API as a first-class Agno tool.

    The Research API goes beyond a single web search: it runs multiple searches,
    reads through sources, and synthesises everything into a thorough, well-cited
    answer.  Use it when a question is too complex for a simple lookup and when you
    need a response you can trust and verify.

    Get an API key at https://you.com/platform/api-keys and set ``YDC_API_KEY``.

    Reference: https://you.com/docs/api-reference/research/v1-research

    Args:
        api_key (Optional[str]): You.com API key.  Falls back to the ``YDC_API_KEY`` env var.
        base_url (Optional[str]): Override the API base URL.  Falls back to the ``YDC_BASE_URL``
            env var, then defaults to ``https://api.you.com``.
        research_effort (str): Controls depth vs. speed trade-off.
            One of ``"lite"``, ``"standard"``, ``"deep"``, ``"exhaustive"``.
            Default is ``"standard"``.
        include_domains (Optional[List[str]]): Restrict sources to these domains (max 500).
            Cannot be combined with ``exclude_domains`` (returns 422).
        exclude_domains (Optional[List[str]]): Exclude sources from these domains (max 500).
            Cannot be combined with ``include_domains`` (returns 422).
        boost_domains (Optional[List[str]]): Boost ranking for these domains without filtering
            others out. Can be combined with ``exclude_domains`` but **not** ``include_domains``.
        freshness (Optional[str]): Freshness filter (``"day"``, ``"week"``, ``"month"``,
            ``"year"``, or ``"YYYY-MM-DDtoYYYY-MM-DD"``).
        country (Optional[str]): Country code for geographical focus (e.g. ``"IN"``, ``"US"``).
        output_schema (Optional[Dict[str, Any]]): JSON Schema requesting structured output in
            ``output.content``.  Supported only with ``research_effort`` ``"standard"``,
            ``"deep"``, or ``"exhaustive"`` (``"lite"`` returns 422).
        text_length_limit (int): Max characters to keep per source snippet. Default is 1000.
        timeout (int): Client-side HTTP timeout in seconds. Default is 120
            (research requests are slower than simple searches).
        format (str): Output format (``"json"`` or ``"markdown"``). Default is ``"json"``.
        show_results (bool): Log the full response for debugging. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        research_effort: Literal["lite", "standard", "deep", "exhaustive"] = "standard",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        boost_domains: Optional[List[str]] = None,
        freshness: Optional[str] = None,
        country: Optional[str] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        text_length_limit: int = 1000,
        timeout: int = 120,
        format: Literal["json", "markdown"] = "json",
        show_results: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("YDC_API_KEY")
        if not self.api_key:
            log_error("YDC_API_KEY not set. Please set the YDC_API_KEY environment variable.")

        # include_domains and exclude_domains cannot be combined (API returns 422).
        if include_domains and exclude_domains:
            raise ValueError("include_domains cannot be combined with exclude_domains")

        # boost_domains cannot be combined with include_domains (API returns 422).
        if include_domains and boost_domains:
            raise ValueError("boost_domains cannot be combined with include_domains")

        # Domain lists are capped at 500 entries per the spec.
        if include_domains and len(include_domains) > 500:
            raise ValueError("include_domains cannot exceed 500 items")
        if exclude_domains and len(exclude_domains) > 500:
            raise ValueError("exclude_domains cannot exceed 500 items")
        if boost_domains and len(boost_domains) > 500:
            raise ValueError("boost_domains cannot exceed 500 items")

        # output_schema is not supported with research_effort "lite" (API returns 422).
        if output_schema and research_effort == "lite":
            raise ValueError('output_schema is not supported with research_effort "lite"')

        self.base_url: str = (base_url or getenv("YDC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.research_effort: str = research_effort
        self.include_domains: Optional[List[str]] = include_domains
        self.exclude_domains: Optional[List[str]] = exclude_domains
        self.boost_domains: Optional[List[str]] = boost_domains
        self.freshness: Optional[str] = freshness
        self.country: Optional[str] = country
        self.output_schema: Optional[Dict[str, Any]] = output_schema
        self.text_length_limit: int = text_length_limit
        self.timeout: int = timeout
        self.format: Literal["json", "markdown"] = format
        self.show_results: bool = show_results

        super().__init__(name="youcom_research", tools=[self.you_research], **kwargs)

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _truncate(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        if self.text_length_limit and len(text) > self.text_length_limit:
            return text[: self.text_length_limit]
        return text

    def you_research(self, input: str, research_effort: Optional[str] = None) -> str:
        """Run a deep-research query using the You.com Research API.

        The Research API performs multi-step reasoning: it runs multiple searches,
        reads through sources, and returns a comprehensive, well-cited answer.

        Args:
            input (str): The research question (max 40 000 characters).
            research_effort (Optional[str]): Override the configured research effort
                level for this call (``"lite"``, ``"standard"``, ``"deep"``,
                ``"exhaustive"``).

        Returns:
            str: Research answer formatted as JSON or markdown, including source citations.
        """
        try:
            if len(input) > MAX_INPUT_LENGTH:
                raise ValueError(f"input exceeds maximum length of {MAX_INPUT_LENGTH} characters (got {len(input)})")

            effective_effort = research_effort or self.research_effort
            if self.output_schema and effective_effort == "lite":
                raise ValueError('output_schema is not supported with research_effort "lite"')

            if self.show_results:
                log_info(f"Researching via You.com: {input}")

            body: Dict[str, Any] = {
                "input": input,
                "research_effort": effective_effort,
            }

            # Build source_control only when at least one field is set.
            source_control: Dict[str, Any] = {}
            if self.include_domains:
                source_control["include_domains"] = self.include_domains
            if self.exclude_domains:
                source_control["exclude_domains"] = self.exclude_domains
            if self.boost_domains:
                source_control["boost_domains"] = self.boost_domains
            if self.freshness:
                source_control["freshness"] = self.freshness
            if self.country:
                source_control["country"] = self.country
            if source_control:
                body["source_control"] = source_control

            if self.output_schema:
                body["output_schema"] = self.output_schema

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/v1/research",
                    headers=self._headers(),
                    json=body,
                )
            response.raise_for_status()
            data = response.json()
            return self._format_response(input, data)
        except httpx.HTTPError as e:
            log_error(f"You.com research request failed: {e}")
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to run You.com research")
            return f"Error: {e}"

    def _format_response(self, query: str, data: Dict[str, Any]) -> str:
        """Parse the Research API response into a clean, LLM-friendly output.

        Response shape (from API):
            {
                "output": {
                    "content": <str | dict>,
                    "content_type": "text" | "object",
                    "sources": [{"url": ..., "title": ..., "snippets": [...]}]
                }
            }
        """
        output = data.get("output") or {}
        content = output.get("content", "")
        content_type = output.get("content_type", "text")
        sources: List[Dict[str, Any]] = output.get("sources") or []

        # Truncate snippets in sources.
        cleaned_sources: List[Dict[str, Any]] = []
        for src in sources:
            if not isinstance(src, dict):
                continue
            entry: Dict[str, Any] = {}
            if src.get("url"):
                entry["url"] = src["url"]
            if src.get("title"):
                entry["title"] = src["title"]
            snippets = src.get("snippets")
            if isinstance(snippets, list) and snippets:
                entry["snippets"] = [self._truncate(s) for s in snippets if isinstance(s, str)]
            cleaned_sources.append(entry)

        if self.format == "markdown":
            lines = [f"# Research: {query}\n"]

            # Content section.
            if content_type == "object" and isinstance(content, dict):
                lines.append("## Answer (structured)\n")
                lines.append(f"```json\n{json.dumps(content, indent=2, ensure_ascii=False)}\n```\n")
            elif content:
                lines.append(str(content))
                lines.append("")

            # Sources section.
            if cleaned_sources:
                lines.append("## Sources\n")
                for i, src in enumerate(cleaned_sources, 1):
                    title = src.get("title") or src.get("url") or "Untitled"
                    url = src.get("url", "")
                    lines.append(f"{i}. [{title}]({url})")
                lines.append("")

            result = "\n".join(lines)
            if self.show_results:
                log_info(result)
            return result

        # JSON output.
        result_dict: Dict[str, Any] = {"content": content, "content_type": content_type}
        if cleaned_sources:
            result_dict["sources"] = cleaned_sources
        result = json.dumps(result_dict, indent=4, ensure_ascii=False)
        if self.show_results:
            log_info(result)
        return result
