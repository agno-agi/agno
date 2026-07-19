"""run_rollouts / arun_rollouts and the result types."""

import asyncio
import copy
import json
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

from agno.db.in_memory import InMemoryDb
from agno.environments._engine import AttemptResult, StopReason, arun_batch
from agno.environments._render import LiveGrid, attempt_glyph, build_grid
from agno.environments.env import (
    Env,
    EnvTask,
    _env_fingerprint_or_none,
    _fingerprints_match,
    env_fingerprint_of,
    policy_fingerprint_of,
    resolved_task_id,
)
from agno.models.base import Model
from agno.run.agent import RunOutput
from agno.scorer import EnvFingerprintError, EnvMismatchError, Score
from agno.utils.log import log_warning

_FORMAT_VERSION = 1

# The learning-zone tolerance: isclose rather than == because float judges otherwise
# manufacture variance; no statistical variance is computed and no epsilon invented.
_REL_TOL = 1e-9
_ABS_TOL = 1e-9


@dataclass
class TaskResult:
    """One task's K attempts, in attempt order."""

    task: EnvTask
    attempts: Tuple[AttemptResult, ...]

    @property
    def n_scored(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.score is not None)

    @property
    def n_unscored(self) -> int:
        return len(self.attempts) - self.n_scored

    @property
    def _scored_values(self) -> List[float]:
        return [attempt.score.value for attempt in self.attempts if attempt.score is not None]

    @property
    def n_passed(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.score is not None and attempt.score.passed)

    @property
    def pass_rate(self) -> Optional[float]:
        # Unscored attempts are excluded from statistics, never coerced to zero: a
        # timeout is not a wrong answer.
        if self.n_scored == 0:
            return None
        return self.n_passed / self.n_scored

    @property
    def mean_value(self) -> Optional[float]:
        values = self._scored_values
        return mean(values) if values else None

    @property
    def in_learning_zone(self) -> bool:
        """At least two scored attempts, and the extremes disagree."""
        values = self._scored_values
        if len(values) < 2:
            return False
        return not math.isclose(min(values), max(values), rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


@dataclass
class EnvRunResult:
    """The result of one rollout run: fingerprints, task results, and the grid."""

    env_name: str
    k: int
    env_fingerprint: Optional[str]
    policy_fingerprint: Optional[str]
    task_results: Tuple[TaskResult, ...]
    duration_seconds: float
    stopped_early: Optional[str] = None  # "error-storm" | None

    @property
    def n_attempts(self) -> int:
        return sum(len(task_result.attempts) for task_result in self.task_results)

    @property
    def n_scored(self) -> int:
        return sum(task_result.n_scored for task_result in self.task_results)

    @property
    def n_unscored(self) -> int:
        return sum(task_result.n_unscored for task_result in self.task_results)

    @property
    def pass_rate(self) -> Optional[float]:
        if self.n_scored == 0:
            return None
        return sum(task_result.n_passed for task_result in self.task_results) / self.n_scored

    @property
    def mean_value(self) -> Optional[float]:
        values = [value for task_result in self.task_results for value in task_result._scored_values]
        return mean(values) if values else None

    def summary(self) -> Dict[str, Any]:
        """The CI contract; these keys are frozen."""
        return {
            "env": self.env_name,
            "k": self.k,
            "n_tasks": len(self.task_results),
            "n_attempts": self.n_attempts,
            "n_scored": self.n_scored,
            "n_unscored": self.n_unscored,
            "pass_rate": self.pass_rate,
            "mean_value": self.mean_value,
            "env_fingerprint": self.env_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "stopped_early": self.stopped_early,
            "tasks": [
                {
                    "id": task_result.task.id,
                    "pass_rate": task_result.pass_rate,
                    "mean_value": task_result.mean_value,
                    "n_unscored": task_result.n_unscored,
                    "learning_zone": task_result.in_learning_zone,
                }
                for task_result in self.task_results
            ],
        }

    def learning_zone(self) -> "EnvRunResult":
        """A filtered copy holding only the tasks whose attempts disagreed -- same
        fingerprints, so the grid, summary() and the exporter all work on it."""
        return replace(
            self,
            task_results=tuple(task_result for task_result in self.task_results if task_result.in_learning_zone),
        )

    def errors(self) -> Dict[str, List[str]]:
        """Task id -> error strings, attempt order. Tasks without errors are absent."""
        grouped: Dict[str, List[str]] = {}
        for task_result in self.task_results:
            messages = [attempt.error for attempt in task_result.attempts if attempt.error]
            if messages:
                grouped[str(task_result.task.id)] = messages
        return grouped

    def env_matches(self, other: Any) -> bool:
        return _fingerprints_match(self.env_fingerprint, _env_fingerprint_or_none(other))

    def diff(self, baseline: "EnvRunResult") -> "EnvDiff":
        """Per-task deltas against a baseline run of the same environment."""
        if not self.env_matches(baseline):
            raise EnvMismatchError(
                "env_fingerprint diverged: current="
                f"{self.env_fingerprint!r}, baseline={baseline.env_fingerprint!r} -- "
                "these results are not from the same environment (None never matches)"
            )
        baseline_by_id = {str(task_result.task.id): task_result for task_result in baseline.task_results}
        rows: List[Dict[str, Any]] = []
        improved: List[str] = []
        regressed: List[str] = []
        for task_result in self.task_results:
            task_id = str(task_result.task.id)
            baseline_task = baseline_by_id.get(task_id)
            if baseline_task is None:
                continue
            current_rate = task_result.pass_rate
            baseline_rate = baseline_task.pass_rate
            delta = None if current_rate is None or baseline_rate is None else current_rate - baseline_rate
            status = ""
            if delta is not None and not math.isclose(delta, 0.0, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
                status = "improved" if delta > 0 else "regressed"
                (improved if delta > 0 else regressed).append(task_id)
            rows.append(
                {
                    "id": task_id,
                    "baseline": f"{baseline_task.n_passed}/{baseline_task.n_scored}",
                    "current": f"{task_result.n_passed}/{task_result.n_scored}",
                    "baseline_pass_rate": baseline_rate,
                    "current_pass_rate": current_rate,
                    "delta": delta,
                    "status": status,
                }
            )
        return EnvDiff(
            env_name=self.env_name,
            policy_changed=not _fingerprints_match(self.policy_fingerprint, baseline.policy_fingerprint),
            rows=tuple(rows),
            improved=tuple(improved),
            regressed=tuple(regressed),
        )

    def save(self, path: Union[str, Path]) -> None:
        """Plain JSON round-trip: the opening pitch -- re-running after an edit tells
        you what moved -- needs the first result to still exist when the second run
        happens."""
        payload = {
            "format_version": _FORMAT_VERSION,
            "env_name": self.env_name,
            "k": self.k,
            "env_fingerprint": self.env_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "duration_seconds": self.duration_seconds,
            "stopped_early": self.stopped_early,
            "task_results": [
                {
                    "task": {
                        "id": task_result.task.id,
                        "input": task_result.task.input,
                        "expected": task_result.task.expected,
                        "metadata": dict(task_result.task.metadata),
                    },
                    "attempts": [
                        {
                            "run": attempt.run.to_dict() if attempt.run is not None else None,
                            "score": _score_to_dict(attempt.score),
                            "stop_reason": attempt.stop_reason.value,
                            "duration_seconds": attempt.duration_seconds,
                            "error": attempt.error,
                            "tool_call_limit_hit": attempt.tool_call_limit_hit,
                        }
                        for attempt in task_result.attempts
                    ],
                }
                for task_result in self.task_results
            ],
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "EnvRunResult":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = payload.get("format_version")
        if version != _FORMAT_VERSION:
            raise ValueError(f"unsupported format_version {version!r}; this build reads {_FORMAT_VERSION}")
        task_results = []
        for row in payload["task_results"]:
            task = EnvTask(
                input=row["task"]["input"],
                expected=row["task"]["expected"],
                id=row["task"]["id"],
                metadata=row["task"]["metadata"] or {},
            )
            attempts = tuple(
                AttemptResult(
                    run=RunOutput.from_dict(attempt["run"]) if attempt["run"] is not None else None,
                    score=_score_from_dict(attempt["score"]),
                    stop_reason=StopReason(attempt["stop_reason"]),
                    duration_seconds=attempt["duration_seconds"],
                    error=attempt["error"],
                    tool_call_limit_hit=attempt["tool_call_limit_hit"],
                )
                for attempt in row["attempts"]
            )
            task_results.append(TaskResult(task=task, attempts=attempts))
        return cls(
            env_name=payload["env_name"],
            k=payload["k"],
            env_fingerprint=payload["env_fingerprint"],
            policy_fingerprint=payload["policy_fingerprint"],
            task_results=tuple(task_results),
            duration_seconds=payload["duration_seconds"],
            stopped_early=payload["stopped_early"],
        )

    def __str__(self) -> str:
        rows = []
        first_error: Optional[str] = None
        total_cost: Optional[float] = None
        for task_result in self.task_results:
            for attempt in task_result.attempts:
                if first_error is None and attempt.error:
                    first_error = attempt.error
                cost = _attempt_cost(attempt)
                if cost is not None:
                    total_cost = (total_cost or 0.0) + cost
            rows.append(
                {
                    "id": task_result.task.id,
                    "glyphs": "".join(attempt_glyph(attempt.score) for attempt in task_result.attempts),
                    "n_passed": task_result.n_passed,
                    "n_scored": task_result.n_scored,
                    "pass_rate": task_result.pass_rate,
                    "learning_zone": task_result.in_learning_zone,
                    "n_unscored": task_result.n_unscored,
                }
            )
        return build_grid(
            self.env_name,
            self.k,
            rows,
            n_attempts=self.n_attempts,
            duration_seconds=self.duration_seconds,
            total_cost=total_cost,
            first_error=first_error if self.n_unscored > 0 else None,
            stopped_early=self.stopped_early,
        )


@dataclass
class EnvDiff:
    """Per-task deltas between two runs of the same environment."""

    env_name: str
    policy_changed: bool
    rows: Tuple[Dict[str, Any], ...]
    improved: Tuple[str, ...]
    regressed: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "env_name": self.env_name,
            "policy_changed": self.policy_changed,
            "rows": list(self.rows),
            "improved": list(self.improved),
            "regressed": list(self.regressed),
        }

    def __str__(self) -> str:
        note = "(env identical, policy changed)" if self.policy_changed else "(env identical, policy identical)"
        lines = [f"{self.env_name}       baseline -> current      {note}"]
        id_width = max([len(row["id"]) for row in self.rows], default=2)
        for row in self.rows:
            delta = f"{row['delta']:+.2f}" if row["delta"] is not None else "   -"
            line = f"  {row['id']:<{id_width}}   {row['baseline']} -> {row['current']}    {delta}"
            if row["status"]:
                line += f"   {row['status']}"
            lines.append(line)
        return "\n".join(lines)


def _score_to_dict(score: Optional[Score]) -> Optional[Dict[str, Any]]:
    if score is None:
        return None
    return {"value": score.value, "passed": score.passed, "reason": score.reason, "detail": score.detail}


def _score_from_dict(payload: Optional[Dict[str, Any]]) -> Optional[Score]:
    if payload is None:
        return None
    return Score(
        value=payload["value"], passed=payload["passed"], reason=payload.get("reason"), detail=payload.get("detail")
    )


def _attempt_cost(attempt: AttemptResult) -> Optional[float]:
    run = attempt.run
    if run is None or run.metrics is None:
        return None
    return getattr(run.metrics, "cost", None)


async def arun_rollouts(
    env: Env,
    *,
    k: int = 8,
    tasks: Optional[Sequence[EnvTask]] = None,
    model: Optional[Model] = None,
    concurrency: int = 4,
) -> EnvRunResult:
    """Run every task K times, hermetically, and score every attempt.

    Rollouts are hermetic and there is no knob: contaminated statistics answer "does
    my agent work" wrongly, and contaminated trajectories poison the training set.
    Every attempt runs on a fresh copy with a fresh in-memory db, fresh session and
    user ids, memory capture, knowledge writes and learning disabled, and the response
    cache off. Knowledge READS survive: retrieval goes through knowledge.vector_db,
    not agent.db, so a RAG agent retrieves normally inside a rollout.
    """
    if model is not None and not isinstance(model, Model):
        raise TypeError(
            f"model must be a Model instance, got {type(model).__name__}; string model resolution is "
            "deliberately not supported -- construct the model and pass it"
        )

    resolved_tasks = tuple(replace(task, id=resolved_task_id(task, index)) for index, task in enumerate(env.tasks))
    if tasks is None:
        selected = resolved_tasks
    else:
        index_by_identity = {id(task): index for index, task in enumerate(env.tasks)}
        selected_list: List[EnvTask] = []
        for task in tasks:
            env_index = index_by_identity.get(id(task))
            if env_index is None:
                raise ValueError(
                    "tasks must be selected from env.tasks (e.g. [t for t in env.tasks if ...]); "
                    "selection keeps env identity, a rebuilt task does not"
                )
            selected_list.append(resolved_tasks[env_index])
        selected = tuple(selected_list)

    start = time.perf_counter()

    # Fingerprints are computed from the first instance constructed at run start and
    # stamped on the result; a scorer or component that cannot fingerprint degrades
    # to None with a warning rather than failing the run.
    source_agent = env.agent() if callable(env.agent) else env.agent
    env_fingerprint: Optional[str] = None
    try:
        env_fingerprint = env_fingerprint_of(env, source_agent)
    except EnvFingerprintError as exc:
        log_warning(f"env_fingerprint degraded to None: {exc}")

    # The stamped policy fingerprint is computed from the EFFECTIVE model actually
    # used -- stamping the env's declared model under a model= override would
    # mislabel every checkpoint-swap comparison.
    effective_model = model if model is not None else source_agent.model
    policy_fingerprint: Optional[str] = None
    if effective_model is None:
        log_warning("policy_fingerprint degraded to None: the agent has no model")
    else:
        try:
            policy_fingerprint = policy_fingerprint_of(effective_model)
        except EnvFingerprintError as exc:
            log_warning(f"policy_fingerprint degraded to None: {exc}")

    def build_attempt_agent() -> Any:
        agent = env.agent() if callable(env.agent) else env.agent.deep_copy()
        # The model override is applied BEFORE the cache handling, and the cache rule
        # is unconditional on the effective model: copy.copy per attempt (shallow, so
        # the HTTP client underneath stays shared), cache_response=False on the copy,
        # never on the caller's instance. In the other order, an override model with
        # caching on would replay a shared disk cache across all K attempts.
        attempt_model = model if model is not None else agent.model
        if attempt_model is not None:
            model_copy = copy.copy(attempt_model)
            model_copy.cache_response = False
            agent.model = model_copy
        # Hermetic overrides. add_history_to_context is deliberately NOT modified: a
        # fresh session means empty history, which is the honest version of pinned.
        # agent.knowledge is deliberately NOT nulled: knowledge reads must survive.
        agent.db = InMemoryDb()
        agent.user_id = f"rollout-user-{uuid4().hex}"
        agent.update_memory_on_run = False
        agent.enable_user_memories = False
        agent.enable_agentic_memory = False
        agent.update_knowledge = False
        # deep_copy shares a LearningMachine by reference and it resolves against its
        # own db; left attached, a "hermetic" run would write learning updates to the
        # caller's real store.
        agent.learning = None
        return agent

    finished: List[AttemptResult] = []
    storm = {"stop": False}

    def check_error_storm(attempt: AttemptResult) -> None:
        # A uniform misconfiguration is not data about the agent: when the first
        # `concurrency` completions all errored with one exception type before any
        # success, stop scheduling and return the partial result.
        finished.append(attempt)
        if storm["stop"] or len(finished) != concurrency:
            return
        first = finished[:concurrency]
        if not all(candidate.stop_reason == StopReason.error for candidate in first):
            return
        kinds = {(candidate.error or "").split(":", 1)[0].strip() for candidate in first}
        if len(kinds) == 1:
            storm["stop"] = True

    from rich.console import Console

    console = Console()
    live_grid = LiveGrid(console, env.name, k, [str(task.id) for task in selected]) if console.is_terminal else None

    def on_attempt_end(input_index: int, attempt_index: int, attempt: AttemptResult) -> None:
        check_error_storm(attempt)
        if live_grid is not None:
            live_grid.on_attempt(input_index, attempt_index, attempt)

    inputs = [task.input for task in selected]
    expected = [task.expected for task in selected]

    if live_grid is not None:
        with live_grid:
            batches = await arun_batch(
                build_attempt_agent,
                inputs,
                k=k,
                concurrency=concurrency,
                scorer=env.scorer,
                expected=expected,
                timeout_seconds=env.timeout_seconds,
                on_attempt_end=on_attempt_end,
                should_stop=lambda: storm["stop"],
            )
    else:
        batches = await arun_batch(
            build_attempt_agent,
            inputs,
            k=k,
            concurrency=concurrency,
            scorer=env.scorer,
            expected=expected,
            timeout_seconds=env.timeout_seconds,
            on_attempt_end=on_attempt_end,
            should_stop=lambda: storm["stop"],
        )

    task_results = tuple(TaskResult(task=task, attempts=attempts) for task, attempts in zip(selected, batches))
    return EnvRunResult(
        env_name=env.name,
        k=k,
        env_fingerprint=env_fingerprint,
        policy_fingerprint=policy_fingerprint,
        task_results=task_results,
        duration_seconds=time.perf_counter() - start,
        stopped_early="error-storm" if storm["stop"] else None,
    )


def run_rollouts(
    env: Env,
    *,
    k: int = 8,
    tasks: Optional[Sequence[EnvTask]] = None,
    model: Optional[Model] = None,
    concurrency: int = 4,
) -> EnvRunResult:
    """Sync door over arun_rollouts (asyncio.run, so a timed-out attempt is actually
    cancelled rather than abandoned)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("run_rollouts cannot be called from a running event loop; await arun_rollouts instead")
    return asyncio.run(arun_rollouts(env, k=k, tasks=tasks, model=model, concurrency=concurrency))
