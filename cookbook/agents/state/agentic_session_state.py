from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/agents.db")
agent = Agent(
    model=OpenAIChat(id="o3-mini"),
    db=db,
    session_state={"shopping_list": []},
    add_session_state_to_context=True,  # Required so the agent is aware of the session state
    enable_agentic_state=True,
)

agent.print_response("Add milk, eggs, and bread to the shopping list")

agent.print_response("I picked up the eggs, now what's on my list?")

print(f"Session state: {agent.get_session_state()}")
