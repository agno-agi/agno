from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-3-5-sonnet-20241022",
        web_search=True,
    ),
    markdown=True,
)

agent.print_response(
    "Please search the web for the latest news regarding Anthropic", stream=True
)
