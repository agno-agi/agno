"""
No-op Guard
===========
An agent that "completes" without changing the world is the commonest lie. A fingerprint
captures a stable digest of world state between attempts; with stop_on_noop=True, a
FAILED attempt that changed nothing ends the run unverified immediately instead of
burning the rest of the budget on identical retries.

GitWorktreeFingerprint digests a git worktree: HEAD, status, diffs, and untracked file
content. The state the verifiers judge is captured before they run, and the comparison
baseline settles after they run, so a verifier's own artifacts are never mistaken for
the agent's work.
"""

import subprocess
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verifiers import GitWorktreeFingerprint, VerificationConfig

# ---------------------------------------------------------------------------
# A scratch git repository
# ---------------------------------------------------------------------------

repo = Path(tempfile.mkdtemp(prefix="noop_guard_"))
subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
(repo / "README.md").write_text("# Scratch\n")


def changelog_exists(run_output) -> object:
    """The definition of done: CHANGELOG.md exists in the repository."""
    return True if (repo / "CHANGELOG.md").exists() else "CHANGELOG.md does not exist"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=repo)],
    verifiers=[changelog_exists],
    verification=VerificationConfig(
        max_attempts=5,
        stop_on_noop=True,
        fingerprint=GitWorktreeFingerprint(str(repo)),
    ),
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

output = agent.run("Create a CHANGELOG.md for this repository with one initial entry.")

print("status:", output.status)
print("verification:", output.verification.status, "/", output.verification.stop_reason)
for attempt in output.verification.attempts:
    print("attempt", attempt.index, "| noop:", attempt.noop, "| passed:", attempt.passed)
