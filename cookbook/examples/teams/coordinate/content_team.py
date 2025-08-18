from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Create individual specialized agents
researcher = Agent(
    name="Researcher",
    role="Expert at finding information",
    tools=[DuckDuckGoTools()],
    model=OpenAIChat("gpt-4o"),
)

writer = Agent(
    name="Writer",
    role="Expert at writing clear, engaging content",
    model=OpenAIChat("gpt-4o"),
)

# Create a team with these agents
content_team = Team(
    name="Content Team",
    mode="coordinate",
    members=[researcher, writer],
    instructions="You are a team of researchers and writers that work together to create high-quality content.",
    model=OpenAIChat("gpt-4o"),
    show_members_responses=True,
)

# Run the team with a task
content_team.print_response("Create a short article about quantum computing")
