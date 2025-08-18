from agno.agent import Agent
from agno.models.message import Message
from agno.team import Team

# Create a research team
research_team = Team(
    name="Research Team",
    members=[
        Agent(
            name="Sarah",
            role="Data Researcher",
            instructions="Focus on gathering and analyzing data",
        ),
        Agent(
            name="Mike",
            role="Technical Writer",
            instructions="Create clear, concise summaries",
        ),
    ],
    stream=True,
    markdown=True,
    debug_mode=True,
)

research_team.print_response(
    input="Also, please summarize the key findings in bullet points for my slides.",
    markdown=True,
)
