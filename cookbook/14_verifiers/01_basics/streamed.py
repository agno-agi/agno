"""
Streaming the Verification Loop
===============================
The loop is visible live: VerificationStarted and VerificationCompleted events arrive
per attempt between the content of each try, so a UI can render the checks as they run.

The check requires a closing "Further reading" line the prompt never asks for, so the
first attempt fails on the stream and the second one carries the fix.
"""

from pathlib import Path
from typing import Union

from agno.agent import Agent, RunEvent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty notes.txt at the start of every run, so an earlier run's file never passes the check.
WORKDIR = Path("tmp/verifiers/streamed")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "notes.txt").write_text("")


def notes_complete(run_output: RunOutput) -> Union[bool, str]:
    """The definition of done: notes.txt ends with a Further reading line."""
    if "Further reading:" not in (WORKDIR / "notes.txt").read_text():
        return "notes.txt has no 'Further reading:' line"
    return True


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=WORKDIR)],
    verifiers=[notes_complete],
)

# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for event in agent.run(
        "Write three bullet points about typed languages into notes.txt.",
        stream=True,
        stream_events=True,
    ):
        if event.event == RunEvent.verification_started:
            print(
                f"\n[Verification attempt {event.attempt} of {event.max_attempts} started]"
            )
        elif event.event == RunEvent.verification_completed:
            outcome = "passed" if event.passed else "failed"
            print(f"[Verification attempt {event.attempt} {outcome}]")
            for verdict in event.verdicts or []:
                # A failing verdict's report opens with the evidence the model sees next.
                summary = "pass" if verdict.passed else verdict.report.splitlines()[0]
                print(f"  - {verdict.name}: {summary}")
        elif event.event == RunEvent.run_content:
            print(event.content or "", end="", flush=True)

    print()
