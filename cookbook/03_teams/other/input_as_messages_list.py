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
)

research_team.print_response(
    [
        Message(
            role="user",
            content="I'm preparing a presentation for my company about renewable energy adoption.",
        ),
        Message(
            role="assistant",
            content="I'd be happy to help with your renewable energy presentation. What specific aspects would you like me to focus on?",
        ),
        Message(
            role="user",
            content="Could you research the latest solar panel efficiency improvements in 2024?",
        ),
        Message(
            role="user",
            content="Also, please summarize the key findings in bullet points for my slides.",
        ),
    ],
    markdown=True,
)
