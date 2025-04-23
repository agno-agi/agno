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
        results_expanded: bool = False,
        **kwargs,
    ):
        super().__init__(name="pubmed", **kwargs)
        self.max_results: Optional[int] = max_results
        self.email: str = email
        self.results_expanded: bool = results_expanded

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
            # Get existing fields
            pub_date = article.find(".//PubDate/Year")
            title = article.find(".//ArticleTitle")

            # Handle abstract sections with labels (methods, results, etc.)
            abstract_sections = article.findall(".//AbstractText")
            abstract_text = ""
            if abstract_sections:
                for section in abstract_sections:
                    label = section.get("Label", "")
                    if label:
                        abstract_text += f"{label}: {section.text}\n\n"
                    else:
                        abstract_text += f"{section.text}\n\n"
                abstract_text = abstract_text.strip()
            else:
                abstract_text = "No abstract available"

            # Get first author
            first_author_elem = article.find(".//AuthorList/Author[1]")
            first_author = "Unknown"
            if first_author_elem is not None:
                last_name = first_author_elem.find("LastName")
                fore_name = first_author_elem.find("ForeName")
                if last_name is not None and fore_name is not None:
                    first_author = f"{last_name.text}, {fore_name.text}"
                elif last_name is not None:
                    first_author = last_name.text

            # Get DOI
            doi_elem = article.find(".//ArticleIdList/ArticleId[@IdType='doi']")
            doi = doi_elem.text if doi_elem is not None else "No DOI available"

            # Get PMID for URL construction
            pmid_elem = article.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else ""
            pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "No URL available"

            # Check if full text is available via PMC
            pmc_elem = article.find(".//ArticleIdList/ArticleId[@IdType='pmc']")
            full_text_url = "Not available"
            if pmc_elem is not None:
                full_text_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_elem.text}/"
            elif doi_elem is not None:
                full_text_url = f"https://doi.org/{doi}"

            # Get keywords
            keywords = []
            for keyword in article.findall(".//KeywordList/Keyword"):
                if keyword.text:
                    keywords.append(keyword.text)

            # Get MeSH terms (useful for understanding medical context)
            mesh_terms = []
            for mesh in article.findall(".//MeshHeading/DescriptorName"):
                if mesh.text:
                    mesh_terms.append(mesh.text)

            # Get journal info
            journal_elem = article.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else "Unknown Journal"

            # Publication type (research article, review, etc.)
            pub_types = []
            for pub_type in article.findall(".//PublicationTypeList/PublicationType"):
                if pub_type.text:
                    pub_types.append(pub_type.text)

            articles.append(
                {
                    "Published": pub_date.text if pub_date is not None else "No date available",
                    "Title": title.text if title is not None else "No title available",
                    "Summary": abstract_text,
                    "First_Author": first_author,
                    "DOI": doi,
                    "PubMed_URL": pubmed_url,
                    "Full_Text_URL": full_text_url,
                    "Keywords": ", ".join(keywords) if keywords else "No keywords available",
                    "MeSH_Terms": ", ".join(mesh_terms) if mesh_terms else "No MeSH terms available",
                    "Journal": journal,
                    "Publication_Type": ", ".join(pub_types) if pub_types else "Not specified",
                }
            )

        return articles

    def search_pubmed(self, query: str, max_results: Optional[int] = 10) -> str:
        """Use this function to search PubMed for articles.

        Args:
            query (str): The search query.
            max_results (int): The maximum number of results to return (default 10).

        Returns:
            str: A JSON string containing the search results.
        """
        try:
            log_debug(f"Searching PubMed for: {query}")
            ids = self.fetch_pubmed_ids(query, self.max_results or max_results, self.email)
            details_root = self.fetch_details(ids)
            articles = self.parse_details(details_root)

            # Create result strings based on configured detail level
            results = []
            for article in articles:
                if self.results_expanded:
                    # Comprehensive format with all metadata
                    article_text = (
                        f"Published: {article.get('Published')}\n"
                        f"Title: {article.get('Title')}\n"
                        f"First Author: {article.get('First_Author')}\n"
                        f"Journal: {article.get('Journal')}\n"
                        f"Publication Type: {article.get('Publication_Type')}\n"
                        f"DOI: {article.get('DOI')}\n"
                        f"PubMed URL: {article.get('PubMed_URL')}\n"
                        f"Full Text URL: {article.get('Full_Text_URL')}\n"
                        f"Keywords: {article.get('Keywords')}\n"
                        f"MeSH Terms: {article.get('MeSH_Terms')}\n"
                        f"Summary:\n{article.get('Summary')}"
                    )
                else:
                    # Concise format with just essential information
                    article_text = (
                        f"Title: {article.get('Title')}\n"
                        f"Published: {article.get('Published')}\n"
                        f"Summary: {article.get('Summary')[:200]}..."
                        if len(article.get("Summary", "")) > 200
                        else f"Summary: {article.get('Summary')}"
                    )
                results.append(article_text)

            return json.dumps(results)
        except Exception as e:
            return f"Could not fetch articles. Error: {e}"
