"""
Oxylabs Tools
=============================

Web scraping toolkit for Google search, Amazon products, and website scraping.

Requirements:
    pip install oxylabs

Environment variables:
    OXYLABS_USERNAME: Your Oxylabs username
    OXYLABS_PASSWORD: Your Oxylabs password
"""

from agno.agent import Agent
from agno.tools.oxylabs import OxylabsTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[OxylabsTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Google Search
    agent.print_response(
        "Search for 'latest iPhone reviews' and summarize the top 3 results.",
    )

    # Example 2: Amazon Product Search
    # agent.print_response(
    #     "Get details for Amazon product with ASIN 'B07FZ8S74R' (Echo Dot).",
    # )

    # Example 3: Multi-Domain Amazon Search
    # agent.print_response(
    #     "Use search_amazon_products to search for 'gaming keyboards' on both:\n"
    #     "1. Amazon US (domain='com')\n"
    #     "2. Amazon UK (domain='co.uk')\n"
    #     "Compare the top 3 results from each region including pricing and availability."
    # )

    # Example 4: Website Scraping with Markdown Output
    # Use markdown=True on OxylabsTools to get full Markdown content instead of parsed HTML
    # agent_markdown = Agent(
    #     tools=[OxylabsTools(markdown=True)],
    #     markdown=True,
    # )
    # agent_markdown.print_response(
    #     "Scrape the content from https://example.com and summarize it.",
    # )
