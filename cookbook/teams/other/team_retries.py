"""Example demonstrating how to set up retries with a Team."""

from agno.agent import Agent
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Create a research team
team = Team(
    members=[
        Agent(
            name="Sarah",
            role="Data Researcher",
            tools=[DuckDuckGoTools()],
            instructions="Focus on gathering and analyzing data",
        ),
        Agent(
            name="Mike",
            role="Technical Writer",
            instructions="Create clear, concise summaries",
        ),
    ],
    retries=3,  # The Team run will be retried 3 times in case of error.
    delay_between_retries=1,  # Delay between retries in seconds.
    exponential_backoff=True,  # If True, the delay between retries is doubled each time.
)

team.print_response(
    "Search for latest news about the latest AI models",
    stream=True,
)
