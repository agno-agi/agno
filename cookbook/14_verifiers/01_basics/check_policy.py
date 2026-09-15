"""
Per-Check Policy
================
Policy rides the check: each verifier carries its own rules while the loop budget stays
on the agent.

- required=False makes a check advisory: it runs and reports (a [WARN] line the model can
  act on) but never gates the outcome.
- run_condition gates a check on this attempt's earlier verdicts - here the LLM judge only runs
  once the cheap required checks pass, so failed attempts never pay for a judge call.

The other two knobs have their own files: max_retries (flaky_check.py) retries the check itself
before a failure counts, and stop_on_failure (stop_on_failure_check.py) ends the run on the first failure.
"""

from pathlib import Path
from typing import List, Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.scorer import JudgeScorer
from agno.tools.file import FileTools
from agno.verifiers import ScorerVerifier, Verdict, verifier

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Empty summary.md at the start of every run, so an earlier run's file never passes the checks.
WORKDIR = Path("tmp/verifiers/check_policy")
WORKDIR.mkdir(parents=True, exist_ok=True)
(WORKDIR / "summary.md").write_text("")

# ---------------------------------------------------------------------------
# Define Checks
# ---------------------------------------------------------------------------


def summary_written(run_output: RunOutput) -> Union[bool, str]:
    """Required: summary.md must not be empty."""
    if (WORKDIR / "summary.md").read_text().strip():
        return True
    return "summary.md is still empty"


def short_enough(run_output: RunOutput) -> Union[bool, str]:
    """Advisory: prefer summaries under 600 characters, but do not block on it."""
    if len((WORKDIR / "summary.md").read_text()) > 600:
        return "summary.md is over 600 characters; shorter is better"
    return True


def required_passing(verdicts: List[Verdict]) -> bool:
    """Run the judge only when every required check so far has passed."""
    return all(v.passed for v in verdicts if v.required and not v.skipped)


judge = JudgeScorer(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    criteria="The summary is concrete: it names at least one specific benefit, no filler.",
    mode="numeric",
    threshold=7,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=WORKDIR)],
    verifiers=[
        summary_written,
        verifier(short_enough, required=False),
        ScorerVerifier(judge, run_condition=required_passing),
    ],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run(
        "Write summary.md: a short summary of why code review matters."
    )

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        for verdict in attempt.verdicts:
            if verdict.skipped:
                result = "SKIP"
            elif verdict.passed:
                result = "PASS"
            else:
                result = "FAIL" if verdict.required else "WARN"
            print(f"Attempt {attempt.index}: {result} {verdict.name}")
