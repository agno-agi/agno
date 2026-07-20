"""run_rollouts / arun_rollouts and the result types."""

import asyncio
import copy
import inspect
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
from agno.environments._render import LiveGrid, attempt_glyph, build_grid, build_report
from agno.environments.environment import (
    Environment,
    Task,
    _env_fingerprint_of,
    _env_fingerprint_or_none,
    _fingerprints_match,
    _policy_fingerprint_of,
    _resolved_task_id,
    _validated_agent,
)
from agno.models.base import Model
from agno.run.agent import RunOutput
from agno.scorer import FingerprintError, MismatchError, Score
from agno.utils.log import log_warning

_FORMAT_VERSION = 1

# Pass-rate delta tolerance: diff deltas that differ only by float rounding noise
# count as unchanged.
_REL_TOL = 1e-9
_ABS_TOL = 1e-9


@dataclass
class TaskResult:
    """One task's K attempts, in attempt order."""

    task: Task
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
        """Some scored attempts passed and some failed -- the task is neither
        saturated nor hopeless, so every failure has a passing attempt to
        contrast against. Unscored attempts are excluded, as everywhere."""
        return 0 < self.n_passed < self.n_scored


@dataclass
class EnvironmentRunResult:
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

    def learning_zone(self) -> "EnvironmentRunResult":
        """A filtered copy holding only the tasks with both passed and failed
        scored attempts -- same fingerprints, so the grid, summary() and the
        exporter all work on it. Every task kept contains at least one failed
        scored attempt, the guarantee to_sft_jsonl's only_passed default
        builds on."""
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

    def diff(self, baseline: "EnvironmentRunResult") -> "EnvironmentDiff":
        """Per-task deltas against a baseline run of the same environment."""
        if not self.env_matches(baseline):
            raise MismatchError(
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
        return EnvironmentDiff(
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
            raise TypeError(f"EnvironmentRunResult.save: {_name_unserializable(payload)}: {exc}") from exc
        with open(Path(path), "w", encoding="utf-8", newline="") as handle:
            handle.write(text + "\n")

    async def asave(self, path: Union[str, Path]) -> None:
        """Async twin of save."""
        await asyncio.to_thread(self.save, path)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "EnvironmentRunResult":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = payload.get("format_version")
        if version != _FORMAT_VERSION:
            raise ValueError(f"unsupported format_version {version!r}; this build reads {_FORMAT_VERSION}")
        task_results = []
        for row in payload["task_results"]:
            task = Task(
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
    async def aload(cls, path: Union[str, Path]) -> "EnvironmentRunResult":
        """Async twin of load."""
        return await asyncio.to_thread(cls.load, path)

    def print_report(
        self,
        *,
        only: str = "failed",
        attempts: Optional[int] = None,
        console: Optional[Any] = None,
    ) -> None:
        """Print the per-attempt evidence underneath the grid: verdict, score reason,
        tool executions, the answer, and the token bill for each attempt.

        `only="failed"` (default) shows the attempts a person investigates -- scored
        fails plus everything unscored (errors, timeouts, pauses); `only="all"` shows
        every attempt. `attempts` caps rows per task. Presentation only: the format is
        not a contract and may change; parse `summary()` or `save()` output instead.
        """
        text = build_report(self.task_results, only=only, attempts=attempts)
        if console is not None:
            console.print(text)
        else:
            print(text)

    def print_attempt(self, task_id: str, attempt: int = 1, *, markdown: bool = False) -> None:
        """Print one attempt in full: the score's complete reasoning, then the whole
        run transcript via `pprint_run_response`. `attempt` is 1-based, matching the
        grid's glyph order. Presentation only, like `print_report`."""
        task_result = next((tr for tr in self.task_results if str(tr.task.id) == task_id), None)
        if task_result is None:
            known = ", ".join(str(tr.task.id) for tr in self.task_results)
            raise KeyError(f"no task with id {task_id!r}; known ids: {known}")
        if not 1 <= attempt <= len(task_result.attempts):
            raise IndexError(f"attempt must be in 1..{len(task_result.attempts)} for task {task_id!r}, got {attempt}")
        selected = task_result.attempts[attempt - 1]
        print(f"task {task_id}, attempt {attempt} of {len(task_result.attempts)}")
        print(f"  input: {task_result.task.input}")
        if task_result.task.expected is not None:
            print(f"  expected: {task_result.task.expected}")
        score = selected.score
        verdict = "unscored" if score is None else ("PASS" if score.passed else "FAIL")
        print(
            f"  {verdict}   stop={selected.stop_reason.value}   "
            f"{selected.duration_seconds:.1f}s   limit_hit={selected.tool_call_limit_hit}"
        )
        if selected.error:
            print(f"  error: {selected.error}")
        if score is not None:
            print(f"  score: value={score.value} passed={score.passed}")
            if score.reason:
                print(f"  reason: {score.reason}")
            if score.detail:
                print(f"  detail: {score.detail}")
        if selected.run is None:
            print("  (no run captured)")
            return
        from agno.utils.pprint import pprint_run_response

        pprint_run_response(selected.run, markdown=markdown)

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
class EnvironmentDiff:
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


# The isolation action for every field Agent.deep_copy shares by reference
# (agno.agent._utils.SHARED_BY_REFERENCE_FIELDS), plus handled fields deep_copy
# copies but whose copies still leak (a shallow-copied followup model, a config of
# cache-bearing fallback models, a save path string, a sub-agent that re-shares its
# own db). The drift test pins SHARED_BY_REFERENCE_FIELDS as a subset of this
# mapping, so a field newly shared upstream fails CI until an action is chosen here.
_ISOLATE_FIELD_ACTIONS: Dict[str, str] = {
    "db": "fresh-inmemory-db",
    "model": "cache-off-copy",
    "reasoning_model": "cache-off-copy",
    "parser_model": "cache-off-copy",
    "output_model": "cache-off-copy",
    "followup_model": "cache-off-copy",
    "knowledge": "shared",  # reads survive: retrieval goes through knowledge.vector_db
    "skills": "shared",  # loader-backed skill definitions: read-only, no db binding
    "learning": "writes-severed-copy",  # global reads keep the caller's db; every write engine cut
    "memory_manager": "fresh-db-rebind",  # per-user state: reads come from the attempt's empty db
    "session_summary_manager": "isolated-copy",  # resolution binds the attempt model on the copy
    "culture_manager": "read-only-rebind",  # culture is global knowledge: reads survive
    "compression_manager": "isolated-copy",
    "fallback_config": "cache-off-copies",
    "reasoning_agent": "recursive-isolate",
    "save_response_to_file": "nulled",
}


def _cache_off_copy(model_like: Any) -> Any:
    # Shallow, so the HTTP client underneath stays shared; the flag lands on the
    # copy, never on the caller's instance.
    model_copy = copy.copy(model_like)
    model_copy.cache_response = False
    return model_copy


def _isolated_manager_copy(manager: Any, db: Any = None, reset_stats: bool = False) -> Any:
    """An attempt-local shallow copy of a manager: resolution binds db and model
    onto the copy, never onto the caller's instance. `db` rebinds the copy's
    store; a model already set on the manager gets the cache-off treatment."""
    manager_copy = copy.copy(manager)
    if db is not None:
        manager_copy.db = db
    if reset_stats and hasattr(manager_copy, "stats"):
        manager_copy.stats = {}
    manager_model = getattr(manager_copy, "model", None)
    if manager_model is not None and hasattr(manager_model, "cache_response"):
        manager_copy.model = _cache_off_copy(manager_model)
    return manager_copy


def _writes_off_learning_config(config: Any) -> Any:
    """A copy of a learning store config (or of a pre-built store carrying one)
    with every write-granting agent_can_* flag off. agent_can_search* flags are
    the read tools and stay on; the pattern covers flags this module has never
    seen, so a store gaining a new write flag upstream fails safe."""
    store_config = getattr(config, "config", None)
    if store_config is not None:
        store_copy = copy.copy(config)
        store_copy.config = _writes_off_learning_config(store_config)
        return store_copy
    config_copy = copy.copy(config)
    for flag in vars(config_copy):
        if flag.startswith("agent_can_") and not flag.startswith("agent_can_search"):
            setattr(config_copy, flag, False)
    config_model = getattr(config_copy, "model", None)
    if config_model is not None and hasattr(config_model, "cache_response"):
        config_copy.model = _cache_off_copy(config_model)
    return config_copy


def _read_only_learning_machine(machine: Any, source_db: Any) -> Any:
    """A per-attempt writes-severed copy of a LearningMachine.

    Learned knowledge is global state exactly like culture, so its READS -- the
    <learning_system> block, the search tools, store reads through the caller's
    knowledge and db -- survive the attempt (`source_db` carries the caller's db
    onto a machine that had none). Every write engine is severed: the
    extraction/curation hooks are no-ops on the copy (they fire whenever the
    machine exists, mode-gated per store), the agentic save/update/create tools
    go through _writes_off_learning_config, and custom stores -- opaque write
    surfaces -- are dropped loudly. Bare-True store configs (and the knowledge
    auto-enable, which defaults its save tools ON) are materialized first so the
    flag pass can reach them. Per-user reads still come back empty: the attempt
    runs a fresh rollout user. One deliberate prompt deviation follows from the
    severing: store context blocks that mention their update tools lose those
    sentences, exactly like the agentic memory/culture tool blocks -- write-tool
    text describes tools the attempt does not have."""
    from agno.learn.config import (
        DecisionLogConfig,
        EntityMemoryConfig,
        LearnedKnowledgeConfig,
        SessionContextConfig,
        UserMemoryConfig,
        UserProfileConfig,
    )

    store_config_types = {
        "user_profile": UserProfileConfig,
        "user_memory": UserMemoryConfig,
        "session_context": SessionContextConfig,
        "entity_memory": EntityMemoryConfig,
        "learned_knowledge": LearnedKnowledgeConfig,
        "decision_log": DecisionLogConfig,
    }

    machine_copy = copy.copy(machine)
    # Both are lazy caches over the config fields; reset so the copy's stores are
    # built from the writes-severed configs below, never shared with the caller's.
    machine_copy._stores = None
    machine_copy._curator = None
    if getattr(machine_copy, "db", None) is None and source_db is not None:
        machine_copy.db = source_db
    machine_model = getattr(machine_copy, "model", None)
    if machine_model is not None and hasattr(machine_model, "cache_response"):
        machine_copy.model = _cache_off_copy(machine_model)

    if not machine_copy.learned_knowledge and getattr(machine_copy, "knowledge", None) is not None:
        machine_copy.learned_knowledge = LearnedKnowledgeConfig()

    for field_name, config_type in store_config_types.items():
        value = getattr(machine_copy, field_name, None)
        if value is True:
            setattr(machine_copy, field_name, _writes_off_learning_config(config_type()))
        elif value and not isinstance(value, bool):
            # A config, or a built-in store carrying one (.config), can have its write
            # flags stripped. An opaque LearningStore (the protocol accepts one in this
            # slot) has neither -- isolation cannot neuter write tools it does not
            # understand, so a rollout would keep the store's write tools and share its
            # state by reference. Drop it loudly, exactly like custom_stores below; its
            # per-attempt reads are severed either way.
            if isinstance(value, config_type) or getattr(value, "config", None) is not None:
                setattr(machine_copy, field_name, _writes_off_learning_config(value))
            else:
                log_warning(
                    f"rollout isolation cannot make an opaque {field_name} learning store read-only; dropping it"
                )
                setattr(machine_copy, field_name, False)

    if getattr(machine_copy, "custom_stores", None):
        log_warning("rollout isolation cannot make custom learning stores read-only; dropping them")
        machine_copy.custom_stores = None

    def _noop_process(*args: Any, **kwargs: Any) -> None:
        return None

    async def _noop_aprocess(*args: Any, **kwargs: Any) -> None:
        return None

    # SAFETY-CRITICAL: this machine copy keeps the caller's db so global
    # learned-knowledge reads survive the attempt. These noops (together with the
    # write flags severed in _isolate_attempt) are therefore the ONLY barrier
    # against a learning write reaching the caller's real store. Do not remove
    # them in any refactor.
    machine_copy.process = _noop_process
    machine_copy.aprocess = _noop_aprocess
    return machine_copy


def _field_names_of(agent: Any) -> List[str]:
    """Declared dataclass fields UNIONED with live instance attributes.

    Agent is @dataclass(init=False), so fields() alone misses anything a subclass sets
    in its own __init__ -- and an unseen custom manager or model is exactly what the
    isolation walk exists to catch: it would stay bound to the caller's db (or keep its
    response cache on) inside every attempt. Union, not replacement: some declared
    fields are absent from vars() on an initialized agent, and dropping them would
    silently un-guard those slots. A list, not a generator: both callers setattr while
    iterating."""
    if is_dataclass(agent):
        names = [f.name for f in fields(agent)]
        seen = set(names)
        names.extend(name for name in vars(agent) if name not in seen)
        return names
    return list(vars(agent))


def _is_mcp_tool(tool: Any) -> bool:
    mro = getattr(type(tool), "__mro__", ())
    return any(c.__name__ in ("MCPTools", "MultiMCPTools") for c in mro)


def _resolved_tools_factory(tools: Any) -> Any:
    """Resolve a callable tools factory for inspection, failing closed: tools the
    guard never saw cannot be certified MCP-free. Production accepts factories
    taking injected parameters (agent, run_context, session_state) and async
    factories -- neither resolves under a plain zero-argument call, so both raise
    here instead of being silently treated as toolless."""
    try:
        resolved = tools()
    except Exception as exc:
        raise RuntimeError(
            "the agent's callable tools factory could not be resolved for MCP safety checking "
            f"({type(exc).__name__}: {exc}). A tools factory taking injected parameters (agent, "
            "run_context, session_state) cannot be called at run start, and unseen tools cannot "
            "be certified MCP-free. Use a concrete tools list, or build the tools inside an "
            "agent factory -- agent=lambda: Agent(..., tools=[...])."
        ) from exc
    if inspect.isawaitable(resolved):
        if inspect.iscoroutine(resolved):
            resolved.close()
        raise RuntimeError(
            "the agent's tools factory is async, so it could not be resolved for MCP safety "
            "checking at run start, and unseen tools cannot be certified MCP-free. Use a "
            "concrete tools list, or build the tools inside an agent factory -- "
            "agent=lambda: Agent(..., tools=[...])."
        )
    return resolved


def _mcp_tool_instances(agent: Any, _seen: Optional[Set[int]] = None) -> List[Any]:
    """The MCP tool OBJECTS an agent carries -- same traversal as _mcp_tool_names
    (callable factories resolved fail-closed, one level of composition, nested
    reasoning agent), returning the instances so two factory products can be
    compared by identity."""
    seen = _seen if _seen is not None else set()
    if id(agent) in seen:
        return []
    seen.add(id(agent))
    found: List[Any] = []
    tools = getattr(agent, "tools", None)
    if callable(tools):
        tools = _resolved_tools_factory(tools)
    if isinstance(tools, (list, tuple)):
        for tool in tools:
            if _is_mcp_tool(tool):
                found.append(tool)
                continue
            for attr in ("tools", "functions", "toolkits"):
                inner = getattr(tool, attr, None)
                if isinstance(inner, (list, tuple)):
                    found.extend(sub for sub in inner if _is_mcp_tool(sub))
    reasoning_agent = getattr(agent, "reasoning_agent", None)
    if reasoning_agent is not None:
        found.extend(_mcp_tool_instances(reasoning_agent, _seen=seen))
    return found


def _mcp_tool_names(agent: Any, _seen: Optional[Set[int]] = None, *, callable_only: bool = False) -> List[str]:
    """MCP tool class names on this agent or any nested agent the isolation walk
    reaches: deep_copy shares a reasoning agent's tools by reference exactly like
    top-level ones, so a nested MCPTools corrupts attempts the same way.

    A callable tools-factory is resolved here before inspection: production resolves it
    per attempt into run_context (not agent.tools), so connect_mcp_tools never connects
    it and aget_tools silently drops the unconnected MCP -- the agent runs toolless and
    the rollout greens a run that never had its tools. A factory this call cannot
    resolve fails closed via _resolved_tools_factory: production supports factories
    taking injected parameters and async factories, neither of which a plain
    zero-argument call can see into, and tools the guard never saw cannot be certified
    MCP-free. One level of container composition is walked so a toolkit wrapping
    MCPTools does not evade the top-level type check. With callable_only, only MCP
    hidden behind a callable factory is reported: a concrete tools=[MCPTools(...)]
    list is the supported per-attempt-factory pattern (each attempt owns a fresh
    connection) and is left alone."""
    seen = _seen if _seen is not None else set()
    if id(agent) in seen:
        return []
    seen.add(id(agent))
    names: List[str] = []
    tools = getattr(agent, "tools", None)
    tools_is_callable = callable(tools)
    if callable(tools):
        tools = _resolved_tools_factory(tools)
    if (tools_is_callable or not callable_only) and isinstance(tools, (list, tuple)):
        for tool in tools:
            if _is_mcp_tool(tool):
                names.append(type(tool).__name__)
                continue
            for attr in ("tools", "functions", "toolkits"):
                inner = getattr(tool, attr, None)
                if isinstance(inner, (list, tuple)):
                    names.extend(type(sub).__name__ for sub in inner if _is_mcp_tool(sub))
    reasoning_agent = getattr(agent, "reasoning_agent", None)
    if reasoning_agent is not None:
        names.extend(_mcp_tool_names(reasoning_agent, _seen=seen, callable_only=callable_only))
    return names


def _isolate_attempt(agent: Any, model_override: Optional[Model] = None, _seen: Optional[Set[int]] = None) -> None:
    """Attempt isolation by INPUT swap, applied per attempt to a factory product
    or a deep copy -- and recursively to a user-supplied reasoning agent, whose
    own deep_copy re-shares its db and model.

    The override swaps the attempt's inputs, lets production's own resolver
    (Agent.initialize_agent) run UNCHANGED against them, and only then severs
    write paths. It never writes a resolved read-shaping flag
    (add_memories_to_context, add_session_summary_to_context,
    add_culture_to_context, add_learnings_to_context): production computes those
    lazily from write signals plus manager presence, and with the inputs swapped
    first the attempt resolves them exactly as a fresh production user would --
    empty per-user reads render production's own empty states, not an absent
    block.

    Inputs, by kind:

    - Per-user state (memories, session history, session summaries, per-user
      learning stores) reads from a fresh empty InMemoryDb under a fresh rollout
      user id; the memory manager copy is rebound to the fresh db.
    - Global read-only stores keep the caller's data: knowledge and skills stay
      shared (retrieval goes through knowledge.vector_db, not agent.db), the
      culture manager copy keeps the caller's culture db, and a configured
      LearningMachine copy keeps the caller's db for its global learned-knowledge
      reads. These are the read paths deliberately NOT backed by the isolated db,
      which is why their write engines must be severed below -- empty inputs
      cannot neutralize a write into a shared store.
    - Every model slot -- primary, *_model fields, fallback lists, manager
      models -- runs on a copy with the response cache off: the cache is a shared
      disk cache keyed by messages, and a cached attempt is a replay, not a
      sample.
    - Manager copies are attempt-local, so resolution binds db and model onto
      them, never onto the caller's instances.

    Severed after resolution, and only because they act on the world: memory
    capture and the agentic memory tool, knowledge and culture write tools and
    post-run writes, learning extraction and save tools, the session-summary
    WRITE (an extra LLM call per attempt; the read resolves naturally and a
    fresh session has no summary to render), and save_response_to_file (K
    attempts would race-write the caller's file). add_history_to_context is NOT
    modified: a fresh session means empty history, the honest version of pinned.
    Compression stays on (it changes what the model sees) on an isolated copy so
    attempt stats and model bindings never land on the caller's manager.
    """
    seen = _seen if _seen is not None else set()
    if id(agent) in seen:
        return
    seen.add(id(agent))
    source_db = getattr(agent, "db", None)

    # -- inputs: every model slot runs on a cache-off copy ------------------
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

    # -- inputs: per-user state is a fresh empty world ----------------------
    fresh_db = InMemoryDb()
    agent.db = fresh_db
    agent.user_id = f"rollout-user-{uuid4().hex}"

    memory_manager = getattr(agent, "memory_manager", None)
    if memory_manager is not None:
        agent.memory_manager = _isolated_manager_copy(memory_manager, db=fresh_db)

    session_summary_manager = getattr(agent, "session_summary_manager", None)
    if session_summary_manager is not None:
        agent.session_summary_manager = _isolated_manager_copy(session_summary_manager)

    # -- inputs: global read-only stores keep the caller's data -------------
    culture_manager = getattr(agent, "culture_manager", None)
    if culture_manager is not None:
        agent.culture_manager = _isolated_manager_copy(
            culture_manager, db=source_db if getattr(culture_manager, "db", None) is None else None
        )
    elif source_db is not None and (
        getattr(agent, "add_culture_to_context", None)
        or getattr(agent, "update_cultural_knowledge", False)
        or getattr(agent, "enable_agentic_culture", False)
    ):
        # Production reads would come straight off agent.db; the attempt's db is
        # fresh, so an explicit manager bound to the caller's db keeps the reads
        # identical to a fresh production user's.
        from agno.culture.manager import CultureManager

        agent.culture_manager = CultureManager(db=source_db)

    learning = getattr(agent, "learning", None)
    if learning is not None and learning is not False:
        from agno.learn.machine import LearningMachine

        if learning is True:
            # Materialized into the default machine set_learning_machine would
            # build, because that builder RE-BUILDS on every initialize and would
            # resurrect the write engines on a machine it constructed itself. db
            # stays unbound so resolution binds the fresh db: learning=True
            # enables only per-user stores.
            agent.learning = _read_only_learning_machine(
                LearningMachine(user_profile=True, user_memory=True), source_db=None
            )
        elif isinstance(learning, LearningMachine):
            agent.learning = _read_only_learning_machine(learning, source_db)
        else:
            log_warning(
                f"rollout isolation cannot sever writes on a {type(learning).__name__} learning value; nulling it"
            )
            agent.learning = None

    compression_manager = getattr(agent, "compression_manager", None)
    if compression_manager is not None:
        agent.compression_manager = _isolated_manager_copy(compression_manager, reset_stats=True)

    # A manager this block has never seen is nulled loudly, BEFORE resolution
    # can bind anything onto it: managers bind db and model by pattern, and
    # silently sharing one is the exact leak this function exists to stop.
    for field_name in _field_names_of(agent):
        if (
            field_name.endswith("_manager")
            and field_name not in _ISOLATE_FIELD_ACTIONS
            and getattr(agent, field_name, None) is not None
        ):
            log_warning(f"rollout isolation does not know agent.{field_name}; nulling it")
            setattr(agent, field_name, None)

    # -- production's own resolver, unchanged, against the swapped inputs ---
    # Resolves the add_*_to_context read flags and materializes managers from
    # the ORIGINAL write signals, so the severing below can no longer re-shape
    # any read. Duck-typed subjects have no lazy resolution to run.
    if isinstance(agent, Agent):
        agent.initialize_agent()

    # -- sever write and side-effect paths ----------------------------------
    # SAFETY-CRITICAL: the culture and learning read paths above DELIBERATELY
    # share the caller's db, so the flags severed here (update_cultural_knowledge,
    # enable_agentic_culture) and the learning process/aprocess noops in
    # _read_only_learning_machine are the ONLY barrier between an attempt and a
    # write into the caller's real store. The shared-db read path depends on
    # these severs; do not remove them in any future refactor.
    agent.update_memory_on_run = False  # the post-run memory extraction call
    agent.enable_user_memories = False  # deprecated alias of update_memory_on_run
    agent.enable_agentic_memory = False  # the update_user_memory tool and its prompt block
    agent.update_knowledge = False  # the knowledge write tool: agent.knowledge stays shared
    agent.update_cultural_knowledge = False  # the post-run write into the caller's culture store
    agent.enable_agentic_culture = False  # the culture write tool and its prompt block
    agent.enable_session_summaries = False  # the post-run summary write, an extra LLM call
    agent.save_response_to_file = None  # K attempts would race-write the caller's file

    reasoning_agent = getattr(agent, "reasoning_agent", None)
    if reasoning_agent is not None:
        _isolate_attempt(reasoning_agent, _seen=seen)


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
    env: Environment,
    *,
    k: int = 8,
    tasks: Optional[Sequence[Task]] = None,
    model: Optional[Model] = None,
    concurrency: int = 4,
) -> EnvironmentRunResult:
    """Run every task K times, each attempt isolated, and score every attempt.

    Isolation is unconditional and there is no knob: each attempt runs against a
    fresh in-memory store and a fresh user id, so attempts can't contaminate each
    other or your real data -- contaminated statistics answer "does my agent work"
    wrongly, and contaminated trajectories poison the training set. Every attempt
    runs on a fresh copy whose INPUTS are swapped -- a fresh in-memory db, fresh
    session and user ids, the response cache off -- and then production's own
    resolver runs unchanged against those inputs, so the attempt's prompt is the
    prompt a fresh production user would get, by construction. Only write paths are
    severed afterwards: memory capture, knowledge/culture/learning writes, the
    session-summary write, save_response_to_file. Knowledge READS survive: retrieval
    goes through knowledge.vector_db, not agent.db, so a RAG agent retrieves
    normally inside a rollout -- and culture and learned-knowledge reads survive the
    same way, through writes-severed copies of the culture manager and the
    LearningMachine that keep the caller's db. Memory READS resolve against the
    attempt's empty db under a fresh rollout user, so they render production's own
    fresh-user empty states -- per-user state from the caller's world must not leak
    into a sample. The full field inventory lives on _isolate_attempt.

    Three residuals the overrides cannot reach, stated honestly:

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
    - User-supplied callables are shared by reference and run inside attempts with
      whatever side effects they carry: pre/post hooks fire per attempt, and a
      fallback_config.callback fires on attempt fallbacks. The override cannot
      reach into a callable; keep rollout-visible hooks idempotent or filter on
      the rollout-* ids they receive.

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
    # Declared duplicates are rejected at Environment construction; the positional case (an
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
        selected_list: List[Task] = []
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
        # Even a factory env must not hide MCP behind a CALLABLE tools factory: that
        # resolves per attempt into run_context, never connects, and is silently
        # dropped -- the attempt runs toolless and the rollout greens a run that never
        # had its tools. Concrete tools=[MCPTools(...)] built fresh per attempt is fine
        # and not flagged (callable_only).
        hidden_mcp = _mcp_tool_names(source_agent, callable_only=True)
        if hidden_mcp:
            raise RuntimeError(
                f"env.agent builds an agent whose tools are a callable factory hiding {hidden_mcp[0]}: "
                "that MCP is resolved per run but never connected, so the attempt runs with none of "
                "its tools and the rollout would report success for a toolless run. Put the MCP in a "
                "concrete list -- agent=lambda: Agent(..., tools=[MCPTools(...)]) -- so each attempt "
                "owns and connects its own."
            )
        # A factory that CLOSES OVER one MCP returns a fresh agent holding the same
        # session every call -- the anti-pattern rejected on the live path, invisible to
        # a single-product check. Compared by instance identity across two products, and
        # only when the first actually carries MCP, so the extra construction is paid
        # solely by MCP factories. Raised here, before any attempt: raising inside the
        # per-attempt build would be swallowed into attempt-error data, and the first
        # attempt would already have run green against the shared session.
        first_mcp = _mcp_tool_instances(source_agent)
        if first_mcp:
            probe_ids = {id(tool) for tool in _mcp_tool_instances(_validated_agent(env.agent()))}
            shared = [tool for tool in first_mcp if id(tool) in probe_ids]
            if shared:
                raise RuntimeError(
                    f"the env.agent factory returns the SAME {type(shared[0]).__name__} instance on every "
                    "call: every attempt shares one MCP session, and concurrent attempts connect and close "
                    "it mid-run, losing the batch. Construct the MCP INSIDE the factory -- "
                    "agent=lambda: Agent(..., tools=[MCPTools(...)]) -- so each attempt owns its own."
                )
    else:
        source_agent = env.agent
        # Live path: a factory constructs fresh MCP tools per attempt, which is exactly
        # the workaround this error names. _mcp_tool_names resolves callable tool
        # factories and walks one level of composition, so an MCP held by reference,
        # behind a lambda, or wrapped in a toolkit is all caught. Raised before any
        # connection or attempt exists.
        mcp_names = _mcp_tool_names(source_agent)
        if mcp_names:
            raise RuntimeError(
                f"env.agent holds {mcp_names[0]} (directly, behind a callable tools factory, or wrapped "
                "in a toolkit): every attempt would share one MCP session -- concurrent attempts connect "
                "and close it mid-run, losing the batch -- or, behind a factory, never connect it at all. "
                "Use a factory env -- agent=lambda: Agent(..., tools=[MCPTools(...)]) -- so each attempt "
                "owns its connection."
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
    except FingerprintError as exc:
        log_warning(f"env_fingerprint degraded to None: {exc}")

    policy_fingerprint: Optional[str] = None
    if effective_model is None:
        log_warning("policy_fingerprint degraded to None: the agent has no model")
    else:
        try:
            policy_fingerprint = _policy_fingerprint_of(effective_model)
        except FingerprintError as exc:
            log_warning(f"policy_fingerprint degraded to None: {exc}")

    expected_model_id = getattr(effective_model, "id", None)

    def build_attempt_agent() -> Any:
        is_factory = callable(env.agent)
        agent = _validated_agent(env.agent()) if callable(env.agent) else env.agent.deep_copy()
        _isolate_attempt(agent, model_override=model)
        # deep_copy rebuilds the agent through its own __init__ signature, so a subclass
        # declaring **kwargs loses every field -- the attempt then samples a different
        # (or default) model while the result carries the caller's policy fingerprint: a
        # green verification attributed to a policy that never ran. Live path only; a
        # factory is expected to build its own model. This reads the model AFTER
        # _isolate_attempt because initialize_agent() installs the default there -- if
        # that resolution ever moves later, this fires on every model-less agent.
        if not is_factory and expected_model_id is not None:
            actual_model_id = getattr(getattr(agent, "model", None), "id", None)
            if actual_model_id is not None and actual_model_id != expected_model_id:
                raise RuntimeError(
                    f"attempt agent sampled model {actual_model_id!r} but the run was fingerprinted against "
                    f"{expected_model_id!r}: env.agent does not survive deep_copy (an Agent subclass whose "
                    "__init__ takes **kwargs loses its fields), so results would be stamped with a policy "
                    "that never ran. Use a factory env -- agent=lambda: MyAgent(...) -- which is constructed "
                    "fresh per attempt."
                )
        return agent

    finished: List[AttemptResult] = []
    storm = {"stop": False}

    # The storm check aborts a run whose opening completions all failed identically (a
    # uniform misconfiguration -- a bad key, an unreachable base_url). It is confined to
    # single-task runs: scheduling is input-major, so in a multi-task run the opening
    # cohort is one task, and a single front-loaded failing task would otherwise abort
    # healthy tasks that never got to run -- making completeness depend on task order. A
    # floor keeps a tiny concurrency from aborting on the first error or two before there
    # is enough signal that the failure is uniform, not a flaky first sample. Armed only
    # when k exceeds the evidence window: at k <= the window every attempt has run (or
    # started) by the time the verdict is in, so there is nothing left to save by
    # stopping.
    storm_floor = 4
    storm_window = max(concurrency, storm_floor)
    storm_trip_at = storm_window if len(selected) == 1 and k > storm_window else 0

    def check_error_storm(attempt: AttemptResult) -> None:
        finished.append(attempt)
        if storm["stop"] or storm_trip_at == 0 or len(finished) != storm_trip_at:
            return
        first = finished[:storm_trip_at]
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
    # Stamped only when the stop actually cost attempts: in-flight attempts drain
    # after the trip, so a late trip can still complete the full plan, and a complete
    # run stamped stopped-early would misreport its own completeness.
    n_ran = sum(len(attempts) for attempts in batches)
    return EnvironmentRunResult(
        env_name=env.name,
        k=k,
        env_fingerprint=env_fingerprint,
        policy_fingerprint=policy_fingerprint,
        task_results=task_results,
        duration_seconds=time.perf_counter() - start,
        stopped_early="error-storm" if storm["stop"] and n_ran < k * len(selected) else None,
    )


def run_rollouts(
    env: Environment,
    *,
    k: int = 8,
    tasks: Optional[Sequence[Task]] = None,
    model: Optional[Model] = None,
    concurrency: int = 4,
) -> EnvironmentRunResult:
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
