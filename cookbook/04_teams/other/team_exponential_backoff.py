from agno.agent import Agent
from agno.team import Team
from agno.tools.websearch import WebSearchTools

# Create a research team
team = Team(
    members=[
        Agent(
            name="Sarah",
            role="Data Researcher",
            tools=[WebSearchTools()],
            instructions="Focus on gathering and analyzing data",
        ),
        Agent(
            name="Mike",
            role="Technical Writer",
            instructions="Create clear, concise summaries",
        ),
    ],
    retries=3,
    exponential_backoff=True,
)

team.print_response(
    "Search for latest news about the latest AI models",
    stream=True,
)
