"""
Gemini Interactions - Deep Research with MCP servers
=====================================================

Give the Deep Research agent access to external tools via remote MCP servers.
Pass server configs through `mcp_servers`; `type: "mcp_server"` is added
automatically. Only `url` is strictly required; `name`, `headers`, and
`allowed_tools` are optional.

Custom Function Calling tools are NOT supported by Deep Research, but remote
MCP servers are.
"""

from agno.agent import Agent
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
        mcp_servers=[
            {
                "name": "Deployment Tracker",
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer my-token"},
                # "allowed_tools": ["get_status"],  # optionally restrict
            }
        ],
    ),
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Check the status of my last server deployment and summarize any issues."
    )
