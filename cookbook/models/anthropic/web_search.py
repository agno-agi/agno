from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
    ),
    tools=[
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }
    ],
    markdown=True,
)

agent.print_response("What's the latest with Anthropic?", stream=True)
