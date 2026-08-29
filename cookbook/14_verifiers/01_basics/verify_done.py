"""
Verify Done
===========
The simplest verifier: a callable that checks the world, not the model's words.

The agent is asked to write a file. The model tends to describe the file instead of
writing it, so the verifier fails the first attempt with evidence, the framework sends
that evidence back into the run, and the model actually does the work on attempt two.
One run, one run_id, one transcript.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

workdir = Path(tempfile.mkdtemp(prefix="verify_done_"))


def report_exists(run_output) -> object:
    """The definition of done: report.md exists and is not empty."""
    report = workdir / "report.md"
    if not report.exists():
        return "report.md does not exist yet"
    if not report.read_text().strip():
        return "report.md exists but is empty"
    return True


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    verifiers=[report_exists],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# A lazy prompt on purpose: the model may claim success without writing anything,
# and the verifier holds it to the evidence.
output = agent.run(
    "Prepare a short report on the benefits of code review. Call it report.md."
)

print("status:", output.status)
print("verification:", output.verification.status, "/", output.verification.stop_reason)
for attempt in output.verification.attempts:
    verdicts = ", ".join(
        ("PASS " if v.passed else "FAIL ") + v.name for v in attempt.verdicts
    )
    print("attempt", attempt.index, "->", verdicts)
print("report.md written:", (workdir / "report.md").exists())
