from agno.agent import Agent
from agno.models.google.gemini import Gemini
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Create individual specialized agents
researcher = Agent(
    name="Researcher",
    role="Expert at finding information",
    tools=[DuckDuckGoTools()],
    model=Gemini("gemini-2.0-flash-001"),
)

writer = Agent(
    name="Writer",
    role="Expert at writing clear, engaging content",
    model=Gemini("gemini-2.0-flash-001"),
)

# Create a team with these agents
content_team = Team(
    name="Content Team",
    model=Gemini("gemini-2.5-flash"),
    # model=Gemini("gemini-2.0-flash-lite"),  # Try a small model for faster response
    members=[researcher, writer],
    instructions="You are a team of researchers and writers that work together to create high-quality content.",
    show_members_responses=True,
)

# Run the team with a task
content_team.print_response("Create a short article about quantum computing")
