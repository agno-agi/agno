"""
Member Verified
===============
Verifiers are an agent property, so a team member carries its own definition of done
into every delegation: the member's run loop verifies the member's work, and the leader
can read the outcome off member_responses.

Teams take verifiers too - Team(verifiers=[...]) gates the leader's final answer the
same way; here the gate is on the member, where the evidence lives.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# A member with its own definition of done
# ---------------------------------------------------------------------------

workdir = Path(tempfile.mkdtemp(prefix="member_verified_"))


def summary_exists(run_output) -> object:
    """The member's definition of done: summary.md exists."""
    return True if (workdir / "summary.md").exists() else "summary.md does not exist yet"


writer = Agent(
    name="Writer",
    role="Writes files the team needs",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    verifiers=[summary_exists],
)

team = Team(
    members=[writer],
    model=OpenAIResponses(id="gpt-5.5"),
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

output = team.run("Have the writer produce summary.md: three sentences on why tests matter.")

print("team status:", output.status)
for member_run in output.member_responses or []:
    print("member status:", member_run.status)
    if member_run.verification is not None:
        print(
            "member verification:",
            member_run.verification.status,
            "/",
            member_run.verification.stop_reason,
        )
print("summary.md written:", (workdir / "summary.md").exists())
