"""
The Unverified Outcome
======================
A run whose verifiers never pass ends with RunStatus.unverified, and the full
verification record is persisted with the run row.

The verifier here is impossible on purpose, so the run exhausts its budget and the
record shows every attempt with its evidence.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.verifiers import VerificationConfig

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

DB_FILE = "tmp/verifiers/unverified.db"


def impossible(run_output: RunOutput) -> str:
    """A check that can never pass, to show the unverified leg."""
    return "the moon is not made of cheese yet"


agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file=DB_FILE),
    verifiers=[impossible],
    verification=VerificationConfig(max_attempts=2),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run("Say hello.", session_id="unverified-demo")

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    assert run_output.status == RunStatus.unverified, (
        f"Expected unverified, got {run_output.status}"
    )
    print(f"Stop reason: {verification.stop_reason.value}")
    print(f"Attempts: {len(verification.attempts)}")

    # The record is persisted with the run row and reads back from the database.
    session = agent.get_session(session_id="unverified-demo")
    stored = session.get_run(run_output.run_id)
    print(f"Stored status: {stored.status}")
    print(
        f"Stored record: {stored.verification.status.value} / {stored.verification.stop_reason.value}"
    )
