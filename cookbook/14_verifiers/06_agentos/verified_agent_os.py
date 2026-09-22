"""
Verified Agent on AgentOS
=========================
Verifiers live on the agent, so every surface the agent runs on runs the loop, AgentOS
included. Serve this app, call the run endpoint, and watch the VerificationStarted /
VerificationCompleted events arrive on the stream; a run whose checks never pass shows
status UNVERIFIED in the run list.

The check requires a closing "Call to action:" line the request never mentions, so each
run's attempt 0 fails and attempt 1 rewrites pitch.md with the line.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/14_verifiers/06_agentos/verified_agent_os.py
Try: curl -N -X POST http://localhost:7777/agents/verified-writer/runs -F "message=Write pitch.md: two sentences pitching code review." -F "stream=true"
"""

from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty pitch.md at every server start, so an earlier run's file never passes the check.
# The run rows live in tmp/verifiers/agentos.db, outside the agent's writable tree.
WORKDIR = Path("tmp/verifiers/verified_agent_os")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "pitch.md").write_text("")


def pitch_complete(run_output: RunOutput) -> Union[bool, str]:
    """The definition of done: pitch.md ends with a Call to action line."""
    if "Call to action:" not in (WORKDIR / "pitch.md").read_text():
        return "pitch.md has no 'Call to action:' line"
    return True


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    id="verified-writer",
    name="Verified Writer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/verifiers/agentos.db"),
    tools=[FileTools(base_dir=WORKDIR)],
    verifiers=[pitch_complete],
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="verified_agent_os:app", reload=True)
