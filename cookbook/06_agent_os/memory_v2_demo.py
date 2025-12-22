from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    name="Memory V2 Agent",
    db=db,
    enable_agentic_memory_v2=True,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
    debug_mode=True,
)

agent_os = AgentOS(
    description="Agent with Memory V2 for personalized user context",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="memory_v2_demo:app", reload=True)
