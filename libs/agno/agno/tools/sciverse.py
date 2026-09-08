import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

DEFAULT_BASE_URL = "https://api.sciverse.space"

# Maps the user-facing search mode to the API's retrieval knobs
# (`retrieval`: recall backend, `sub_queries`: LLM query-rewrite fan-out).
_SEARCH_MODES: Dict[str, Dict[str, Any]] = {
    "fast": {"retrieval": "es"},
    "balanced": {"retrieval": "hybrid"},
    "quality": {"retrieval": "hybrid", "sub_queries": 3},
}


class SciverseTools(Toolkit):
    """Tools for searching scientific literature via the Sciverse open platform.

    Sciverse indexes paper metadata *and* full text, so it can return citable passages
    from paper bodies rather than just abstracts, and read the surrounding original text
    by byte offset.

    Get an API token at https://sciverse.space and set `SCIVERSE_API_TOKEN`.

    Args:
        enable_semantic_search (bool): Enable natural-language passage retrieval. Default True.
        enable_search_papers (bool): Enable structured metadata search. Default True.
        enable_read_paper_content (bool): Enable reading original full text. Default True.
        enable_list_paper_relations (bool): Enable citation/reference listing. Default False.
        all (bool): Enable all tools. Overrides individual flags when True. Default False.
        api_key (Optional[str]): Sciverse API token. Falls back to `SCIVERSE_API_TOKEN`.
        base_url (Optional[str]): API base URL. Falls back to `SCIVERSE_BASE_URL`.
        timeout (float): Request timeout in seconds. Default 30.0.
    """

    def __init__(
        self,
        enable_semantic_search: bool = True,
        enable_search_papers: bool = True,
        enable_read_paper_content: bool = True,
        enable_list_paper_relations: bool = False,
        all: bool = False,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SCIVERSE_API_TOKEN")
        if not self.api_key:
            log_error("SCIVERSE_API_TOKEN not set. Please set the SCIVERSE_API_TOKEN environment variable.")

        self.base_url = (base_url or getenv("SCIVERSE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

        tools: List[Any] = []
        if all or enable_semantic_search:
            tools.append(self.semantic_search)
        if all or enable_search_papers:
            tools.append(self.search_papers)
        if all or enable_read_paper_content:
            tools.append(self.read_paper_content)
        if all or enable_list_paper_relations:
            tools.append(self.list_paper_relations)

        super().__init__(name="sciverse", tools=tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Lets Sciverse attribute traffic to this integration.
            "X-Sciverse-Source": "oss_agno",
        }

    def _request(self, method: str, path: str, **kwargs) -> str:
        """Issue a request and return the response body as a JSON string.

        Errors are returned as a JSON object with an `error` key so the model can see
        what went wrong and adjust, rather than the tool call raising.
        """
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                response = client.request(method, path, headers=self._headers(), **kwargs)
                response.raise_for_status()
                return json.dumps(response.json(), indent=2, ensure_ascii=False)
        except httpx.HTTPStatusError as e:
            message = e.response.text
            try:
                body = e.response.json()
                message = body.get("message") or body.get("code") or message
            except Exception:
                pass
            log_error(f"Sciverse request failed ({e.response.status_code}): {message}")
            return json.dumps({"error": f"HTTP {e.response.status_code}", "message": message}, ensure_ascii=False)
        except Exception as e:
            log_error(f"Sciverse request failed: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def semantic_search(self, query: str, top_k: int = 10, mode: str = "balanced") -> str:
        """Search scientific literature with a natural-language question and get back
        the most relevant passages from paper full text.

        Use this when you have a question rather than exact filter criteria, and you want
        quotable evidence. Hits that carry a doc_id locate the passage in the original
        document, so you can call read_paper_content with that doc_id and offset to read
        more around it (hits without doc_id are preview-only).

        Args:
            query (str): The natural-language question. Works best under 200 characters.
            top_k (int, optional): Number of passages to return, 1-100. Defaults to 10.
            mode (str, optional): One of "fast" (keyword only, ~200ms), "balanced" (hybrid
                retrieval, ~600ms) or "quality" (LLM query rewriting + hybrid, ~2-4s).
                Defaults to "balanced"; unknown values fall back to "balanced".
        Returns:
            str: JSON with a list of hits, each holding chunk (the passage text), title,
                score, abstract, and doc_id plus offset when the full text is available.
        """
        log_debug(f"Sciverse semantic search: {query}")
        payload: Dict[str, Any] = {"query": query, "top_k": top_k}
        payload.update(_SEARCH_MODES.get(mode, _SEARCH_MODES["balanced"]))
        return self._request("POST", "/agentic-search", json=payload)

    def search_papers(
        self,
        query: Optional[str] = None,
        authors: Optional[List[str]] = None,
        journals: Optional[List[str]] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> str:
        """Search scientific paper metadata by structured criteria such as author, journal
        or publication year.

        Use this when you know what to filter on. For an open-ended question, use
        semantic_search instead.

        Args:
            query (str, optional): Free-text query matched against title and abstract.
            authors (list[str], optional): Author names; a paper matches any of them.
                Matching is exact against the stored name variants, so pass the full name
                (e.g. "Geoffrey Hinton"). A surname alone matches only the subset of papers
                that happen to store that bare variant, and mixes in every other author who
                shares the surname, so it is not a way to broaden a search.
            journals (list[str], optional): Journal or venue names; a paper matches any of
                them. Exact match on the normalized venue name (e.g. "Nature Communications").
            year_from (int, optional): Earliest publication year, inclusive.
            year_to (int, optional): Latest publication year, inclusive.
            page (int, optional): 1-based page number. Defaults to 1.
            page_size (int, optional): Results per page, max 200. Defaults to 10.
        Returns:
            str: JSON with paper records holding unique_id (always present), doc_id (only when
                full text exists), title, author, abstract, publication venue and year.
        """
        log_debug(f"Sciverse paper search: query={query} authors={authors} years={year_from}-{year_to}")
        payload: Dict[str, Any] = {"page": page, "page_size": page_size}
        if query:
            payload["query"] = query

        filters: List[Dict[str, Any]] = []
        if authors:
            filters.append({"field": "author", "operator": "FILTER_OP_IN", "value": list(authors)})
        if journals:
            filters.append(
                {
                    "field": "publication_venue_name_unified",
                    "operator": "FILTER_OP_IN",
                    "value": list(journals),
                }
            )
        if year_from is not None:
            filters.append({"field": "publication_published_year", "operator": "FILTER_OP_GTE", "value": year_from})
        if year_to is not None:
            filters.append({"field": "publication_published_year", "operator": "FILTER_OP_LTE", "value": year_to})
        if filters:
            payload["filters"] = filters

        return self._request("POST", "/meta-search", json=payload)

    def read_paper_content(self, doc_id: str, offset: int = 0, limit: int = 4096) -> str:
        """Read the original full text of a paper, one segment at a time.

        Pair this with semantic_search: take the doc_id and offset of a hit and read around
        it to get more context than the returned passage. Offsets count Unicode characters
        (same unit as Python's len(str)), matching the offset values semantic_search returns.

        Args:
            doc_id (str): Document ID from semantic_search or search_papers.
            offset (int, optional): Character offset to start reading from. Defaults to 0.
            limit (int, optional): Characters to read, max 524288. Defaults to 4096.
        Returns:
            str: JSON with text (the segment), next_offset (pass as offset to continue)
                and more (whether content follows).
        """
        log_debug(f"Sciverse read content: doc_id={doc_id} offset={offset}")
        params = {"doc_id": doc_id, "offset": offset, "limit": limit}
        return self._request("GET", "/content", params=params)

    def list_paper_relations(
        self,
        unique_id: str,
        relation: str = "REFERENCES",
        page: int = 1,
        page_size: int = 25,
    ) -> str:
        """List the citation relationships of a paper.

        Args:
            unique_id (str): The paper's unique_id from search_papers or semantic_search.
                Note this is unique_id, not doc_id.
            relation (str, optional): "REFERENCES" (works this paper cites), "CITATIONS"
                (works citing this paper) or "RELATED_WORKS". Defaults to "REFERENCES".
            page (int, optional): 1-based page number. Defaults to 1.
            page_size (int, optional): Results per page. Defaults to 25.
        Returns:
            str: JSON with the related paper records and pagination info.
        """
        log_debug(f"Sciverse paper relations: unique_id={unique_id} relation={relation}")
        payload = {
            "unique_id": unique_id,
            "relation": relation,
            "page": page,
            "page_size": page_size,
        }
        return self._request("POST", "/meta-paper-relations", json=payload)
