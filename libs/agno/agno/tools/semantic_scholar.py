import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


DEFAULT_PAPER_FIELDS = (
    "paperId,title,abstract,authors,year,venue,publicationDate,url,externalIds,"
    "citationCount,referenceCount,isOpenAccess,openAccessPdf,fieldsOfStudy,tldr"
)


class SemanticScholarTools(Toolkit):
    """
    SemanticScholarTools is a toolkit for searching academic papers with the
    Semantic Scholar Academic Graph API.

    Args:
        api_key (Optional[str]): Semantic Scholar API key. If not provided,
            uses SEMANTIC_SCHOLAR_API_KEY from the environment. Most endpoints
            can be used without a key, but a key gives more stable rate limits.
        max_results (int): Default number of papers to return. Default is 5.
        timeout (int): Request timeout in seconds. Default is 30.
        enable_search_papers (bool): Enable paper search. Default is True.
        enable_get_paper (bool): Enable fetching paper details. Default is True.
        enable_get_author_papers (bool): Enable fetching papers by author. Default is False.
        all (bool): If True, enable every Semantic Scholar tool.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 5,
        timeout: int = 30,
        enable_search_papers: bool = True,
        enable_get_paper: bool = True,
        enable_get_author_papers: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SEMANTIC_SCHOLAR_API_KEY")
        self.max_results = max_results
        self.timeout = timeout
        self.base_url = "https://api.semanticscholar.org/graph/v1"

        tools: List[Any] = []
        if all or enable_search_papers:
            tools.append(self.search_papers)
        if all or enable_get_paper:
            tools.append(self.get_paper)
        if all or enable_get_author_papers:
            tools.append(self.get_author_papers)

        super().__init__(name="semantic_scholar_tools", tools=tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a GET request to the Semantic Scholar API."""
        try:
            url = f"{self.base_url}/{path.lstrip('/')}"
            log_debug(f"Requesting Semantic Scholar path={path}")
            response = httpx.get(url, params=params, headers=self._headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as e:
            log_error(f"Semantic Scholar HTTP error: {e}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            log_error(f"Semantic Scholar request error: {e}")
            return {"error": str(e)}
        except ValueError as e:
            log_error(f"Semantic Scholar JSON decode error: {e}")
            return {"error": f"Invalid JSON response: {e}"}

    @staticmethod
    def _compact_paper(paper: Dict[str, Any]) -> Dict[str, Any]:
        external_ids = paper.get("externalIds") or {}
        open_access_pdf = paper.get("openAccessPdf") or {}
        tldr = paper.get("tldr") or {}

        authors = [
            {
                "author_id": author.get("authorId"),
                "name": author.get("name"),
            }
            for author in paper.get("authors", [])
        ]

        return {
            "paper_id": paper.get("paperId"),
            "title": paper.get("title"),
            "abstract": paper.get("abstract"),
            "year": paper.get("year"),
            "publication_date": paper.get("publicationDate"),
            "venue": paper.get("venue"),
            "url": paper.get("url"),
            "doi": external_ids.get("DOI"),
            "arxiv_id": external_ids.get("ArXiv"),
            "pubmed_id": external_ids.get("PubMed"),
            "authors": authors,
            "citation_count": paper.get("citationCount"),
            "reference_count": paper.get("referenceCount"),
            "fields_of_study": paper.get("fieldsOfStudy"),
            "is_open_access": paper.get("isOpenAccess"),
            "open_access_pdf_url": open_access_pdf.get("url"),
            "tldr": tldr.get("text"),
        }

    def search_papers(
        self,
        query: str,
        max_results: Optional[int] = None,
        fields: Optional[str] = None,
    ) -> str:
        """Search Semantic Scholar for academic papers.

        Args:
            query (str): Search query, such as "retrieval augmented generation".
            max_results (Optional[int]): Number of results to return. Defaults to the instance setting.
            fields (Optional[str]): Comma-separated Semantic Scholar paper fields to request.

        Returns:
            str: JSON string containing matching papers and metadata.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        limit = max_results if max_results is not None else self.max_results
        if limit < 1:
            return json.dumps({"error": "max_results must be greater than 0"})

        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": fields or DEFAULT_PAPER_FIELDS,
        }

        data = self._get("paper/search", params)
        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "total": data.get("total"),
            "offset": data.get("offset"),
            "papers": [self._compact_paper(paper) for paper in data.get("data", [])],
        }
        return json.dumps(result, indent=2)

    def get_paper(self, paper_id: str, fields: Optional[str] = None) -> str:
        """Fetch details for a Semantic Scholar paper.

        Args:
            paper_id (str): Semantic Scholar paper ID, Corpus ID, DOI:<doi>, ARXIV:<id>, or PMID:<id>.
            fields (Optional[str]): Comma-separated Semantic Scholar paper fields to request.

        Returns:
            str: JSON string containing paper metadata.
        """
        if not paper_id:
            return json.dumps({"error": "Please provide a paper_id"})

        data = self._get(f"paper/{paper_id}", {"fields": fields or DEFAULT_PAPER_FIELDS})
        if "error" in data:
            return json.dumps({"error": data["error"]})

        return json.dumps(self._compact_paper(data), indent=2)

    def get_author_papers(
        self,
        author_id: str,
        max_results: Optional[int] = None,
        fields: Optional[str] = None,
    ) -> str:
        """Fetch papers written by a Semantic Scholar author.

        Args:
            author_id (str): Semantic Scholar author ID.
            max_results (Optional[int]): Number of papers to return. Defaults to the instance setting.
            fields (Optional[str]): Comma-separated paper fields to request.

        Returns:
            str: JSON string containing the author's papers.
        """
        if not author_id:
            return json.dumps({"error": "Please provide an author_id"})

        limit = max_results if max_results is not None else self.max_results
        if limit < 1:
            return json.dumps({"error": "max_results must be greater than 0"})

        params = {
            "limit": min(limit, 100),
            "fields": fields or DEFAULT_PAPER_FIELDS,
        }

        data = self._get(f"author/{author_id}/papers", params)
        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "author_id": author_id,
            "papers": [self._compact_paper(paper) for paper in data.get("data", [])],
        }
        return json.dumps(result, indent=2)
