""""""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.utils.models.claude import MCPServerConfiguration, MCPToolConfiguration
from os import getenv

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        default_headers={"anthropic-beta": "mcp-client-2025-04-04"},
        mcp_servers=[
            MCPServerConfiguration(
                type="url",
                name="brave-search",
                url="https://api.brave.com/mcp",
                authorization_token=getenv("BRAVE_API_KEY"),
            )
        ],
    ),
    markdown=True,
)

agent.print_response(
    "Tell me which tools you have access to",
    stream=True,
)


# agent = Agent(
#     model=Claude(
#         id="claude-sonnet-4-20250514",
#         default_headers={"anthropic-beta": "mcp-client-2025-04-04"},
#         mcp_servers=[
#             {
#                 "type": "mcp-server-brave-search",
#                 "name": "brave-search",
#                 "url": "https://api.brave.com/mcp",
#                 "env": {
#                     "BRAVE_API_KEY": getenv("BRAVE_API_KEY"),
#                 },
#             }
#         ],
#     ),
#     markdown=True,
# )

# agent.print_response(
#     "What is the weather in Tokyo?",
#     stream=True,
# )
