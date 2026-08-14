import json
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import arxiv
except ImportError:
    raise ImportError("`arxiv` not installed. Please install using `pip install arxiv`")

try:
    from pypdf import PdfReader
except ImportError:
    raise ImportError("`pypdf` not installed. Please install using `pip install pypdf`")


class ArxivTools(Toolkit):
    def __init__(
        self,
        download_dir: Optional[Path] = None,
        search_arxiv: bool = True,
        read_arxiv_papers: bool = True,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat: enable_X -> X
        if "enable_search_arxiv" in kwargs:
            search_arxiv = kwargs.pop("enable_search_arxiv")
        if "enable_read_arxiv_papers" in kwargs:
            read_arxiv_papers = kwargs.pop("enable_read_arxiv_papers")

        self.client: arxiv.Client = arxiv.Client()
        self.download_dir: Path = download_dir or Path(__file__).parent.joinpath("arxiv_pdfs")

        tools: List[Callable] = []
        if all or search_arxiv:
            tools.append(self.search_arxiv_and_return_articles)
        if all or read_arxiv_papers:
            tools.append(self.read_arxiv_papers)

        super().__init__(name="arxiv_tools", tools=tools, **kwargs)

    def search_arxiv_and_return_articles(self, query: str, num_articles: int = 10) -> str:
        """Search arXiv for a query and return the top articles.

        Args:
            query: The search query.
            num_articles: Number of articles to return (default 10).

        Returns:
            JSON array of articles with title, id, authors, pdf_url, summary.
        """
        articles = []
        log_debug(f"Searching arxiv for: {query}")
        for result in self.client.results(
            arxiv.Search(
                query=query,
                max_results=num_articles,
                sort_by=arxiv.SortCriterion.Relevance,
                sort_order=arxiv.SortOrder.Descending,
            )
        ):
            try:
                article = {
                    "title": result.title,
                    "id": result.get_short_id(),
                    "entry_id": result.entry_id,
                    "authors": [author.name for author in result.authors],
                    "primary_category": result.primary_category,
                    "categories": result.categories,
                    "published": result.published.isoformat() if result.published else None,
                    "pdf_url": result.pdf_url,
                    "links": [link.href for link in result.links],
                    "summary": result.summary,
                    "comment": result.comment,
                }
                articles.append(article)
            except Exception:
                logger.exception("Error processing article")
        return json.dumps(articles)

    def read_arxiv_papers(self, id_list: List[str], pages_to_read: Optional[int] = None) -> str:
        """Download and read arxiv papers by ID.

        Args:
            id_list: Paper IDs, e.g. ["2103.03404v1", "2103.03404v2"].
            pages_to_read: Max pages to extract (None = all).

        Returns:
            JSON array of papers with metadata and content.
        """
        download_dir = self.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        articles = []
        log_debug(f"Searching arxiv for: {id_list}")
        for result in self.client.results(arxiv.Search(id_list=id_list)):
            try:
                article: Dict[str, Any] = {
                    "title": result.title,
                    "id": result.get_short_id(),
                    "entry_id": result.entry_id,
                    "authors": [author.name for author in result.authors],
                    "primary_category": result.primary_category,
                    "categories": result.categories,
                    "published": result.published.isoformat() if result.published else None,
                    "pdf_url": result.pdf_url,
                    "links": [link.href for link in result.links],
                    "summary": result.summary,
                    "comment": result.comment,
                }
                if result.pdf_url:
                    # Download PDF (arxiv 4.0 removed download_pdf method)
                    pdf_filename = f"{result.get_short_id().replace('/', '_')}.pdf"
                    pdf_path = download_dir / pdf_filename
                    log_debug(f"Downloading: {result.pdf_url}")
                    urllib.request.urlretrieve(result.pdf_url, pdf_path)
                    log_debug(f"To: {pdf_path}")

                    pdf_reader = PdfReader(pdf_path)
                    article["content"] = []
                    for page_number, page in enumerate(pdf_reader.pages, start=1):
                        if pages_to_read and page_number > pages_to_read:
                            break
                        article["content"].append({"page": page_number, "text": page.extract_text()})
                articles.append(article)
            except Exception:
                logger.exception("Error processing article")
        return json.dumps(articles)
