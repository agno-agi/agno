"""
Verified Agent on AgentOS
=========================
Because verifiers live on the agent, every surface the agent runs on gets the loop for
free - including AgentOS. Serve this app, call the run endpoint, and watch the
VerificationStarted / VerificationCompleted events arrive on the stream; a run whose
checks never pass shows status UNVERIFIED in the run list.

Run:
    python cookbook/14_verifiers/06_agentos/verified_agent_os.py

Then:
    curl -X POST http://localhost:7777/agents/verified-writer/runs \
        -F "message=Write pitch.md: two sentences pitching code review." \
        -F "stream=true"
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

workdir = Path(tempfile.mkdtemp(prefix="verified_os_"))


def pitch_exists(run_output) -> object:
    """The definition of done: pitch.md exists."""
    return True if (workdir / "pitch.md").exists() else "pitch.md does not exist yet"


agent = Agent(
    id="verified-writer",
    name="Verified Writer",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file=str(workdir / "agentos.db")),
    tools=[FileTools(base_dir=workdir)],
    verifiers=[pitch_exists],
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="verified_agent_os:app", reload=False)
