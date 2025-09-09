from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

db = SqliteDb(db_file="tmp/agents.db")
shopping_agent = Agent(
    name="Shopping List Agent",
    role="Manage the shopping list",
    model=OpenAIChat(id="o3-mini"),
    db=db,
    add_session_state_to_context=True,  # Required so the agent is aware of the session state
    enable_agentic_state=True,
)

team = Team(
    members=[shopping_agent],
    session_state={"shopping_list": []},
    db=db,
    add_session_state_to_context=True,  # Required so the team is aware of the session state
    enable_agentic_state=True,
    description="You are a team that manages a shopping list and chores",
    show_members_responses=True,
)


team.print_response("Add milk, eggs, and bread to the shopping list")

team.print_response("I picked up the eggs, now what's on my list?")

print(f"Session state: {team.get_session_state()}")
