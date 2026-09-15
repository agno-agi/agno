"""
Stop On Failure
===============
stop_on_failure=True ends the run on the first failure instead of sending the evidence back to
the model. Use it for checks whose failure no model action can fix: a missing license
file, a wrong environment, a precondition the operator has to satisfy.

Here the check requires a config file the agent has no tool to create. It fails on
attempt 0, and the run ends with stop_reason "fatal" and one attempt, though the budget
allowed three.
"""

from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.verifiers import VerificationConfig, verifier

# ---------------------------------------------------------------------------
# Define Checks
# ---------------------------------------------------------------------------

CONFIG_FILE = Path("tmp/verifiers/stop_on_failure_check/config.toml")


def config_present(run_output: RunOutput) -> Union[bool, str]:
    """The operator must provide config.toml before this agent can do anything."""
    if CONFIG_FILE.exists():
        return True
    return "config.toml is missing; an operator must provide it"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    verifiers=[verifier(config_present, stop_on_failure=True)],
    verification=VerificationConfig(max_attempts=3),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run("Summarize the project configuration.")

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    print(
        f"Attempts: {len(verification.attempts)} of {agent.verification.max_attempts}"
    )
