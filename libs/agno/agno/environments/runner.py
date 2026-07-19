"""run_rollouts / arun_rollouts and the result types."""

import asyncio
import copy
import json
import math
import time
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
from uuid import uuid4

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.environments._engine import AttemptResult, StopReason, arun_batch
from agno.environments._render import LiveGrid, attempt_glyph, build_grid
from agno.environments.env import (
    Env,
    EnvTask,
    _env_fingerprint_of,
    _env_fingerprint_or_none,
    _fingerprints_match,
    _policy_fingerprint_of,
    _resolved_task_id,
    _validated_agent,
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
        current_ids = {str(task_result.task.id) for task_result in self.task_results}
        rows: List[Dict[str, Any]] = []
        improved: List[str] = []
        regressed: List[str] = []
        # Same fingerprint, different task subset (learning_zone(), tasks=) is legal,
        # so unmatched tasks are possible and must be visible, not silently dropped.
        unmatched_current: List[str] = []
        unmatched_baseline = [task_id for task_id in baseline_by_id if task_id not in current_ids]
        for task_result in self.task_results:
            task_id = str(task_result.task.id)
            baseline_task = baseline_by_id.get(task_id)
            if baseline_task is None:
                unmatched_current.append(task_id)
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
            unmatched_current=tuple(unmatched_current),
            unmatched_baseline=tuple(unmatched_baseline),
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
                            "error_type": attempt.error_type,
                        }
                        for attempt in task_result.attempts
                    ],
                }
                for task_result in self.task_results
            ],
        }
        # Serialize BEFORE opening: open("w") truncates, so a dumps failure after it
        # would destroy an existing baseline -- the exact file diff() needs.
        try:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"EnvRunResult.save: {_name_unserializable(payload)}: {exc}") from exc
        with open(Path(path), "w", encoding="utf-8", newline="") as handle:
            handle.write(text + "\n")

    async def asave(self, path: Union[str, Path]) -> None:
        """Async twin of save."""
        await asyncio.to_thread(self.save, path)

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
                    error_type=attempt.get("error_type"),
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

    @classmethod
    async def aload(cls, path: Union[str, Path]) -> "EnvRunResult":
        """Async twin of load."""
        return await asyncio.to_thread(cls.load, path)

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
    # Tasks on only one side (a subset run diffed against a fuller baseline, or the
    # reverse): not comparable, but never silently dropped.
    unmatched_current: Tuple[str, ...] = ()
    unmatched_baseline: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "env_name": self.env_name,
            "policy_changed": self.policy_changed,
            "rows": list(self.rows),
            "improved": list(self.improved),
            "regressed": list(self.regressed),
            "unmatched_current": list(self.unmatched_current),
            "unmatched_baseline": list(self.unmatched_baseline),
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
        if self.unmatched_current or self.unmatched_baseline:
            parts = []
            if self.unmatched_current:
                parts.append(f"current-only: {', '.join(self.unmatched_current)}")
            if self.unmatched_baseline:
                parts.append(f"baseline-only: {', '.join(self.unmatched_baseline)}")
            lines.append(f"  not compared -- {'; '.join(parts)}")
        return "\n".join(lines)


def _name_unserializable(payload: Dict[str, Any]) -> str:
    """Name the task and field that broke serialization: expected and metadata are the
    only raw user-controlled values in the save payload."""
    for row in payload.get("task_results", []):
        for field_name in ("expected", "metadata"):
            try:
                json.dumps(row["task"][field_name])
            except (TypeError, ValueError):
                return f"task {row['task']['id']!r} field {field_name!r} is not JSON-serializable"
    return "a component is not JSON-serializable"


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


# The hermetic action for every field Agent.deep_copy shares by reference
# (agno.agent._utils.SHARED_BY_REFERENCE_FIELDS), plus handled fields deep_copy
# copies but whose copies still leak (a shallow-copied followup model, a config of
# cache-bearing fallback models, a save path string, a sub-agent that re-shares its
# own db). The drift test pins SHARED_BY_REFERENCE_FIELDS as a subset of this
# mapping, so a field newly shared upstream fails CI until an action is chosen here.
_HERMETIC_FIELD_ACTIONS: Dict[str, str] = {
    "db": "fresh-inmemory-db",
    "model": "cache-off-copy",
    "reasoning_model": "cache-off-copy",
    "parser_model": "cache-off-copy",
    "output_model": "cache-off-copy",
    "followup_model": "cache-off-copy",
    "knowledge": "shared",  # reads survive: retrieval goes through knowledge.vector_db
    "skills": "shared",  # loader-backed skill definitions: read-only, no db binding
    "learning": "nulled",
    "memory_manager": "nulled",  # a fresh user_id reads empty memories by design
    "session_summary_manager": "nulled",
    "culture_manager": "read-only-rebind",  # culture is global knowledge: reads survive
    "compression_manager": "isolated-copy",
    "fallback_config": "cache-off-copies",
    "reasoning_agent": "recursive-hermetic",
    "save_response_to_file": "nulled",
}


def _cache_off_copy(model_like: Any) -> Any:
    # Shallow, so the HTTP client underneath stays shared; the flag lands on the
    # copy, never on the caller's instance.
    model_copy = copy.copy(model_like)
    model_copy.cache_response = False
    return model_copy


def _field_names_of(agent: Any) -> List[str]:
    if is_dataclass(agent):
        return [f.name for f in fields(agent)]
    return list(vars(agent))


def _mcp_tool_names(agent: Any) -> List[str]:
    tools = getattr(agent, "tools", None)
    if not isinstance(tools, (list, tuple)):
        return []
    names = []
    for tool in tools:
        mro = getattr(type(tool), "__mro__", ())
        if any(c.__name__ in ("MCPTools", "MultiMCPTools") for c in mro):
            names.append(type(tool).__name__)
    return names


def _apply_hermetic_overrides(
    agent: Any, model_override: Optional[Model] = None, _seen: Optional[Set[int]] = None
) -> None:
    """The hermetic override block, applied per attempt to a factory product or a
    deep copy -- and recursively to a user-supplied reasoning agent, whose own
    deep_copy re-shares its db and model.

    What survives, deliberately: knowledge (reads go through knowledge.vector_db,
    not agent.db), skills (read-only definitions), culture READS (culture is global
    knowledge, not per-user state -- the manager is rebound to a copy holding the
    caller's culture db while both write flags are off), and compression (it changes
    what the model sees, so it stays on; the manager is isolated so attempt stats
    and model bindings never land on the caller's). add_history_to_context is NOT
    modified: a fresh session means empty history, the honest version of pinned.

    Everything else that touches the caller's world is cut: db swapped for a fresh
    InMemoryDb, fresh user id, memory capture / knowledge writes / learning /
    cultural-knowledge writes off, session summaries off (an extra LLM call per
    attempt, and attempt init would write the attempt's model onto a shared
    manager), save_response_to_file nulled (K attempts would race-write the
    caller's file), and every model slot -- primary, *_model fields, fallback
    lists -- runs on a copy with the response cache off, because the cache is a
    shared disk cache keyed by messages and a cached attempt is a replay, not a
    sample.
    """
    seen = _seen if _seen is not None else set()
    if id(agent) in seen:
        return
    seen.add(id(agent))
    source_db = getattr(agent, "db", None)
    # Whether the production configuration would put culture in context: read
    # BEFORE the capture flags are forced off, because they feed the resolution.
    wants_culture = bool(
        getattr(agent, "add_culture_to_context", None)
        or getattr(agent, "update_cultural_knowledge", False)
        or getattr(agent, "enable_agentic_culture", False)
        or getattr(agent, "culture_manager", None) is not None
    )

    attempt_model = model_override if model_override is not None else getattr(agent, "model", None)
    if attempt_model is not None:
        agent.model = _cache_off_copy(attempt_model)
    for field_name in _field_names_of(agent):
        if field_name == "model" or field_name.startswith("_"):
            continue
        value = getattr(agent, field_name, None)
        if value is None:
            continue
        # Model-typed values by isinstance; *_model fields by name so duck-typed
        # subjects (and their stub models) get the same treatment.
        if isinstance(value, Model) or (field_name.endswith("_model") and hasattr(value, "cache_response")):
            setattr(agent, field_name, _cache_off_copy(value))
    fallback_config = getattr(agent, "fallback_config", None)
    if fallback_config is not None:
        config_copy = copy.copy(fallback_config)
        for list_name in ("on_error", "on_rate_limit", "on_context_overflow"):
            entries = getattr(config_copy, list_name, None)
            if entries:
                setattr(
                    config_copy,
                    list_name,
                    [_cache_off_copy(entry) if hasattr(entry, "cache_response") else entry for entry in entries],
                )
        agent.fallback_config = config_copy

    agent.db = InMemoryDb()
    agent.user_id = f"rollout-user-{uuid4().hex}"
    agent.update_memory_on_run = False
    agent.enable_user_memories = False
    agent.enable_agentic_memory = False
    agent.update_knowledge = False
    agent.learning = None
    agent.update_cultural_knowledge = False
    agent.enable_agentic_culture = False
    agent.memory_manager = None
    agent.session_summary_manager = None
    agent.enable_session_summaries = False
    agent.save_response_to_file = None

    culture_manager = getattr(agent, "culture_manager", None)
    if culture_manager is not None:
        manager_copy = copy.copy(culture_manager)
        if getattr(manager_copy, "db", None) is None and source_db is not None:
            manager_copy.db = source_db
        manager_model = getattr(manager_copy, "model", None)
        if manager_model is not None and hasattr(manager_model, "cache_response"):
            manager_copy.model = _cache_off_copy(manager_model)
        agent.culture_manager = manager_copy
    elif wants_culture and source_db is not None:
        # Production reads came straight off agent.db; the attempt's db is fresh, so
        # an explicit manager bound to the caller's db keeps the reads identical.
        from agno.culture.manager import CultureManager

        agent.culture_manager = CultureManager(db=source_db)

    compression_manager = getattr(agent, "compression_manager", None)
    if compression_manager is not None:
        manager_copy = copy.copy(compression_manager)
        if hasattr(manager_copy, "stats"):
            manager_copy.stats = {}
        manager_model = getattr(manager_copy, "model", None)
        if manager_model is not None and hasattr(manager_model, "cache_response"):
            manager_copy.model = _cache_off_copy(manager_model)
        agent.compression_manager = manager_copy

    # A manager this block has never seen is nulled loudly: managers bind db and
    # model by pattern, and silently sharing one is the exact leak this function
    # exists to stop.
    for field_name in _field_names_of(agent):
        if (
            field_name.endswith("_manager")
            and field_name not in _HERMETIC_FIELD_ACTIONS
            and getattr(agent, field_name, None) is not None
        ):
            log_warning(f"hermetic overrides do not know agent.{field_name}; nulling it for isolation")
            setattr(agent, field_name, None)

    reasoning_agent = getattr(agent, "reasoning_agent", None)
    if reasoning_agent is not None:
        _apply_hermetic_overrides(reasoning_agent, _seen=seen)


def _default_model_for(agent: Any) -> Optional[Model]:
    """The default model the run path installs on a model-less Agent, resolved on a
    shallow copy so the caller's agent is never mutated. None when resolution is
    unavailable (openai not installed); the fingerprint then degrades loudly."""
    if not isinstance(agent, Agent):
        return None
    try:
        from agno.agent._init import set_default_model

        probe = copy.copy(agent)
        set_default_model(probe)
        return probe.model
    except Exception:
        return None


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
    not agent.db, so a RAG agent retrieves normally inside a rollout -- and culture
    reads survive the same way, through a read-only manager rebind. The full field
    inventory lives on _apply_hermetic_overrides.

    Two residuals the overrides cannot reach, stated honestly:

    - env.timeout_seconds bounds when an attempt RETURNS, not when a sync scorer's
      body stops: a sync scorer runs in a thread (asyncio.to_thread), cancellation
      cannot interrupt it, and the abandoned thread runs to its natural end after
      the attempt has already come back as a timeout.
    - Tracing is process-global state, not an agent attribute: with setup_tracing
      configured, attempts export trace and span rows into the caller's trace store
      like any other run. They are identifiable there by their rollout-* session
      and user ids. (Suppressing them via OTel context is not viable today: the
      installed openinference-instrumentation-agno's suppressed fast-path breaks
      streamed runs.)

    A LIVE agent holding MCPTools is rejected at run start: deep_copy shares the
    MCP session by reference, concurrent attempts connect and close that one shared
    session mid-run, and the whole batch dies losing every attempt. Use a factory
    env -- ``agent=lambda: Agent(..., tools=[MCPTools(...)])`` -- so each attempt
    owns its connection.
    """
    if model is not None and not isinstance(model, Model):
        raise TypeError(
            f"model must be a Model instance, got {type(model).__name__}; string model resolution is "
            "deliberately not supported -- construct the model and pass it"
        )

    resolved_tasks = tuple(replace(task, id=_resolved_task_id(task, index)) for index, task in enumerate(env.tasks))
    # Declared duplicates are rejected at Env construction; the positional case (an
    # explicit "t2" colliding with the second task's auto-id) only exists after
    # resolution, so it is caught here -- diff() keyed on a duplicated id silently
    # pairs rows with the wrong baseline task.
    seen_ids: Set[str] = set()
    for task in resolved_tasks:
        task_id = str(task.id)
        if task_id in seen_ids:
            raise ValueError(f"duplicate resolved task id {task_id!r}; task ids must be unique (t1..tN are reserved)")
        seen_ids.add(task_id)
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
    if callable(env.agent):
        try:
            constructed = env.agent()
        except Exception as exc:
            raise RuntimeError(
                f"env.agent factory raised during run-start construction, before any attempt ran: {exc}"
            ) from exc
        source_agent = _validated_agent(constructed)
    else:
        source_agent = env.agent
        # Live path only: a factory constructs fresh MCP tools per attempt, which is
        # exactly the workaround this error names. Raised before any connection or
        # attempt exists.
        mcp_names = _mcp_tool_names(source_agent)
        if mcp_names:
            raise RuntimeError(
                f"env.agent holds {mcp_names[0]} by reference: every attempt would share one MCP "
                "session, and concurrent attempts connect and close that shared session mid-run, "
                "losing the whole batch. Use a factory env -- agent=lambda: Agent(..., "
                "tools=[MCPTools(...)]) -- so each attempt owns its connection."
            )

    # The stamped policy fingerprint is computed from the EFFECTIVE model actually
    # used -- stamping the env's declared model under a model= override would
    # mislabel every checkpoint-swap comparison. A model-less Agent runs on the
    # default the run path installs, so that default is what gets fingerprinted.
    # Resolved before the env fingerprint, whose model_prompt component reads the
    # same effective model.
    effective_model = model if model is not None else getattr(source_agent, "model", None)
    if effective_model is None:
        effective_model = _default_model_for(source_agent)

    env_fingerprint: Optional[str] = None
    try:
        env_fingerprint = _env_fingerprint_of(env, source_agent, model=effective_model)
    except EnvFingerprintError as exc:
        log_warning(f"env_fingerprint degraded to None: {exc}")

    policy_fingerprint: Optional[str] = None
    if effective_model is None:
        log_warning("policy_fingerprint degraded to None: the agent has no model")
    else:
        try:
            policy_fingerprint = _policy_fingerprint_of(effective_model)
        except EnvFingerprintError as exc:
            log_warning(f"policy_fingerprint degraded to None: {exc}")

    def build_attempt_agent() -> Any:
        agent = _validated_agent(env.agent()) if callable(env.agent) else env.agent.deep_copy()
        _apply_hermetic_overrides(agent, model_override=model)
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
        # The structured error_type when the engine knows the exception class; the
        # first-colon prefix only as a fallback for typeless error events, whose
        # content need not be prefix-stable.
        kinds = {candidate.error_type or (candidate.error or "").split(":", 1)[0].strip() for candidate in first}
        if len(kinds) == 1:
            storm["stop"] = True

    from rich.console import Console

    console = Console()
    live_grid = LiveGrid(console, env.name, k, [str(task.id) for task in selected]) if console.is_terminal else None

    grid_disabled = {"disabled": False}

    def on_attempt_end(input_index: int, attempt_index: int, attempt: AttemptResult) -> None:
        # The storm check must survive a rendering bug: an exception escaping this
        # callback would make the engine disable it entirely, and with it the
        # spec-mandated error-storm stop -- so the grid gets its own failure domain.
        check_error_storm(attempt)
        if live_grid is not None and not grid_disabled["disabled"]:
            try:
                live_grid.on_attempt(input_index, attempt_index, attempt)
            except Exception as exc:
                grid_disabled["disabled"] = True
                log_warning(f"live grid rendering failed and is disabled for the rest of the run: {exc}")

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
    """Sync door over arun_rollouts (asyncio.run).

    Timeout semantics match the async door -- the attempt coroutine is cancelled at
    env.timeout_seconds -- with one addition: a sync scorer body already running in
    its thread cannot be interrupted, and asyncio.run joins that thread at loop
    shutdown, so this door can block past the timeout until the scorer's body
    finishes on its own.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("run_rollouts cannot be called from a running event loop; await arun_rollouts instead")
    return asyncio.run(arun_rollouts(env, k=k, tasks=tasks, model=model, concurrency=concurrency))
