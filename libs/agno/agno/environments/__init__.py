"""agno.environments: run an agent many times against a set of tasks, score every
attempt, and do something useful with the result.

Two questions, in this order: does my agent actually work (run each task K times and
count -- a real pass rate, not one sampled run), and can I train on the runs that
worked (the passing attempts are, with no further labelling, an SFT dataset).

The fingerprint errors are re-exported from agno.scorer so callers can catch them
without importing scorer.
"""

from agno.environments._engine import AttemptResult, StopReason
from agno.environments.environment import Environment, Task
from agno.environments.exporters import ExportReport, ato_sft_jsonl, to_sft_jsonl
from agno.environments.runner import EnvironmentDiff, EnvironmentRunResult, TaskResult, arun_rollouts, run_rollouts
from agno.scorer import FingerprintError, MismatchError

__all__ = [
    "AttemptResult",
    "Environment",
    "EnvironmentDiff",
    "FingerprintError",
    "MismatchError",
    "EnvironmentRunResult",
    "Task",
    "ExportReport",
    "StopReason",
    "TaskResult",
    "arun_rollouts",
    "ato_sft_jsonl",
    "run_rollouts",
    "to_sft_jsonl",
]
