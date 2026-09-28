"""
Printing an Unverified Run
==========================
print_response prints the last attempt's answer for a run whose checks never passed, the
same as for a finished run. The outcome lives on the run itself: read the status and the
stop reason off get_last_run_output() after printing.

The check is impossible on purpose, with a budget of two attempts.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.verifiers import VerificationConfig

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def impossible(run_output: RunOutput) -> str:
    """A check that can never pass, to show the unverified outcome."""
    return "the moon is not made of cheese yet"


agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=InMemoryDb(),
    verifiers=[impossible],
    verification=VerificationConfig(max_attempts=2),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("Say hello.", stream=True)

    run_output = agent.get_last_run_output()
    verification = run_output.verification
    print(f"\nStatus: {run_output.status}")
    print(f"Stop reason: {verification.stop_reason.value}")
    print(
        f"Attempts: {len(verification.attempts)} of {agent.verification.max_attempts}"
    )
