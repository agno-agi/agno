from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(id="claude-opus-4-5", betas=["web-fetch-2025-09-10"]),
    tools=[
        {
            "type": "web_fetch_20250910",
            "name": "web_fetch",
            "max_uses": 5,
        }
    ],
    markdown=True,
)

agent.print_response(
    "Tell me more about https://en.wikipedia.org/wiki/Glacier_National_Park_(U.S.)",
    stream=True,
)
