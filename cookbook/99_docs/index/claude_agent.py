from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

agent = ClaudeAgent(
    name="Claude Agent",
    model="claude-opus-4-7",
    allowed_tools=["Read", "Bash"],
    permission_mode="acceptEdits",
)

agent_os = AgentOS(
    agents=[agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()
