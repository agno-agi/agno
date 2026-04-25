from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace

workbench = Agent(
    name="Workbench",
    model="openai:gpt-5.4",
    db=SqliteDb(db_file="agno.db"),  # session storage
    tools=[Workspace(".")],  # sandboxed local workspace
    add_datetime_to_context=True,
    add_history_to_context=True,  # include past runs
    num_history_runs=3,  # last 3 conversations
    enable_agentic_memory=True,  # remembers across sessions
)

# Serve via AgentOS → streaming, auth, session isolation, API endpoints
agent_os = AgentOS(agents=[workbench], tracing=True)
app = agent_os.get_app()
