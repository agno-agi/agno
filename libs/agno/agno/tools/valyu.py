import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from valyu import Valyu
except ImportError:
    raise ImportError("`valyu` not installed. Please install using `pip install valyu`")


# Default sources for each specialized search type
LIFE_SCIENCES_SOURCES = [
    "valyu/valyu-pubmed",
    "valyu/valyu-biorxiv",
    "valyu/valyu-medrxiv",
    "valyu/valyu-clinical-trials",
    "valyu/valyu-drug-labels",
    "valyu/valyu-chembl",
    "valyu/valyu-pubchem",
    "valyu/valyu-drugbank",
    "valyu/valyu-open-targets",
    "valyu/valyu-npi-registry",
    "valyu/valyu-who-icd",
]

SEC_SOURCES = ["valyu/valyu-sec-filings"]

PATENT_SOURCES = ["valyu/valyu-patents"]

FINANCE_SOURCES = [
    "valyu/valyu-stocks",
    "valyu/valyu-sec-filings",
    "valyu/valyu-earnings-US",
    "valyu/valyu-balance-sheet-US",
    "valyu/valyu-income-statement-US",
    "valyu/valyu-cash-flow-US",
    "valyu/valyu-dividends-US",
    "valyu/valyu-insider-transactions-US",
    "valyu/valyu-market-movers-US",
    "valyu/valyu-crypto",
    "valyu/valyu-forex",
]

ECONOMICS_SOURCES = [
    "valyu/valyu-bls",
    "valyu/valyu-fred",
    "valyu/valyu-world-bank",
    "valyu/valyu-worldbank-indicators",
    "valyu/valyu-usaspending",
]

PAPER_SOURCES = [
    "valyu/valyu-arxiv",
    "valyu/valyu-biorxiv",
    "valyu/valyu-medrxiv",
    "valyu/valyu-pubmed",
    "wiley/wiley-finance-papers",
]


class ValyuTools(Toolkit):
    """
    Valyu search API toolkit providing web search and access to specialised/proprietary data sources
    including life sciences, SEC filings, patents, finance, economics, and academic papers.

    Args:
        api_key: Valyu API key. Retrieved from VALYU_API_KEY env variable if not provided.
        max_results: Maximum number of results to return per search. Default is 10.
        relevance_threshold: Minimum relevance score for results. Default is 0.5.
        max_price: Maximum price for API calls. Default is 30.0.
        text_length: Maximum length of text content per result. Default is 1000.
        search_type: Default search type ('web', 'proprietary', 'all'). Default is 'all'.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 10,
        relevance_threshold: float = 0.5,
        max_price: float = 30.0,
        text_length: int = 1000,
        search_type: str = "all",
        **kwargs,
    ):
        self.api_key = api_key or getenv("VALYU_API_KEY")
        if not self.api_key:
            raise ValueError("VALYU_API_KEY not set. Please set the VALYU_API_KEY environment variable.")

        self.valyu = Valyu(api_key=self.api_key)
        self.max_results = max_results
        self.relevance_threshold = relevance_threshold
        self.max_price = max_price
        self.text_length = text_length
        self.search_type = search_type

        tools: List[Any] = [
            self.search,
            self.web_search,
            self.life_sciences_search,
            self.sec_search,
            self.patent_search,
            self.finance_search,
            self.economics_search,
            self.paper_search,
        ]

        super().__init__(name="valyu", tools=tools, **kwargs)

    def _parse_results(self, results: List[Any]) -> str:
        """Parse search results into JSON string."""
        parsed_results = []
        for result in results:
            result_dict = {}

            if hasattr(result, "url") and result.url:
                result_dict["url"] = result.url
            if hasattr(result, "title") and result.title:
                result_dict["title"] = result.title
            if hasattr(result, "source") and result.source:
                result_dict["source"] = result.source
            if hasattr(result, "relevance_score"):
                result_dict["relevance_score"] = result.relevance_score

            if hasattr(result, "content") and result.content:
                content = result.content
                if self.text_length and len(content) > self.text_length:
                    content = content[: self.text_length] + "..."
                result_dict["content"] = content

            if hasattr(result, "description") and result.description:
                result_dict["description"] = result.description

            parsed_results.append(result_dict)

        return json.dumps(parsed_results, indent=2)

    def _execute_search(
        self,
        query: str,
        search_type: str,
        sources: Optional[List[str]] = None,
        included_sources: Optional[List[str]] = None,
        excluded_sources: Optional[List[str]] = None,
    ) -> str:
        """Execute a search with the given parameters."""
        try:
            search_params = {
                "query": query,
                "search_type": search_type,
                "max_num_results": self.max_results,
                "relevance_threshold": self.relevance_threshold,
                "max_price": self.max_price,
            }

            # Handle source filtering
            if sources:
                search_params["included_sources"] = sources
            elif included_sources:
                search_params["included_sources"] = included_sources

            if excluded_sources:
                search_params["excluded_sources"] = excluded_sources

            log_debug(f"Valyu search parameters: {search_params}")
            response = self.valyu.search(**search_params)

            if not response.success:
                log_error(f"Valyu search API error: {response.error}")
                return f"Error: {response.error or 'Search request failed'}"

            return self._parse_results(response.results or [])

        except Exception as e:
            error_msg = f"Valyu search failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def search(
        self,
        query: str,
        included_sources: Optional[List[str]] = None,
        excluded_sources: Optional[List[str]] = None,
    ) -> str:
        """General search across all Valyu sources.

        Args:
            query: Natural language search query
            included_sources: Restrict search to specific sources
            excluded_sources: Exclude specific sources from results

        Returns:
            JSON array of search results
        """
        return self._execute_search(
            query=query,
            search_type=self.search_type,
            included_sources=included_sources,
            excluded_sources=excluded_sources,
        )

    def web_search(
        self,
        query: str,
        included_sources: Optional[List[str]] = None,
        excluded_sources: Optional[List[str]] = None,
    ) -> str:
        """Search the web for current information, news, and articles.

        Args:
            query: Natural language search query (e.g., 'latest AI developments')
            included_sources: Restrict to specific domains (e.g., ['nature.com', 'arxiv.org'])
            excluded_sources: Exclude specific domains (e.g., ['reddit.com'])

        Returns:
            JSON array of web search results
        """
        return self._execute_search(
            query=query,
            search_type="web",
            included_sources=included_sources,
            excluded_sources=excluded_sources,
        )

    def life_sciences_search(self, query: str) -> str:
        """Search biomedical and healthcare data.

        Searches PubMed, clinical trials, FDA drug labels, ChEMBL compounds,
        PubChem, DrugBank, Open Targets, NPI registry, and WHO ICD codes.

        Args:
            query: Natural language query (e.g., 'GLP-1 agonists for weight loss')

        Returns:
            JSON array of biomedical search results
        """
        return self._execute_search(
            query=query,
            search_type="proprietary",
            sources=LIFE_SCIENCES_SOURCES,
        )

    def sec_search(self, query: str) -> str:
        """Search SEC filings (10-K, 10-Q, 8-K, proxy statements).

        Args:
            query: Natural language query (e.g., 'Tesla 10-K risk factors')

        Returns:
            JSON array of SEC filing results
        """
        return self._execute_search(
            query=query,
            search_type="proprietary",
            sources=SEC_SOURCES,
        )

    def patent_search(self, query: str) -> str:
        """Search patent databases for inventions and intellectual property.

        Args:
            query: Natural language query (e.g., 'solid-state battery patents')

        Returns:
            JSON array of patent results
        """
        return self._execute_search(
            query=query,
            search_type="proprietary",
            sources=PATENT_SOURCES,
        )

    def finance_search(self, query: str) -> str:
        """Search financial data: stocks, earnings, balance sheets, SEC filings.

        Includes stock prices, earnings, balance sheets, income statements,
        cash flows, dividends, insider transactions, crypto, and forex.

        Args:
            query: Natural language query (e.g., 'Apple revenue last 4 quarters')

        Returns:
            JSON array of financial data results
        """
        return self._execute_search(
            query=query,
            search_type="proprietary",
            sources=FINANCE_SOURCES,
        )

    def economics_search(self, query: str) -> str:
        """Search economic data from BLS, FRED, World Bank.

        Includes unemployment, wages, GDP, monetary policy indicators,
        international development data, and US government spending.

        Args:
            query: Natural language query (e.g., 'US unemployment rate 2024')

        Returns:
            JSON array of economic data results
        """
        return self._execute_search(
            query=query,
            search_type="proprietary",
            sources=ECONOMICS_SOURCES,
        )

    def paper_search(self, query: str) -> str:
        """Search academic papers from arXiv, PubMed, bioRxiv, and medRxiv.

        Args:
            query: Natural language query (e.g., 'transformer attention mechanisms')

        Returns:
            JSON array of academic paper results
        """
        return self._execute_search(
            query=query,
            search_type="proprietary",
            sources=PAPER_SOURCES,
        )
