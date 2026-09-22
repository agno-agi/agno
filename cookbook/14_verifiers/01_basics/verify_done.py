"""
Verify Done
===========
The simplest verifier: a callable that checks the file the agent wrote.

The agent is asked to write a report. The check requires a "Trade-offs" section the
prompt never mentions, so attempt 0 fails with that gap as evidence, the framework sends
the evidence back into the run, and the model completes the file on attempt 1.
"""

from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty report.md at the start of every run, so an earlier run's file never passes the check.
WORKDIR = Path("tmp/verifiers/verify_done")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "report.md").write_text("")


def report_complete(run_output: RunOutput) -> Union[bool, str]:
    """The definition of done: report.md has a Trade-offs section."""
    if "## Trade-offs" not in (WORKDIR / "report.md").read_text():
        return "report.md has no '## Trade-offs' section"
    return True


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=InMemoryDb(),
    tools=[FileTools(base_dir=WORKDIR)],
    verifiers=[report_complete],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Prepare a short report on the benefits of code review. Call it report.md, "
        "then reply with one sentence on what it covers."
    )

    run_output = agent.get_last_run_output()
    verification = run_output.verification
    print(
        f"\nVerification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        for verdict in attempt.verdicts:
            result = "PASS" if verdict.passed else "FAIL"
            print(f"Attempt {attempt.index}: {result} {verdict.name}")
