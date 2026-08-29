"""
The Unverified Outcome
======================
A run whose verifiers never pass does not pretend: it ends with RunStatus.unverified,
and the full verification record is persisted with the run row.

The verifier here is impossible on purpose, so the run exhausts its budget. The status
tells the truth, and the record shows every attempt with its evidence.
"""

import tempfile

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.base import RunStatus
from agno.verifiers import VerificationConfig

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file=tempfile.mkstemp(suffix=".db", prefix="unverified_")[1])


def impossible(run_output) -> str:
    """A check that can never pass, to show the unverified leg."""
    return "the moon is not made of cheese yet"


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    verifiers=[impossible],
    verification=VerificationConfig(max_attempts=2),
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

output = agent.run("Say hello.", session_id="unverified-demo")

print("status:", output.status)
assert output.status == RunStatus.unverified
print("stop_reason:", output.verification.stop_reason)
print("attempts:", len(output.verification.attempts))

# The record is persisted with the run row and reads back from the database.
session = agent.get_session(session_id="unverified-demo")
stored = session.get_run(output.run_id)
print("stored status:", stored.status)
print(
    "stored record:", stored.verification.status, "/", stored.verification.stop_reason
)
