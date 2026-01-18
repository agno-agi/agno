from agno.os import AgentOS
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-5"),
    db=SqliteDb(db_file="agno.db"),
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agno_agent:app", reload=True)
