"""
Example showing how to use JSON as output schema.

Note: JSON schemas must be in the provider's expected format.
For example, OpenAI expects:
{"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.pprint import pprint_run_response

stock_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "StockAnalysis",
        "schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Stock ticker symbol"},
                "company_name": {"type": "string", "description": "Company name"},
                "analysis": {"type": "string", "description": "Brief analysis"},
            },
            "required": ["symbol", "company_name", "analysis"],
            "additionalProperties": False,
        },
    },
}

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches for information on stocks and provides price analysis.",
    tools=[DuckDuckGoTools()],
)

company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches for information about companies and recent news.",
    tools=[DuckDuckGoTools()],
)

team = Team(
    name="Stock Research Team",
    model=OpenAIChat("gpt-4o"),
    respond_directly=True,
    members=[stock_searcher, company_info_agent],
    output_schema=stock_schema,
    markdown=True,
)

response = team.run("What is the current stock price of NVDA?")
assert isinstance(response.content, dict)
assert response.content_type == "dict"
pprint_run_response(response)
