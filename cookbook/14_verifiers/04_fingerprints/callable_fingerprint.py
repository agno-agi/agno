"""
Callable Fingerprint
====================
World state is not always a git worktree. CallableFingerprint wraps any function that
returns a digest string, so the unchanged-state guard works over an in-memory ledger, a database
row count, a remote resource, anything you can hash.

The check requires an entry tagged [approved] that the prompt never mentions, so attempt
0 fails, but the ledger did change, so the state is not unchanged and the loop
continues; attempt 1 adds the tagged entry and passes.
"""

import hashlib
import json
from typing import List, Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.verifiers import CallableFingerprint, VerificationConfig

# ---------------------------------------------------------------------------
# Create Tool
# ---------------------------------------------------------------------------

# The decision ledger lives in memory for the length of the run.
LEDGER: List[str] = []


def add_entry(text: str) -> str:
    """Append one entry to the decision ledger.

    Args:
        text: The entry to record.
    """
    LEDGER.append(text)
    return f"recorded entry {len(LEDGER)}"


def ledger_digest() -> str:
    """A stable digest of the ledger contents."""
    return hashlib.sha256(json.dumps(LEDGER).encode()).hexdigest()


def approved_entry(run_output: RunOutput) -> Union[bool, str]:
    """The definition of done: at least one entry carries the [approved] tag."""
    if any("[approved]" in entry for entry in LEDGER):
        return True
    return "no ledger entry carries the [approved] tag"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[add_entry],
    verifiers=[approved_entry],
    verification=VerificationConfig(
        max_attempts=3,
        stop_on_unchanged_state=True,
        fingerprint=CallableFingerprint(ledger_digest),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run("Record the decision to adopt code review in the ledger.")

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        print(
            f"Attempt {attempt.index}: passed {attempt.passed} | state_unchanged {attempt.state_unchanged}"
        )
    print(f"Ledger: {LEDGER}")
