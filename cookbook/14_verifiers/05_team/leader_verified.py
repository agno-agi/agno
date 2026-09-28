"""
Leader Verified
===============
Team(verifiers=[...]) gates the leader's final answer: when the leader stops, the checks
run against the team's output, a failure goes back to the leader as evidence, and the
leader keeps working, delegating again if needed, inside the same team run.

The check requires a closing "Sources:" line the prompt never asks for, so the leader's
first answer fails, and the second one carries it. The same VerificationConfig applies;
an answer that never passes ends the team run unverified.
"""

from typing import Union

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.verifiers import VerificationConfig

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Answers factual questions about programming languages",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------


def answer_complete(run_output: TeamRunOutput) -> Union[bool, str]:
    """The leader's definition of done: the answer ends with a Sources: line."""
    if "Sources:" not in (run_output.content or ""):
        return "the answer has no 'Sources:' line naming where the facts came from"
    return True


team = Team(
    members=[researcher],
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=InMemoryDb(),
    verifiers=[answer_complete],
    verification=VerificationConfig(max_attempts=3),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Ask the researcher when Python 3 was first released, then answer in two "
        "sentences."
    )

    run_output = team.get_last_run_output()
    verification = run_output.verification
    print(
        f"\nTeam verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        for verdict in attempt.verdicts:
            result = "PASS" if verdict.passed else "FAIL"
            print(f"Attempt {attempt.index}: {result} {verdict.name}")
