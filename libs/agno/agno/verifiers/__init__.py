"""Evidence-based verification for agents and teams.

Principle: evidence over prose. An agent's "done" is a model utterance; a verifier is the
executable definition of done. Configure verifiers on the agent —

    Agent(verifiers=[ShellVerifier("pytest -q"), report_exists])

— and every surface the agent runs on gets the same loop: when the model stops, the
verifiers run; a failure goes back to the model as an evidence report and the model
continues, inside the same run; a run that never passes within budget ends with
``RunStatus.unverified`` and the full record on ``RunOutput.verification``.

A verifier is a pure check, and it mounts in three places: ``Agent(verifiers=...)``,
``Team(verifiers=...)``, and the ``Verify`` workflow step (``agno.workflow.Verify``),
where a failure re-runs earlier steps with the evidence attached. Everything about the
check rides the check — its execution config and its policy (``required=False`` for an
advisory check, ``rerun`` for flaky ones, ``run_when`` to gate expensive checks on
earlier verdicts, ``fatal`` when retrying is pointless; the ``check()`` wrapper gives
bare callables the same surface). Only the shared re-entry loop rides the mount, in
that mount's own vocabulary (``VerificationConfig`` on agents and teams; ``on_fail``
and ``max_rounds`` on the workflow step).

How this relates to the neighbouring machinery:

- ``Agent(retries=...)`` re-runs on an EXCEPTION and never reads the outcome; verifiers
  judge the outcome of a turn that succeeded mechanically.
- Guardrails (``pre_hooks``/``post_hooks``) validate input or output once and END the run
  by raising; verifiers send the failure back into the run and let the model continue.
- ``agno.eval`` and ``agno.scorer`` grade after the run is over; ``ScorerVerifier`` reuses
  the same scorers as an in-loop gate.
- Learning and memory are not gated by verification: their background work starts before
  the model call and runs regardless of the outcome, so an unverified run still writes
  memories and learnings.
"""

from agno.verifiers.base import GuardedVerifier, Verifier, check, verifier
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
    REPORT_CAP_BYTES,
    StopReason,
    Verdict,
    Verification,
    VerificationAttempt,
    VerificationConfig,
)

__all__ = [
    "DEFAULT_EXCLUDES",
    "DIVERGENCE_DIRECTIVE",
    "REPORT_CAP_BYTES",
    "CallableFingerprint",
    "GitWorktreeFingerprint",
    "GuardedVerifier",
    "ScorerVerifier",
    "ShellVerifier",
    "StateFingerprint",
    "StopReason",
    "Verdict",
    "Verification",
    "VerificationAttempt",
    "VerificationConfig",
    "Verifier",
    "check",
    "divergence_report",
    "verified_tool",
    "verifier",
]
