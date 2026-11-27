"""
Semantic Scholar Tools
======================

Demonstrates SemanticScholarTools for academic paper search and paper metadata lookup.

Most Semantic Scholar endpoints work without an API key, but setting
SEMANTIC_SCHOLAR_API_KEY gives more stable rate limits.
"""

from agno.agent import Agent
from agno.tools.semantic_scholar import SemanticScholarTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[SemanticScholarTools()],
    instructions=[
        "Use Semantic Scholar to find relevant academic papers.",
        "Prefer papers with DOI, open access PDFs, citation counts, and concise TLDRs when available.",
    ],
    markdown=True,
)

research_agent = Agent(
    tools=[SemanticScholarTools(all=True, max_results=3)],
    instructions=[
        "Help users compare papers and authors from Semantic Scholar metadata.",
        "Mention publication year, venue, citation count, DOI, and open access PDF links when available.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Search for recent papers about retrieval augmented generation evaluation.",
        stream=True,
    )

    research_agent.print_response(
        "Find papers by Semantic Scholar author id 1741101 and summarize their RAG relevance.",
        stream=True,
    )
