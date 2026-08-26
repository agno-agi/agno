"""
Streaming the Verification Loop
===============================
The loop is visible live: VerificationStarted and VerificationCompleted events arrive
per attempt between the content of each try, so a UI can render the checks as they run.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

workdir = Path(tempfile.mkdtemp(prefix="streamed_"))


def notes_exist(run_output) -> object:
    """The definition of done: notes.txt exists."""
    return True if (workdir / "notes.txt").exists() else "notes.txt does not exist yet"


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    verifiers=[notes_exist],
)

# ---------------------------------------------------------------------------
# Run with streaming
# ---------------------------------------------------------------------------

for event in agent.run(
    "Write three bullet points about typed languages into notes.txt.",
    stream=True,
    stream_events=True,
):
    name = getattr(event, "event", "")
    if name == "VerificationStarted":
        print(
            "\n[verification attempt",
            event.attempt,
            "of",
            event.max_attempts,
            "started]",
        )
    elif name == "VerificationCompleted":
        outcome = "passed" if event.passed else "failed"
        print("[verification attempt", event.attempt, outcome + "]")
        for verdict in event.verdicts or []:
            print(
                "  -",
                verdict["name"] + ":",
                "pass" if verdict["passed"] else verdict["summary"],
            )
    elif name == "RunContent":
        print(event.content or "", end="", flush=True)

print()
