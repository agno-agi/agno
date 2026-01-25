from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.utils.models.claude import MCPServerConfiguration

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        betas=["mcp-client-2025-04-04"],
        mcp_servers=[
            MCPServerConfiguration(
                type="url",
                name="deepwiki",
                url="https://mcp.deepwiki.com/sse",
            )
        ],
    ),
    markdown=True,
)

agent.print_response(
    "Tell me about https://github.com/agno-agi/agno",
    stream=True,
)
