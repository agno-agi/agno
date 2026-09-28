"""
Async Verification
==================
The loop has an async version: agent.arun runs the same gate, and a check written as a
coroutine is awaited in place (a sync check runs in a thread). Nothing about the check
changes between the two paths.

The check requires a "Trade-offs" section the prompt never mentions, so attempt 0 fails
and attempt 1 completes the file.
"""

import asyncio
from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty report.md at the start of every run, so an earlier run's file never passes the check.
WORKDIR = Path("tmp/verifiers/async_verify")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "report.md").write_text("")


async def report_complete(run_output: RunOutput) -> Union[bool, str]:
    """The definition of done, as a coroutine: report.md has a Trade-offs section."""
    text = await asyncio.to_thread((WORKDIR / "report.md").read_text)
    if "## Trade-offs" not in text:
        return "report.md has no '## Trade-offs' section"
    return True


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=WORKDIR)],
    verifiers=[report_complete],
)

# ---------------------------------------------------------------------------
# Run Async Demo
# ---------------------------------------------------------------------------


async def main():
    run_output = await agent.arun(
        "Prepare a short report on the benefits of code review. Call it report.md."
    )

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        for verdict in attempt.verdicts:
            result = "PASS" if verdict.passed else "FAIL"
            print(f"Attempt {attempt.index}: {result} {verdict.name}")


if __name__ == "__main__":
    asyncio.run(main())
