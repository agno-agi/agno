"""
Budget Timeout
==============
VerificationConfig(timeout=...) is a wall clock over the whole loop, measured from the
first model call and checked between attempts. A running model call or check is never
interrupted, so the run may overshoot by one attempt, but it never starts another one
once the clock has run out.

The check here never passes and the clock is one second, shorter than any model call, so
the run ends with stop_reason "timeout" after a single attempt instead of exhausting all
five.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.verifiers import VerificationConfig

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def never_passes(run_output: RunOutput) -> str:
    """A check that always fails, so the clock is what ends the run."""
    return "not there yet"


agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    verifiers=[never_passes],
    verification=VerificationConfig(max_attempts=5, timeout=1.0),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run("Say hello.")

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    print(
        f"Attempts: {len(verification.attempts)} of {agent.verification.max_attempts}"
    )
