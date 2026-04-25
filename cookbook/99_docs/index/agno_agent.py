from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace

agent = Agent(
    name="Agno Agent",
    model="openai:gpt-5.4",
    tools=[
        Workspace(
            root=".",
            allowed_tools=["read", "list", "search"],
            confirm_tools=["write", "edit", "delete", "shell"],
        )
    ],
)

agent_os = AgentOS(
    agents=[agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()
