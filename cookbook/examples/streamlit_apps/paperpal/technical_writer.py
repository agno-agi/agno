import os
from pathlib import Path
from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.arxiv import ArxivTools
from agno.tools.exa import ExaTools
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# Define data models
class SearchTerms(BaseModel):
    terms: List[str] = Field(
        ..., description="List of search terms related to a topic."
    )


class ArxivSearchResult(BaseModel):
    title: str = Field(..., description="Title of the article.")
    id: str = Field(..., description="The ID of the article.")
    authors: List[str] = Field(..., description="Authors of the article.")
    summary: str = Field(..., description="Summary of the article.")
    pdf_url: str = Field(..., description="URL of the PDF of the article.")
    links: List[str] = Field(..., description="Links related to the article.")
    reasoning: str = Field(..., description="Reason for selecting this article.")


class ArxivSearchResults(BaseModel):
    results: List[ArxivSearchResult] = Field(
        ..., description="List of top search results."
    )


class WebSearchResult(BaseModel):
    title: str = Field(..., description="Title of the article.")
    summary: str = Field(..., description="Summary of the article.")
    links: List[str] = Field(..., description="Links related to the article.")
    reasoning: str = Field(..., description="Reason for selecting this article.")


class WebSearchResults(BaseModel):
    results: List[WebSearchResult] = Field(
        ..., description="List of top search results."
    )


# Initialize tools
arxiv_toolkit = ArxivTools(
    download_dir=Path(__file__).parent.parent.parent.parent.joinpath(
        "wip", "arxiv_pdfs"
    )
)
exa_tools = ExaTools()

# Initialize agents
search_term_generator = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="""
You are an expert research strategist. Generate 2 specific and distinct search terms that will capture different key aspects of the given topic.
Focus on terms that are:
    - Specific enough to yield relevant results
    - Cover both technical and practical aspects of the topic
    - Relevant to current developments
    - Optimized for searching academic and web resources effectively

Provide the search terms as a list of strings like ["xyz", "abc", ...]
""",
    response_model=SearchTerms,
)

arxiv_search_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="""
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
""",
    tools=[arxiv_toolkit],
    response_model=ArxivSearchResults,
)

exa_search_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="""
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
""",
    tools=[ExaTools()],
    response_model=WebSearchResults,
)

research_editor = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="""
You are a senior research editor specializing in breaking complex topics and information into understandable, engaging, high-quality blogs.

Your task is to:
1. Create a detailed blog within 1000 words based on the given topic.
2. The blog should be of max 7-8 paragraphs, understandable, intuitive, making things easy to understand for the reader.
3. Highlight key findings and provide a clear, high-level overview of the topic.
4. At the end add the supporting articles link, paper link or any findings you think is necessary to add.

The blog should help the reader in getting a decent understanding of the topic.
The blog should me in markdown format.
""",
    instructions=[
        "Analyze all materials before writing.",
        "Build a clear narrative structure.",
        "Balance technical accuracy with explainability.",
    ],
    markdown=True,
)
