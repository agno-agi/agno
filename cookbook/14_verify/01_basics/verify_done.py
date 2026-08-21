"""
Verify Done: the file-must-exist gate
=====================================
The model's "done" does not count until a verifier says so. Here the verifier is a plain
callable: it passes when the file exists and otherwise returns the reason as a string,
which becomes the evidence the model reads on its next turn.

The prompt is deliberately lazy so a continuation is likely: watch the attempts list.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verify import VERIFICATION_NOTICE, VerifierLimits, run_verified

workdir = Path(tempfile.mkdtemp(prefix="verify_done_"))
target = workdir / "report.md"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    instructions=[
        "You work inside a scratch directory through the file tools.",
        VERIFICATION_NOTICE,
    ],
)


def report_exists(run):
    # True passes. A string fails, and the string is what the model sees.
    if target.exists():
        return True
    return "report.md does not exist yet; write it with the save_file tool"


result = run_verified(
    agent,
    "Think about what a one-paragraph status report on this project should say. Tell me when you are done.",
    verifiers=[report_exists],
    limits=VerifierLimits(max_continuations=2),
)

print("status:", result.status)
print("stop_reason:", result.stop_reason)
for attempt in result.attempts:
    verdicts = ", ".join(
        f"{v.name}={'PASS' if v.passed else 'FAIL'}" for v in attempt.verdicts
    )
    print(f"attempt {attempt.index} run_id={attempt.run_id} -> {verdicts}")
if target.exists():
    print("report.md:", target.read_text()[:200])
