from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

researcher = Agent(
    name="researcher",
    role="Research Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a research assistant. Find information and provide detailed analysis.",
    tools=[DuckDuckGoTools()],
    markdown=True,
)

writer = Agent(
    name="writer",
    role="Content Writer",
    model=OpenAIChat(id="o4-mini"),
    instructions="You are a content writer. Create well-structured content based on research.",
    tools=[DuckDuckGoTools()],
    markdown=True,
)

research_team = Team(
    members=[researcher, writer],
    name="Research Team",
    instructions="""
    You are a research team that helps users with research and content creation.
    First, use the researcher to gather information, then use the writer to create content.
    """,
    show_members_responses=True,
    get_member_information_tool=True,
    add_member_tools_to_context=True,
    add_history_to_context=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    teams=[research_team],
    a2a_interface=True,
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS with A2A interface.

    You can run the research_team via A2A protocol:
    POST http://localhost:7777/a2a/message/send
    (include "agentId": "research-team" in params.message)

    """
    agent_os.serve(app="research_team:app", reload=True, port=7777)
