"""
ArXiv Tools - Academic Paper Search and Research

This example demonstrates how to use ArxivTools for searching academic papers.
Shows enable_ flag patterns for selective function access.
ArxivTools is a small tool (<6 functions) so it uses enable_ flags.

Run: `pip install arxiv` to install the dependencies
"""

from agno.agent import Agent
from agno.tools.arxiv import ArxivTools

# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[ArxivTools()],  # All functions enabled by default
    description="You are a research assistant with full ArXiv search capabilities.",
    instructions=[
        "Help users find and analyze academic papers from ArXiv",
        "Provide detailed paper summaries and insights",
        "Support comprehensive literature reviews",
    ],
    markdown=True,
)

# Example 2: Enable specific search functions
agent_search_only = Agent(
    tools=[
        ArxivTools(
            enable_search_arxiv=True,
            enable_read_arxiv_papers=False,  # Disable detailed paper analysis
        )
    ],
    description="You are a research search specialist focused on finding relevant papers.",
    instructions=[
        "Search for academic papers based on keywords and topics",
        "Provide basic paper information and abstracts",
        "Focus on broad literature discovery",
    ],
    markdown=True,
)

# Example 3: Enable all functions using the 'all=True' pattern
agent_comprehensive = Agent(
    tools=[ArxivTools(all=True)],  # Enable all functions explicitly
    description="You are a comprehensive research assistant for academic literature analysis.",
    instructions=[
        "Perform detailed academic research using all ArXiv capabilities",
        "Provide in-depth paper analysis and cross-references",
        "Support advanced research methodologies",
    ],
    markdown=True,
)

# Example 4: Custom configuration for specific research needs
agent_focused = Agent(
    tools=[
        ArxivTools(
            enable_search_arxiv=True,
            enable_read_arxiv_papers=True,
            # Add other enable_ flags as needed based on available functions
        )
    ],
    description="You are a focused research assistant for specific academic domains.",
    instructions=[
        "Conduct targeted searches in specific academic fields",
        "Provide detailed analysis of relevant papers",
        "Maintain focus on research objectives",
    ],
    markdown=True,
)

# Basic search example
print("=== ArXiv Paper Search Example ===")
agent_full.print_response("Search arxiv for 'language models'", markdown=True)

print("\n=== Focused Research Example ===")
agent_focused.print_response(
    "Find recent papers on 'transformer architectures' and provide detailed analysis",
    markdown=True,
)

print("\n=== Search-Only Example ===")
agent_search_only.print_response(
    "Search for papers related to 'machine learning interpretability'", markdown=True
)
