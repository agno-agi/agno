"""AgentOS HITL: External Tool Execution

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/external_tool_execution.py

A team member's tool is marked for external execution. The run pauses and
the API response includes the tool name and arguments. The client executes
the tool externally, then sends the result back via continue_run.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/hitl/external_tool_execution.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_hitl.db",
    session_table="hitl_external_exec_sessions",
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(external_execution=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to someone. Executed externally."""
    return ""


# ---------------------------------------------------------------------------
# Create members
# ---------------------------------------------------------------------------

email_agent = Agent(
    name="EmailAgent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[send_email],
    instructions=(
        "You MUST call the send_email tool immediately when asked to send an email. "
        "Do NOT simulate or describe sending - use the tool."
    ),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="hitl-external-exec-team",
    name="CommunicationTeam",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[email_agent],
    instructions="Delegate all email requests to the EmailAgent immediately.",
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-external-tool-execution",
    description="AgentOS HITL: external tool execution with result provided by the client",
    agents=[email_agent],
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="external_tool_execution:app", port=7777, reload=True)
