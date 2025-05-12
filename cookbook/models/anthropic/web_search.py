from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-3-5-sonnet-20241022",
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

agent.print_response(
    "Please search the web for the latest news regarding Anthropic", stream=True
)
