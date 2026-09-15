"""
Flaky Check
===========
max_retries=N re-runs the check itself up to N extra times before a failure counts. Use it for
checks whose failure may be the check's own fault: a port still opening, an eventually
consistent store, a network probe.

The probe here fails deterministically on its first two calls and passes on the third,
so with max_retries=2 the attempt passes on the model's first try. Without max_retries the same probe
would fail the attempt and burn a model re-entry on a problem the model never caused.
"""

from typing import Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.verifiers import check

# ---------------------------------------------------------------------------
# Define Checks
# ---------------------------------------------------------------------------

# How many times the probe has been called, across retries.
PROBE_CALLS = 0


def service_ready(run_output: RunOutput) -> Union[bool, str]:
    """Pass on the third call, as a slow-to-settle service would."""
    global PROBE_CALLS
    PROBE_CALLS += 1
    if PROBE_CALLS < 3:
        return f"probe {PROBE_CALLS}: service not ready"
    return True


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    verifiers=[check(service_ready, max_retries=2)],
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
    print(f"Model attempts: {len(verification.attempts)}")
    print(f"Probe calls: {PROBE_CALLS}")
