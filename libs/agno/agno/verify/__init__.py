"""Evidence over prose: an agent's completion claim is checked against executable evidence
before it counts, and a tool call can carry a prediction the framework holds it to.

Two primitives. `run_verified` runs verifiers when the model stops; a failure injects a
bounded evidence report and continues the run, and a run that exhausts its budget without
passing ends as `unverified` instead of a silent false success. `verified_tool` lets a tool
call carry an `expect` prediction; a wrong prediction is surfaced on the result of the call
that broke it.

How this relates to what already exists:

- `Agent(retries=...)` and workflow `Step(max_retries=...)` re-run on an exception; they
  count mechanical failures and never look at the outcome.
- `RetryAgentRun` / `StopAgentRun` re-enter or stop the model loop from inside a tool call;
  only a tool can raise them, and the model decides when to call the tool.
- Output guardrails reject an output by raising `OutputCheckError`, which ends the run.
- The team task list's `mark_all_complete` is a completion flag the model asserts; nothing
  checks it.
- `agno.eval` and `agno.environments` grade runs after they are over and cannot re-enter
  them. `agno.scorer` is shared: one scorer works offline there and in-loop here.
- `Agent.tool_hooks` wrap every tool call but cannot add the `expect` parameter to the
  schema the model sees, which is why `verified_tool` is a decorator. Hooks also wrap the
  decorated function itself, so a hook that rewrites arguments or results can bypass the
  comparison; keep transforming hooks off a verified tool.
- `Agent.continue_run(input=...)` resumes a completed run with a follow-up, forking a
  sibling run that carries the transcript. It is what `run_verified` is built on.

`VerifiedRun.output.status` is `RunStatus.completed` even when the verification failed;
read `VerifiedRun.status`.
"""

from agno.verify.fingerprints import CallableFingerprint, GitWorktreeFingerprint, StateFingerprint
from agno.verify.runner import arun_verified, run_verified
from agno.verify.tools import DIVERGENCE_DIRECTIVE, divergence_report, verified_tool
from agno.verify.types import (
    REPORT_CAP_BYTES,
    VERIFICATION_NOTICE,
    StopReason,
    Verdict,
    Verification,
    VerificationAttempt,
    VerifiedRun,
    VerifierLimits,
)
from agno.verify.verifiers import ScorerVerifier, ShellVerifier, Verifier, verifier

__all__ = [
    "DIVERGENCE_DIRECTIVE",
    "REPORT_CAP_BYTES",
    "VERIFICATION_NOTICE",
    "CallableFingerprint",
    "GitWorktreeFingerprint",
    "ScorerVerifier",
    "ShellVerifier",
    "StateFingerprint",
    "StopReason",
    "Verdict",
    "VerificationAttempt",
    "Verification",
    "VerifiedRun",
    "Verifier",
    "VerifierLimits",
    "arun_verified",
    "divergence_report",
    "run_verified",
    "verified_tool",
    "verifier",
]
