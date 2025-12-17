from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.tools.arxiv import ArxivTools
from agno.tools.exa import ExaTools
from agno.utils.streamlit import get_model_with_provider
from pydantic import BaseModel, Field

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


# Data Models for structured outputs
class SearchTerms(BaseModel):
    terms: List[str] = Field(
        ..., description="List of search terms related to a topic."
    )


class ArxivSearchResult(BaseModel):
    title: str = Field(..., description="Title of the research paper.")
    id: str = Field(..., description="ArXiv ID of the paper.")
    authors: List[str] = Field(..., description="Authors of the paper.")
    summary: str = Field(..., description="Abstract/summary of the paper.")
    pdf_url: str = Field(..., description="URL to the PDF of the paper.")
    links: List[str] = Field(..., description="Related links to the paper.")
    reasoning: str = Field(..., description="Reasoning for selecting this paper.")


class ArxivSearchResults(BaseModel):
    results: List[ArxivSearchResult] = Field(
        ..., description="List of selected ArXiv research papers."
    )


class WebSearchResult(BaseModel):
    title: str = Field(..., description="Title of the web article.")
    summary: str = Field(..., description="Summary of the article content.")
    links: List[str] = Field(..., description="Links related to the article.")
    reasoning: str = Field(..., description="Reasoning for selecting this article.")


class WebSearchResults(BaseModel):
    results: List[WebSearchResult] = Field(
        ..., description="List of selected web search results."
    )


def get_paperpal_agents(
    model_id: str = "gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    arxiv_download_dir: Optional[Path] = None,
):
    """Get Paperpal research agents with tools"""

    # Set up ArXiv download directory
    if not arxiv_download_dir:
        arxiv_download_dir = Path(__file__).parent.parent.parent.parent.joinpath(
            "tmp", "arxiv_pdfs"
        )
        arxiv_download_dir.mkdir(parents=True, exist_ok=True)

    # Initialize tools
    arxiv_toolkit = ArxivTools(download_dir=arxiv_download_dir)
    exa_tools = ExaTools()

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    # Search Term Generator Agent
    search_term_generator = Agent(
        name="Search Term Generator",
        model=get_model_with_provider(model_id),
        db=db,
        id="search-term-generator",
        user_id=user_id,
        session_id=session_id,
        output_schema=SearchTerms,
        instructions=dedent("""
            You are an expert research strategist specializing in generating strategic search terms 
            for comprehensive research coverage.

            Your task is to:
            1. Analyze the given research topic to identify key concepts and aspects
            2. Generate 2-3 specific and distinct search terms that capture different dimensions
            3. Ensure terms are optimized for both academic and web search effectiveness
                            
            Focus on terms that will help find:
            - Recent research papers and theoretical developments
            - Industry applications and real-world implementations
            - Current challenges and future directions
            - Cross-disciplinary connections and emerging trends

            Provide terms as a structured list optimized for research databases and web search.
        """),
        markdown=True,
        debug_mode=True,
    )

    # ArXiv Search Agent
    arxiv_search_agent = Agent(
        name="ArXiv Research Agent",
        model=get_model_with_provider(model_id),
        db=db,
        id="arxiv-search-agent",
        user_id=user_id,
        session_id=session_id,
        tools=[arxiv_toolkit],
        output_schema=ArxivSearchResults,
        instructions=dedent("""
            You are an expert in academic research with access to ArXiv's database.

            Your task is to:
            1. Search ArXiv for the top 10 papers related to the provided search term.
            2. Select the 3 most relevant research papers based on:
                - Direct relevance to the search term.
                - Scientific impact (e.g., citations, journal reputation).
                - Recency of publication.

            For each selected paper, the output should be in json structure have these details:
                - title
                - id
                - authors
                - a concise summary
                - the PDF link of the research paper
                - links related to the research paper
                - reasoning for why the paper was chosen

            Ensure the selected research papers directly address the topic and offer valuable insights.
        """),
        markdown=True,
        debug_mode=True,
    )

    # Web Search Agent
    exa_search_agent = Agent(
        name="Web Research Agent",
        model=get_model_with_provider(model_id),
        db=db,
        id="exa-search-agent",
        user_id=user_id,
        session_id=session_id,
        tools=[exa_tools],
        output_schema=WebSearchResults,
        instructions=dedent("""
            You are a web search expert specializing in extracting high-quality information.

            Your task is to:
            1. Given a topic, search Exa for the top 10 articles about that topic.
            2. Select the 3 most relevant articles based on:
                - Source credibility.
                - Content depth and relevance.

            For each selected article, the output should have:
                - title
                - a concise summary
                - related links to the article
                - reasoning for why the article was chosen and how it contributes to understanding the topic.

            Ensure the selected articles are credible, relevant, and provide significant insights into the topic.
        """),
        markdown=True,
        debug_mode=True,
    )

    # Research Editor Agent
    research_editor = Agent(
        name="Research Editor",
        model=get_model_with_provider(model_id),
        db=db,
        id="research-editor",
        user_id=user_id,
        session_id=session_id,
        instructions=dedent("""
            You are a senior research editor specializing in breaking complex topics and information into understandable, engaging, high-quality blogs.

            Your task is to:
            1. Create a detailed blog within 1000 words based on the given topic.
            2. The blog should be of max 7-8 paragraphs, understandable, intuitive, making things easy to understand for the reader.
            3. Highlight key findings and provide a clear, high-level overview of the topic.
            4. At the end add the supporting articles link, paper link or any findings you think is necessary to add.

            The blog should help the reader in getting a decent understanding of the topic.
            The blog should be in markdown format.
        """),
        markdown=True,
        debug_mode=True,
    )

    return {
        "search_term_generator": search_term_generator,
        "arxiv_search_agent": arxiv_search_agent,
        "exa_search_agent": exa_search_agent,
        "research_editor": research_editor,
        "arxiv_toolkit": arxiv_toolkit,
    }
