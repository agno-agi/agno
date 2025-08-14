from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team

researcher = Agent(
    name="researcher",
    role="Research Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a research assistant. Find information and provide detailed analysis.",
    markdown=True,
)

writer = Agent(
    name="writer",
    role="Content Writer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a content writer. Create well-structured content based on research.",
    markdown=True,
)

research_team = Team(
    members=[researcher, writer],
    name="research_team",
    instructions="""
    You are a research team that helps users with research and content creation.
    First, use the researcher to gather information, then use the writer to create content.
    """,
    show_members_responses=True,
    get_member_information_tool=True,
    add_member_tools_to_context=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="AgentOS setup with an AG-UI interface",
    teams=[research_team],
    interfaces=[AGUI(team=research_team)],
)

app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available interfaces on:
    http://localhost:7777/config

    """
    agent_os.serve(app="team:app", reload=True)
