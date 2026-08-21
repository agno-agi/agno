"""
No-op Guard: an agent that claims done without touching the world
=================================================================
GitWorktreeFingerprint digests a worktree: HEAD, status, diffs, and the content of every
untracked file. The runner captures it before the first attempt and after every attempt.
With stop_on_noop=True, a failed attempt that changed nothing ends the run as unverified
right away: the agent has stopped affecting the world, so more turns are waste.

The agent here has no tools, so it can only claim. The verifier wants a file; the
fingerprint shows nothing changed; the run stops after one attempt with stop_reason "noop".
"""

import subprocess
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.verify import (
    VERIFICATION_NOTICE,
    GitWorktreeFingerprint,
    VerifierLimits,
    run_verified,
)

repo = Path(tempfile.mkdtemp(prefix="noop_guard_"))
subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
target = repo / "notes.md"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[VERIFICATION_NOTICE],
)


def notes_exist(run):
    return target.exists() or "notes.md does not exist in the repository"


result = run_verified(
    agent,
    "Create notes.md in the repository with three bullet points about indexing, then stop.",
    verifiers=[notes_exist],
    limits=VerifierLimits(max_continuations=3, stop_on_noop=True),
    fingerprint=GitWorktreeFingerprint(str(repo)),
)

print("status:", result.status)
print("stop_reason:", result.stop_reason)
print("attempts:", len(result.attempts))
print(
    "baseline fingerprint:",
    (result.verification.baseline_fingerprint or "unknown")[:12],
)
for attempt in result.attempts:
    print(
        f"attempt {attempt.index}: fingerprint={(attempt.fingerprint or 'unknown')[:12]} noop={attempt.noop}"
    )
print()
print("model said:", (result.output.content or "")[:200])
