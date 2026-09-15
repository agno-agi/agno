"""Verifiers: executable definitions of done for agents, teams and workflows.

An agent's "done" is a model utterance; a verifier checks it. When the model stops, the
verifiers run; a failure goes back to the model as an evidence report inside the same run,
and a run that never passes within budget ends ``RunStatus.unverified`` with the record on
``RunOutput.verification``. The same checks mount on ``Agent(verifiers=...)``,
``Team(verifiers=...)`` and the ``Verify`` workflow step; per-check policy rides the check
(``required``, ``max_retries``, ``run_condition``, ``stop_on_failure``) and only the shared re-entry loop rides
the mount. Learning, memory and post-hooks are not gated: they run on the final output.
"""

from agno.verifiers.base import GuardedVerifier, Verifier, verifier
from agno.verifiers.fingerprints import (
    DEFAULT_EXCLUDES,
    CallableFingerprint,
    GitWorktreeFingerprint,
    StateFingerprint,
)
from agno.verifiers.scorer import ScorerVerifier
from agno.verifiers.shell import ShellVerifier
from agno.verifiers.tools import DIVERGENCE_DIRECTIVE, divergence_report, verified_tool
from agno.verifiers.types import (
    MAX_REPORT_BYTES,
    Verdict,
    Verification,
    VerificationAttempt,
    VerificationConfig,
    VerificationStatus,
    VerificationStopReason,
)

__all__ = [
    "DEFAULT_EXCLUDES",
    "DIVERGENCE_DIRECTIVE",
    "MAX_REPORT_BYTES",
    "CallableFingerprint",
    "GitWorktreeFingerprint",
    "GuardedVerifier",
    "ScorerVerifier",
    "ShellVerifier",
    "StateFingerprint",
    "Verdict",
    "Verification",
    "VerificationAttempt",
    "VerificationConfig",
    "VerificationStatus",
    "VerificationStopReason",
    "Verifier",
    "divergence_report",
    "verified_tool",
    "verifier",
]
