"""
This is an example of how to use CrwTools for structured data extraction.

Uses CRW's LLM-powered extraction with JSON Schema to pull specific fields
from web pages. Requires LLM extraction to be configured on the CRW server.

Prerequisites:
- A running CRW server with LLM extraction configured
    cargo install crw-server && crw-server
"""

from agno.agent import Agent
from agno.tools.crw import CrwTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[
        CrwTools(
            api_url="http://localhost:3000",
            enable_scrape=True,
            enable_extract=True,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Extract the product name, price, and rating from https://example.com/product"
    )
