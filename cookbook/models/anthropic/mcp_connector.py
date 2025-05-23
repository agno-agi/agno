""""""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.utils.models.claude import MCPServerConfiguration, MCPToolConfiguration

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        default_headers={"anthropic-beta": "mcp-client-2025-04-04"},
        mcp_servers=[
            MCPServerConfiguration(
                type="url",
                url="http://localhost:8000/sse",
                name="example-mcp",
                tool_configuration=MCPToolConfiguration(
                    enabled=True,
                    allowed_tools=[
                        "get_events"
                    ],  # Used to limit the tools the Agent can use
                ),
            )
        ],
    ),
    markdown=True,
)

agent.print_response(
    "Tell me which tools you have access to",
    stream=True,
)
