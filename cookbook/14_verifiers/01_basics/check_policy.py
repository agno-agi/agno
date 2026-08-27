"""
Per-Check Policy
================
Policy rides the check: each verifier carries its own rules while the loop budget stays
on the agent.

- required=False makes a check ADVISORY: it runs and reports (a [WARN] line the model can
  act on) but never gates the outcome.
- run_when gates a check on this attempt's earlier verdicts - here the LLM judge only runs
  once the cheap required checks pass, so failed attempts never pay for a judge call.
- rerun retries the check itself before a failure counts (for flaky checks).
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.scorer import JudgeScorer
from agno.tools.file import FileTools
from agno.verifiers import ScorerVerifier, check

# ---------------------------------------------------------------------------
# Checks with their policy
# ---------------------------------------------------------------------------

workdir = Path(tempfile.mkdtemp(prefix="check_policy_"))


def summary_exists(run_output) -> object:
    """Required: summary.md must exist."""
    return True if (workdir / "summary.md").exists() else "summary.md does not exist yet"


def short_enough(run_output) -> object:
    """Advisory: prefer summaries under 600 characters, but do not block on it."""
    path = workdir / "summary.md"
    if path.exists() and len(path.read_text()) > 600:
        return "summary.md is over 600 characters; shorter is better"
    return True


def required_passing(verdicts) -> bool:
    """Run the judge only when every required check so far has passed."""
    return all(v.passed for v in verdicts if v.required and not v.skipped)


judge = JudgeScorer(
    model=OpenAIResponses(id="gpt-5.5"),
    criteria="The summary is concrete: it names at least one specific benefit, no filler.",
    mode="numeric",
    threshold=7,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=workdir)],
    verifiers=[
        summary_exists,
        check(short_enough, required=False),
        ScorerVerifier(judge, run_when=required_passing),
    ],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

output = agent.run("Write summary.md: a short summary of why code review matters.")

print("status:", output.status)
print("verification:", output.verification.status, "/", output.verification.stop_reason)
for attempt in output.verification.attempts:
    for verdict in attempt.verdicts:
        if verdict.skipped:
            state = "SKIP"
        elif verdict.passed:
            state = "PASS"
        else:
            state = "FAIL" if verdict.required else "WARN"
        print("attempt", attempt.index, "|", state, verdict.name)
