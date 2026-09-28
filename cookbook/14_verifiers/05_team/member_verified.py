"""
Member Verified
===============
Verifiers are an agent property, so a team member carries its own definition of done
into every delegation: the member's run loop verifies the member's work, and the leader
can read the outcome off member_responses.

The member's check requires a closing "Key takeaway:" line the leader's task never
mentions, so the member's attempt 0 fails, the evidence goes back to the member, and
attempt 1 adds the line before the member returns to the leader.

Teams take verifiers too - Team(verifiers=[...]) gates the leader's final answer the
same way (leader_verified.py); here the gate is on the member, where the evidence lives.
"""

from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.team import Team
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty summary.md at the start of every run, so an earlier run's file never passes the check.
WORKDIR = Path("tmp/verifiers/member_verified")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "summary.md").write_text("")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------


def summary_complete(run_output: RunOutput) -> Union[bool, str]:
    """The member's definition of done: summary.md ends with a Key takeaway line."""
    if "Key takeaway:" not in (WORKDIR / "summary.md").read_text():
        return "summary.md has no 'Key takeaway:' line"
    return True


writer = Agent(
    name="Writer",
    role="Writes files the team needs",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=WORKDIR)],
    verifiers=[summary_complete],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    members=[writer],
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=InMemoryDb(),
    store_member_responses=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Have the writer produce summary.md: three sentences on why tests matter."
    )

    run_output = team.get_last_run_output()
    for member_run in run_output.member_responses or []:
        verification = member_run.verification
        if verification is None:
            continue
        print(
            f"\nMember verification: {verification.status.value} / {verification.stop_reason.value}"
        )
        for attempt in verification.attempts:
            for verdict in attempt.verdicts:
                result = "PASS" if verdict.passed else "FAIL"
                print(f"Attempt {attempt.index}: {result} {verdict.name}")
