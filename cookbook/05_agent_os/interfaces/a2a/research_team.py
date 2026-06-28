"""
Research Team
=============

Demonstrates research team.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

researcher = Agent(
    name="researcher",
    id="researcher",
    role="Research Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a research assistant. Find information and provide detailed analysis.",
    tools=[WebSearchTools()],
    markdown=True,
)

writer = Agent(
    name="writer",
    id="writer",
    role="Content Writer",
    model=OpenAIChat(id="o4-mini"),
    instructions="You are a content writer. Create well-structured content based on research.",
    tools=[WebSearchTools()],
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


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS with the A2A 1.0 interface.

    Endpoints for a Team (A2A 1.0, JSON-RPC 2.0 envelope, flat Part with mediaType):
        GET  http://localhost:7777/a2a/teams/{id}/.well-known/agent-card.json
        POST http://localhost:7777/a2a/teams/{id}/v1                 (JSON-RPC: SendMessage / SendStreamingMessage — what the a2a-sdk Client targets)
        POST http://localhost:7777/a2a/teams/{id}/v1/message:send    (legacy URL-style, kept for back-compat)
        POST http://localhost:7777/a2a/teams/{id}/v1/message:stream  (legacy URL-style, kept for back-compat)

    Test with the official a2a-sdk client (see README.md for a runnable snippet)
    or with the a2a-inspector at https://github.com/a2aproject/a2a-inspector.
    """
    agent_os.serve(app="research_team:app", reload=True, port=7777)
