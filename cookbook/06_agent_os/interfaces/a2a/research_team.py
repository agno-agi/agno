from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

researcher = Agent(
    name="researcher",
    id="researcher",
    role="Research Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a research assistant. Find information and provide detailed analysis.",
    tools=[DuckDuckGoTools()],
    markdown=True,
)

writer = Agent(
    name="writer",
    id="writer",
    role="Content Writer",
    model=OpenAIChat(id="o4-mini"),
    instructions="You are a content writer. Create well-structured content based on research.",
    tools=[DuckDuckGoTools()],
    markdown=True,
)

research_team = Team(
    members=[researcher, writer],
    id="research_team",
    name="Research Team",
    description="A collaborative research and content creation team combining deep research capabilities with professional writing to deliver comprehensive, well-researched content",
    instructions="""
    You are a research team that helps users with research and content creation.
    First, use the researcher to gather information, then use the writer to create content.
    """,
    show_members_responses=True,
    get_member_information_tool=True,
    add_member_tools_to_context=True,
    add_history_to_context=True,
    debug_mode=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    teams=[research_team],
    a2a_interface=True,
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS with A2A interface.

    You can run the Agent via A2A protocol:
    POST http://localhost:7777/teamss/{id}/v1/message:send
    For streaming responses:
    POST http://localhost:7777/teams/{id}/v1/message:stream
    Retrieve the agent card at:
    GET  http://localhost:7777/teams/{id}/.well-known/agent-card.json

    """
    agent_os.serve(app="research_team:app", reload=True, port=7777)
