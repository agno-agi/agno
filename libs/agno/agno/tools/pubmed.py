import json
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug


class PubmedTools(Toolkit):
    def __init__(
        self,
        email: str = "your_email@example.com",
        max_results: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(name="pubmed", **kwargs)
        self.max_results: Optional[int] = max_results
        self.email: str = email

        self.register(self.search_pubmed)

    def fetch_pubmed_ids(self, query: str, max_results: int, email: str) -> List[str]:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "email": email,
            "usehistory": "y",
        }
        response = httpx.get(url, params=params)  # type: ignore
        root = ElementTree.fromstring(response.content)
        return [id_elem.text for id_elem in root.findall(".//Id") if id_elem.text is not None]

    def fetch_details(self, pubmed_ids: List[str]) -> ElementTree.Element:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        params = {"db": "pubmed", "id": ",".join(pubmed_ids), "retmode": "xml"}
        response = httpx.get(url, params=params)
        return ElementTree.fromstring(response.content)

    def parse_details(self, xml_root: ElementTree.Element) -> List[Dict[str, Any]]:
        articles = []
        for article in xml_root.findall(".//PubmedArticle"):
            pub_date = article.find(".//PubDate/Year")
            title = article.find(".//ArticleTitle")
            abstract = article.find(".//AbstractText")
            articles.append(
                {
                    "Published": (pub_date.text if pub_date is not None else "No date available"),
                    "Title": title.text if title is not None else "No title available",
                    "Summary": (abstract.text if abstract is not None else "No abstract available"),
                }
            )
        return articles

    def search_pubmed(self, query: str, max_results: int = 10) -> str:
        """Use this function to search PubMed for articles.

        Args:
            query (str): The search query.
            max_results (int): The maximum number of results to return.

        Returns:
            str: A JSON string containing the search results.
        """
        try:
            log_debug(f"Searching PubMed for: {query}")
            ids = self.fetch_pubmed_ids(query, self.max_results or max_results, self.email)
            details_root = self.fetch_details(ids)
            articles = self.parse_details(details_root)
            results = [
                f"Published: {article.get('Published')}\nTitle: {article.get('Title')}\nSummary:\n{article.get('Summary')}"
                for article in articles
            ]
            return json.dumps(results)
        except Exception as e:
            return f"Cound not fetch articles. Error: {e}"
