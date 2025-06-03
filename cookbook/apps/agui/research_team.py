from agno.agent.agent import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat
from agno.team.team import Team

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
    show_tool_calls=True,
    show_members_responses=True,
    get_member_information_tool=True,
    add_member_tools_to_system_message=True,
)

agui_app = AGUIApp(
    team=research_team,
    name="Research Team AG-UI",
    app_id="research_team_agui",
    description="A research team that demonstrates AG-UI protocol integration.",
)

app = agui_app.get_app()

if __name__ == "__main__":
    agui_app.serve(app="research_team:app", port=8000, reload=True)
