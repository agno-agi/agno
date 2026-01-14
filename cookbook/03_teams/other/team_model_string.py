from agno.agent import Agent
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Model strings follow the format "{provider}:{model_id}", for example:
model_string = "openai:gpt-4o-mini"

# Create a research team
team = Team(
    model=model_string,
    members=[
        Agent(
            model=model_string,
            name="Sarah",
            role="Data Researcher",
            tools=[DuckDuckGoTools()],
            instructions="Focus on gathering and analyzing data",
        ),
        Agent(
            model=model_string,
            name="Mike",
            role="Technical Writer",
            instructions="Create clear, concise summaries",
        ),
    ],
)

team.print_response(
    "Search for latest news about the latest AI models",
)
