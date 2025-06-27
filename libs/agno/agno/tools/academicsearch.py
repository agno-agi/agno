import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    from valyu import Valyu
except ImportError:
    raise ImportError("`valyu` not installed. Please install using `pip install valyu`")


class AcademicSearchTools(Toolkit):
    """
    AcademicSearchTools provides AI agents with access to the world's most comprehensive academic search engine
    powered by Valyu's DeepSearch API. This tool enables intelligent retrieval of academic papers, research content,
    and scholarly materials with full-text multimodal search capabilities.

    🔬 **Why Use Valyu Academic Search?**
    - **Complete ArXiv Coverage**: 100% ArXiv indexed with full-text multimodal retrieval
    - **PubMed Integration**: Comprehensive medical and life sciences literature access
    - **Premium Academic Content**: Proprietary partnerships with major academic publishers
    - **Multimodal Search**: Search across text, figures, equations, and tables within papers
    - **Real-time Updates**: Latest research papers indexed as they're published
    - **Citation Analysis**: Get citation counts, DOIs, and reference networks
    - **Quality Filtering**: Advanced relevance scoring optimized for academic content

    🤖 **Perfect for AI Agents that need to:**
    - Get specific pieces of information from academic papers, beyond just abstracts
    - Find the latest papers on specific research topics
    - Analyze research trends and methodologies
    - Extract insights from academic tables, figures and equations
    - Verify scientific claims with authoritative sources

    Args:
        search_academic_papers: bool = True - Enable academic paper search functionality
        search_within_paper: bool = True - Enable searching within specific ArXiv papers
        api_key: Optional[str] = None - Valyu API key. Retrieved from `VALYU_API_KEY` env variable if not provided
        max_num_results: int = 10 - Default maximum number of results to return (1-20)
        relevance_threshold: float = 0.7 - Minimum relevance score for high-quality academic results (0.0-1.0)
        max_price: float = 30.0 - Maximum cost in dollars for 1000 retrievals
        show_results: bool = False - Log search results for debugging and transparency
        text_length_limit: int = 1500 - Maximum length of text content per result
        **kwargs - Additional toolkit configuration options

    Environment Variables:
        VALYU_API_KEY: Your Valyu API key (get $10 free credits at https://valyu.network)
    """

    def __init__(
        self,
        search_academic_papers: bool = True,
        search_within_paper: bool = True,
        api_key: Optional[str] = None,
        max_num_results: int = 10,
        relevance_threshold: float = 0.5,
        max_price: float = 30.0,
        show_results: bool = False,
        text_length_limit: int = 1500,
        **kwargs,
    ):
        self.api_key = api_key or getenv("VALYU_API_KEY")
        if not self.api_key:
            logger.error(
                "VALYU_API_KEY not set. Please set the VALYU_API_KEY environment variable."
            )
            logger.error(
                "Get your free API key with $10 credits at: https://platform.valyu.network"
            )

        self.valyu = Valyu(api_key=self.api_key) if self.api_key else None
        self.max_num_results = max_num_results
        self.relevance_threshold = relevance_threshold
        self.max_price = max_price
        self.show_results = show_results
        self.text_length_limit = text_length_limit

        tools: List[Any] = []
        if search_academic_papers:
            tools.append(self.search_academic_papers)
        if search_within_paper:
            tools.append(self.search_within_specific_paper)

        super().__init__(name="academic_search", tools=tools, **kwargs)

    def _parse_academic_results(self, results: List[Any]) -> str:
        """Parse and structure academic search results in a simple format for agents."""
        parsed_results = []
        for result in results:
            result_dict = {}

            # Essential fields that agents need (accessing attributes directly from SearchResult objects)
            if hasattr(result, "url") and result.url:
                result_dict["url"] = result.url
            if hasattr(result, "title") and result.title:
                result_dict["title"] = result.title
            if hasattr(result, "source") and result.source:
                result_dict["source"] = result.source
            if hasattr(result, "relevance_score"):
                result_dict["relevance_score"] = result.relevance_score

            # Content with length limiting
            if hasattr(result, "content") and result.content:
                content = result.content
                if self.text_length_limit and len(content) > self.text_length_limit:
                    content = content[: self.text_length_limit] + "..."
                result_dict["content"] = content

            # Additional metadata if available
            if hasattr(result, "description") and result.description:
                result_dict["description"] = result.description
            if hasattr(result, "length"):
                result_dict["length"] = result.length

            parsed_results.append(result_dict)

        return json.dumps(parsed_results, indent=4)

    def search_academic_papers(
        self,
        query: str,
        num_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        specific_sources: Optional[List[str]] = None,
        research_category: Optional[str] = None,
    ) -> str:
        """Search Valyu's comprehensive academic database for research papers and scholarly content.

        This function provides access to the world's largest indexed academic database including:
        • Complete ArXiv repository (all papers with full-text multimodal search)
        • PubMed medical and life sciences literature
        • Proprietary academic content from partnerships with major publishers
        • Real-time indexing of newly published research

        Perfect for literature reviews, research synthesis, finding cutting-edge papers, and academic research.

        Args:
            query (str): Your research question or topic. Use specific academic terminology for best results.
                        Examples: "CRISPR Cas9 off-target effects in human cells"
                                  "quantum error correction surface codes"

            num_results (int, optional): Number of papers to return (1-20). More results = broader coverage.
                                       Defaults to 10. Use 15-20 for comprehensive literature reviews.

            start_date (str, optional): Filter papers published after this date (YYYY-MM-DD format).
                                      Example: "2020-01-01" for papers from 2020 onwards.

            end_date (str, optional): Filter papers published before this date (YYYY-MM-DD format).
                                    Example: "2023-12-31" for papers through 2023.

            specific_sources (List[str], optional): Target specific academic databases. Options include:
                                                  • ["valyu/valyu-arxiv"] - ArXiv papers only
                                                  • ["valyu/valyu-pubmed"] - PubMed medical literature
                                                  • ["wiley/wiley-finance-books"] - Wiley finance/business/accounting textbooks
                                                  • Custom publisher sources available
                                                  If not specified, searches all academic sources.

            research_category (str, optional): Natural language category to guide the search.
                                             Examples: "machine learning", "molecular biology",
                                                      "quantum physics", "clinical trials"

        Returns:
            str: JSON array of academic papers with title, authors, content, DOI, and metadata.

        Example Usage:
            # Find latest CRISPR research
            results = search_academic_papers(
                "CRISPR gene editing safety mechanisms",
                num_results=15,
                start_date="2022-01-01",
                research_category="molecular biology"
            )

            # Search specific ArXiv papers
            results = search_academic_papers(
                "attention mechanisms transformer models",
                specific_sources=["valyu/valyu-arxiv"]
            )
        """
        if not self.valyu:
            return "Error: VALYU_API_KEY not configured. Set environment variable and get free credits at https://valyu.network"

        try:
            if self.show_results:
                log_info(f"🔬 Searching academic papers for: {query}")

            search_params = {
                "search_type": "proprietary",  # Focus on academic content
                "max_num_results": num_results or self.max_num_results,
                "max_price": self.max_price,
                "is_tool_call": True,
            }

            # Add optional parameters
            if start_date:
                search_params["start_date"] = start_date
            if end_date:
                search_params["end_date"] = end_date
            if research_category:
                search_params["category"] = research_category
            if specific_sources:
                search_params["included_sources"] = specific_sources
            else:
                # Default to comprehensive academic sources
                search_params["included_sources"] = [
                    "valyu/valyu-arxiv",
                    "valyu/valyu-pubmed",
                ]

            log_debug(f"Academic search parameters: {search_params}")
            response = self.valyu.search(query, **search_params)

            if not response.success:
                logger.error(f"Academic search API error: {response.error}")
                return f"Error: {response.error or 'Academic search request failed'}"

            parsed_results = self._parse_academic_results(response.results or [])

            if self.show_results:
                log_info(
                    f"✅ Academic search completed. Found {len(response.results or [])} relevant papers"
                )

            return parsed_results

        except Exception as e:
            error_msg = f"Academic search failed: {str(e)}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

    def search_within_specific_paper(
        self,
        arxiv_paper_url: str,
        search_query: str,
        num_results: Optional[int] = None,
    ) -> str:
        """Search within the content of a specific ArXiv paper using its abstract URL.

        This powerful feature allows you to perform targeted searches within individual research papers,
        perfect for finding specific methodologies, results, or discussions within known papers.

        🎯 **Use Cases:**
        • Find specific methodology details in a paper
        • Locate experimental results or data analysis sections
        • Search for particular concepts or techniques within a paper
        • Extract relevant quotes or findings from lengthy papers
        • Navigate large papers to find sections of interest

        Args:
            arxiv_paper_url (str): The ArXiv abstract URL of the paper to search within.
                                  Format: "https://arxiv.org/abs/XXXX.XXXXX"
                                  Examples: "https://arxiv.org/abs/1706.03762" (Attention Is All You Need)
                                           "https://arxiv.org/abs/2005.14165" (GPT-3)
                                           "https://arxiv.org/abs/2303.08774" (GPT-4)

            search_query (str): What to search for within the paper. Be specific for best results.
                               Examples: "conclusion", "experimental setup methodology",
                                        "computational complexity analysis", "limitations"

            num_results (int, optional): Number of relevant sections to return (1-20).
                                       Default is 5. Use more for comprehensive paper analysis.

        Returns:
            str: JSON array of relevant sections from the specific paper with content and metadata.

        Example Usage:
            # Search for attention mechanism details in the famous "Attention Is All You Need" paper
            results = search_within_specific_paper(
                arxiv_paper_url="https://arxiv.org/abs/1706.03762",
                search_query="multi-head attention mechanism architecture",
                num_results=3
            )

            # Find main results in GPT-3 paper
            results = search_within_specific_paper(
                arxiv_paper_url="https://arxiv.org/abs/2005.14165",
                search_query="main results of the paper"
            )
        """
        if not self.valyu:
            return "Error: VALYU_API_KEY not configured. Set environment variable and get free credits at https://valyu.network"

        # Validate ArXiv URL format
        if not arxiv_paper_url.startswith("https://arxiv.org/abs/"):
            return "Error: Invalid ArXiv URL format. Please use: https://arxiv.org/abs/XXXX.XXXXX"

        try:
            if self.show_results:
                log_info(
                    f"📄 Searching within paper {arxiv_paper_url} for: {search_query}"
                )

            search_params = {
                "search_type": "proprietary",
                "max_num_results": num_results
                or 5,  # Fewer results for within-paper search
                "max_price": self.max_price,
                "is_tool_call": True,
                "included_sources": [
                    arxiv_paper_url
                ],  # Search only within this specific paper
            }

            # Let SDK use default relevance_threshold (0.5) for broader coverage when searching within papers

            log_debug(f"Within-paper search parameters: {search_params}")
            response = self.valyu.search(search_query, **search_params)

            if not response.success:
                logger.error(f"Within-paper search API error: {response.error}")
                return (
                    f"Error: {response.error or 'Within-paper search request failed'}"
                )

            parsed_results = self._parse_academic_results(response.results or [])

            if self.show_results:
                log_info(
                    f"✅ Within-paper search completed. Found {len(response.results or [])} relevant sections"
                )

            return parsed_results

        except Exception as e:
            error_msg = f"Within-paper search failed: {str(e)}"
            logger.error(error_msg)
            return f"Error: {error_msg}"
