import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

DEFAULT_BASE_URL = "https://api.you.com"
MAX_INPUT_LENGTH = 40000
VALID_RESEARCH_EFFORTS = ("deep", "exhaustive")


class YouFinanceResearchTools(Toolkit):
    """
    YouFinanceResearchTools exposes the You.com Finance Research API as a first-class Agno tool.

    The Finance Research API is purpose-built for financial questions. Like the Research
    API, it runs multiple searches, reads through sources, and synthesises everything
    into a thorough, well-cited answer — but its retrieval index is optimised for
    financial data: earnings reports, SEC filings, analyst coverage, market data, and
    financial news.

    Use it when you need credible, sourced answers to financial questions: company
    fundamentals, market trends, competitive analysis, earnings summaries, or
    macroeconomic research.

    Get an API key at https://you.com/platform/api-keys and set ``YDC_API_KEY``.

    Reference: https://you.com/docs/api-reference/finance-research/v1-finance_research

    Args:
        api_key (Optional[str]): You.com API key.  Falls back to the ``YDC_API_KEY`` env var.
        base_url (Optional[str]): Override the API base URL.  Falls back to the ``YDC_BASE_URL``
            env var, then defaults to ``https://api.you.com``.
        research_effort (str): Controls depth vs. speed trade-off.
            One of ``"deep"`` or ``"exhaustive"``.  Default is ``"deep"``.
        text_length_limit (int): Max characters to keep per source snippet. Default is 1000.
        timeout (int): Client-side HTTP timeout in seconds. Default is 15.
        format (str): Output format (``"json"`` or ``"markdown"``). Default is ``"json"``.
        show_results (bool): Log the full response for debugging. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        research_effort: Literal["deep", "exhaustive"] = "deep",
        text_length_limit: int = 1000,
        timeout: int = 15,
        format: Literal["json", "markdown"] = "json",
        show_results: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("YDC_API_KEY")
        if not self.api_key:
            log_error("YDC_API_KEY not set. Please set the YDC_API_KEY environment variable.")

        if research_effort not in VALID_RESEARCH_EFFORTS:
            raise ValueError(f"research_effort must be one of {VALID_RESEARCH_EFFORTS}, got {research_effort!r}")

        self.base_url: str = (base_url or getenv("YDC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.research_effort: str = research_effort
        self.text_length_limit: int = text_length_limit
        self.timeout: int = timeout
        self.format: Literal["json", "markdown"] = format
        self.show_results: bool = show_results

        super().__init__(name="youcom_finance_research", tools=[self.you_finance_research], **kwargs)

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

    def you_finance_research(self, input: str, research_effort: Optional[str] = None) -> str:
        """Run a finance research query using the You.com Finance Research API.

        The Finance Research API performs multi-step reasoning optimised for financial
        data: it runs multiple searches across earnings reports, SEC filings, analyst
        coverage, market data, and financial news, then returns a comprehensive,
        well-cited answer.

        Args:
            input (str): The financial research question (max 40 000 characters).
            research_effort (Optional[str]): Override the configured research effort
                level for this call (``"deep"`` or ``"exhaustive"``).

        Returns:
            str: Finance research answer formatted as JSON or markdown, including source citations.
        """
        try:
            if len(input) > MAX_INPUT_LENGTH:
                raise ValueError(f"input exceeds maximum length of {MAX_INPUT_LENGTH} characters (got {len(input)})")

            effective_effort = research_effort or self.research_effort
            if effective_effort not in VALID_RESEARCH_EFFORTS:
                raise ValueError(f"research_effort must be one of {VALID_RESEARCH_EFFORTS}, got {effective_effort!r}")

            if self.show_results:
                log_info(f"Finance research via You.com: {input}")

            body: Dict[str, Any] = {
                "input": input,
                "research_effort": effective_effort,
            }

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/v1/finance_research",
                    headers=self._headers(),
                    json=body,
                )
            response.raise_for_status()
            data = response.json()
            return self._format_response(input, data)
        except httpx.HTTPError as e:
            log_error(f"You.com finance research request failed: {e}")
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to run You.com finance research")
            return f"Error: {e}"

    def _format_response(self, query: str, data: Dict[str, Any]) -> str:
        """Parse the Finance Research API response into a clean, LLM-friendly output.

        Response shape (from API):
            {
                "output": {
                    "content": <str>,
                    "content_type": "text",
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
            lines = [f"# Finance Research: {query}\n"]

            # Content section.
            if content:
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
