"""
Anthropic Pydantic Tool Input
==============================

Demonstrates using pydantic models as tool input parameters with Claude.
Pydantic models work without needing ConfigDict(extra="forbid") - the
framework automatically handles schema formatting for Anthropic's API.
"""

import asyncio
import json

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools import tool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define pydantic models for structured tool input
# ---------------------------------------------------------------------------


class SearchFilters(BaseModel):
    category: str = Field(description="Category to search in")
    max_price: float = Field(description="Maximum price filter")
    in_stock: bool = Field(default=True, description="Only show in-stock items")


class SearchRequest(BaseModel):
    query: str = Field(description="The search query string")
    filters: SearchFilters = Field(description="Filters to apply to the search")


@tool
def search_products(request: SearchRequest) -> str:
    """Search for products using structured filters.

    Args:
        request: The search request with query and filters
    """
    return json.dumps(
        {
            "results": [
                {
                    "name": f"Result for '{request.query}'",
                    "category": request.filters.category,
                    "price": request.filters.max_price * 0.8,
                    "in_stock": request.filters.in_stock,
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[search_products],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "Search for wireless headphones under $50 in the electronics category"
    )

    # --- Async ---
    asyncio.run(
        agent.aprint_response(
            "Find me running shoes under $100 that are in stock, in the sports category"
        )
    )
