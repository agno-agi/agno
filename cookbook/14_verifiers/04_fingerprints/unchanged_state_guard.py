"""
Unchanged State Guard
=====================
A fingerprint captures a stable digest of world state between attempts; with
stop_on_unchanged_state=True, a failed attempt that changed nothing ends the run unverified
immediately instead of burning the rest of the budget on identical retries.

GitWorktreeFingerprint digests a git worktree: HEAD, status, diffs, and untracked file
content. The state the verifiers judge is captured before they run, and the comparison
baseline settles after they run, so a verifier's own artifacts are never mistaken for
the agent's work.

The agent here can only list and search files, so whatever it says, the worktree does not
change: the first failed attempt leaves the state unchanged and the run ends with
stop_reason "unchanged_state" after one attempt, not five.
"""

import subprocess
from pathlib import Path
from typing import Union

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.tools.file import FileTools
from agno.verifiers import GitWorktreeFingerprint, VerificationConfig

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# A scratch git repository, so the fingerprint has a worktree to digest. git init on an
# existing repository is a no-op, and the agent cannot write, so every run starts the same.
REPO = Path("tmp/verifiers/unchanged_state_guard")
REPO.mkdir(parents=True, exist_ok=True)
subprocess.run(["git", "init", "-q"], cwd=REPO, check=True)
(REPO / "README.md").write_text("# Scratch\n")


def changelog_exists(run_output: RunOutput) -> Union[bool, str]:
    """The definition of done: CHANGELOG.md exists in the repository."""
    if (REPO / "CHANGELOG.md").exists():
        return True
    return "CHANGELOG.md does not exist"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    # The agent can only list and search the repository, never write to it.
    tools=[
        FileTools(
            base_dir=REPO,
            enable_save_file=False,
            enable_read_file=False,
            enable_read_file_chunk=False,
            enable_replace_file_chunk=False,
        )
    ],
    verifiers=[changelog_exists],
    verification=VerificationConfig(
        max_attempts=5,
        stop_on_unchanged_state=True,
        fingerprint=GitWorktreeFingerprint(str(REPO)),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_output = agent.run(
        "Create a CHANGELOG.md for this repository with one initial entry."
    )

    verification = run_output.verification
    print(f"Status: {run_output.status.value}")
    print(
        f"Verification: {verification.status.value} / {verification.stop_reason.value}"
    )
    for attempt in verification.attempts:
        print(
            f"Attempt {attempt.index}: passed {attempt.passed} | state_unchanged {attempt.state_unchanged}"
        )
    print(
        f"Attempts: {len(verification.attempts)} of {agent.verification.max_attempts}"
    )
