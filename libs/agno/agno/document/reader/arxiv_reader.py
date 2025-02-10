from typing import List

from agno.document.base import Document
from agno.document.reader.base import Reader

try:
    import arxiv  # noqa: F401
except ImportError:
    raise ImportError("The `arxiv` package is not installed. Please install it via `pip install arxiv`.")


class ArxivReader(Reader):
    max_results: int = 5  # Top articles
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.Relevance

    def read(self, query: str) -> List[Document]:
        """
        Search a query from arXiv database

        This function gets the top_k articles based on a user's query, sorted by relevance from arxiv

        @param query:
        @return: List of documents
        """

        documents = []
        search = arxiv.Search(query=query, max_results=self.max_results, sort_by=self.sort_by)

        for result in search.results():
            links = ", ".join([x.href for x in result.links])

            documents.append(
                Document(
                    name=result.title,
                    id=result.title,
                    meta_data={"pdf_url": str(result.pdf_url), "article_links": links},
                    content=result.summary,
                )
            )

        return documents
