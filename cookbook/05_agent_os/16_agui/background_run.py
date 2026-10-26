"""
Resume a Background AG-UI Run
=============================

Run an agent detached from the request that started it, so the run keeps going
after the client disconnects and a reconnecting client picks up exactly where
it left off.

A client opts in per request with forwardedProps.agnoBackground. Every event of
such a run carries its resume cursor under metadata.agnoBackground.

Resuming is addressed by run id, so the client has to choose the runId when it
starts the run and send that same runId back with the last cursor it received.
A reconnect that carries a different runId names a run the session does not
have, and is refused rather than resumed.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/background_run.py
Try: POST a background run at http://localhost:7777/background/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Background-Capable Agent
# ---------------------------------------------------------------------------

# Detached execution persists run status, so a database is required.
db = SqliteDb(
    id="agui-background-db",
    db_file="tmp/agui_background.db",
)

long_form_agent = Agent(
    id="agui-background-agent",
    name="AG-UI Background Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions=[
        "Answer at length so the stream lasts long enough to disconnect from.",
        "Write at least six paragraphs.",
    ],
)

agent_os = AgentOS(
    id="agui-background-os",
    description="AgentOS serving resumable background AG-UI runs.",
    agents=[long_form_agent],
    interfaces=[AGUI(agent=long_form_agent, prefix="/background")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Background Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
