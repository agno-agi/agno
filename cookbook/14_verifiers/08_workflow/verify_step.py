"""
Verify as a Workflow Step
=========================
Run agents, then a verification step, then continue - conditional continue with evidence.

The Verify step checks the previous step's work against executable evidence. On failure it
loops back to the on_fail step with the evidence report attached to that step's input, up
to max_attempts times; on success the workflow continues. Attempts exhausted, the step ends
with success=False and the verification record on its StepOutput, where the workflow's
ordinary conditional machinery can route it.

The gate requires an "Upgrade notes" section the prompt never mentions, so attempt 0 fails,
the writer re-runs with the evidence, and attempt 1 passes before publish runs.
"""

from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.tools.file import FileTools
from agno.workflow import Step, Verify, Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty RELEASE_NOTES.md at the start of every run, so an earlier run's file never passes the gate.
WORKDIR = Path("tmp/verifiers/verify_step")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "RELEASE_NOTES.md").write_text("")

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

writer = Agent(
    name="writer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=WORKDIR)],
    instructions="You write files exactly as asked.",
)

publisher = Agent(
    name="publisher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Announce the release in one short sentence.",
)


def notes_complete(run_output: RunOutput) -> Union[bool, str]:
    """The gate between writing and publishing: RELEASE_NOTES.md names the version and
    carries an Upgrade notes section."""
    text = (WORKDIR / "RELEASE_NOTES.md").read_text()
    if "1.4.0" not in text:
        return "RELEASE_NOTES.md does not mention version 1.4.0"
    if "## Upgrade notes" not in text:
        return "RELEASE_NOTES.md has no '## Upgrade notes' section"
    return True


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------

workflow = Workflow(
    name="release-notes",
    steps=[
        Step(name="write", agent=writer),
        # stop_on_unverified halts the pipeline when the gate ends unverified: publish never runs.
        Verify(
            [notes_complete], on_fail="write", max_attempts=3, stop_on_unverified=True
        ),
        Step(name="publish", agent=publisher),
    ],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    workflow_output = workflow.run(
        "Draft RELEASE_NOTES.md for version 1.4.0: two bullet points."
    )

    print(f"Workflow status: {workflow_output.status.value}")
    # The gate owns the segment it re-runs: "write" is nested under the verify step's
    # own steps rather than listed at the top level of step_results.
    for step in workflow_output.step_results or []:
        print(f"Step: {step.step_name} | success: {step.success}")
        for nested in step.steps or []:
            print(f"  Segment step: {nested.step_name} | success: {nested.success}")
        verification = step.verification
        if verification is not None:
            print(
                f"  Verification: {verification.status.value} / {verification.stop_reason.value}"
            )
            for attempt in verification.attempts:
                for verdict in attempt.verdicts:
                    result = "PASS" if verdict.passed else "FAIL"
                    print(f"  Attempt {attempt.index}: {result} {verdict.name}")
    print(f"\n{workflow_output.content}")
