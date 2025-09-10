from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        default_headers={"anthropic-beta": "web-fetch-2025-09-10"},
    ),
    tools=[{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 5}],
    markdown=True,
)

agent.print_response(
    "Fetch the content of https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-fetch-tool",
    stream=True,
)
