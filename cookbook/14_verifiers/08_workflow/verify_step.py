"""
Verify as a Workflow Step
=========================
Run agents, then a verification step, then continue - conditional continue with evidence.

The Verify step checks the previous step's work against executable evidence. On failure it
loops back to the on_fail step with the evidence report attached to that step's input, up
to max_rounds times; on success the workflow continues. Rounds exhausted, the step ends
with success=False and the verification record on its StepOutput, where the workflow's
ordinary conditional machinery can route it.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.workflow import Step, Verify, Workflow

# ---------------------------------------------------------------------------
# Agents and the definition of done
# ---------------------------------------------------------------------------

workdir = Path(tempfile.mkdtemp(prefix="verify_step_"))

writer = Agent(
    name="writer",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    instructions="You write files exactly as asked.",
)

publisher = Agent(
    name="publisher",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Announce the release in one short sentence.",
)


def notes_complete(run_output) -> object:
    """The gate between writing and publishing: RELEASE_NOTES.md exists and names a version."""
    path = workdir / "RELEASE_NOTES.md"
    if not path.exists():
        return "RELEASE_NOTES.md does not exist yet"
    text = path.read_text()
    if "1.4.0" not in text:
        return "RELEASE_NOTES.md does not mention version 1.4.0"
    return True


# ---------------------------------------------------------------------------
# The workflow: write, verify, publish
# ---------------------------------------------------------------------------

workflow = Workflow(
    name="release-notes",
    steps=[
        Step(name="write", agent=writer),
        Verify([notes_complete], on_fail="write", max_rounds=2),
        Step(name="publish", agent=publisher),
    ],
)

output = workflow.run("Draft RELEASE_NOTES.md for version 1.4.0: two bullet points.")

print("workflow status:", output.status)
for step in output.step_results or []:
    print("step:", step.step_name, "| success:", step.success)
    if step.verification is not None:
        print(
            "  verification:",
            step.verification.status,
            "/",
            step.verification.stop_reason,
            "|",
            len(step.verification.attempts),
            "attempts",
        )
print("notes written:", (workdir / "RELEASE_NOTES.md").exists())
