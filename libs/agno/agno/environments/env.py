"""Env and EnvTask: the task set, the scorer, and the two fingerprints."""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from agno.agent import Agent
from agno.models.base import Model
from agno.scorer import EnvFingerprintError, Scorer
from agno.scorer._model import model_identity_payload, model_prompt_payload
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

_TASK_KEYS = {"input", "expected", "id", "metadata"}


@dataclass(frozen=True, eq=False)
class EnvTask:
    """One task row: an input and, optionally, the value the agent should produce.

    `id` is for display and selection; when None it defaults to t1..tN positionally at
    run start. `eq=False` keeps identity semantics -- the auto-generated __hash__
    would raise the first time a task sat in a set (metadata is a mapping).
    """

    input: str
    expected: Optional[Any] = None
    id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_jsonl(cls, path: Union[str, Path]) -> Tuple["EnvTask", ...]:
        """Load tasks from JSONL: required "input" (str); optional "expected", "id",
        "metadata" (object). Any other top-level key raises ValueError naming the line
        number and the key -- an "expected_output" column must not silently yield
        expected=None on every task, which under a None-tolerant scorer greens
        everything.
        """
        tasks: List[EnvTask] = []
        text = Path(path).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.split("\n"), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: not valid JSON: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"line {line_number}: expected an object, got {type(row).__name__}")
            unknown = sorted(set(row) - _TASK_KEYS)
            if unknown:
                raise ValueError(
                    f"line {line_number}: unknown key {unknown[0]!r} (allowed: input, expected, id, metadata)"
                )
            if "input" not in row or not isinstance(row["input"], str):
                raise ValueError(f"line {line_number}: 'input' is required and must be a string")
            metadata = row.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError(f"line {line_number}: 'metadata' must be an object")
            row_id = row.get("id")
            if row_id is not None and not isinstance(row_id, str):
                raise ValueError(f"line {line_number}: 'id' must be a string")
            tasks.append(cls(input=row["input"], expected=row.get("expected"), id=row_id, metadata=metadata))
        return tuple(tasks)

    @classmethod
    async def afrom_jsonl(cls, path: Union[str, Path]) -> Tuple["EnvTask", ...]:
        """Async twin of from_jsonl."""
        return await asyncio.to_thread(cls.from_jsonl, path)


@dataclass(frozen=True, eq=False)
class Env:
    """An agent, a task set, and a scorer -- the unit `run_rollouts` runs.

    `frozen=True` guarantees wiring, not state: the fields cannot be rebound, so a
    result provably came from this task set, scorer, and policy object. It does not
    freeze the agent -- nothing can -- which is why both fingerprints are computed at
    run start and stamped on the result: drift between construction and run is
    detected there, not prevented here.

    A live `agent` is deep-copied per attempt; a callable is a factory, called per
    attempt. The agent reference must stay live: rehydrating a model through
    Agent.from_dict drops sampling params, base_url, and credentials -- exactly the
    fields reproducibility depends on.
    """

    name: str
    tasks: Tuple[EnvTask, ...]
    scorer: Scorer
    agent: Union[Agent, Callable[[], Agent]]
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        object.__setattr__(self, "tasks", tuple(self.tasks))
        declared_ids: set = set()
        for index, task in enumerate(self.tasks):
            if not isinstance(task, EnvTask):
                raise TypeError(f"tasks[{index}] must be an EnvTask, got {type(task).__name__}")
            if task.id is not None:
                # A duplicated id makes diff() silently pair rows with the wrong
                # baseline task; positional collisions with auto-ids are caught at
                # run start, where t1..tN resolution happens.
                if task.id in declared_ids:
                    raise ValueError(f"duplicate task id {task.id!r}; task ids must be unique")
                declared_ids.add(task.id)
        received = type(self.agent).__name__
        # The Team check runs before the Agent accept: a hybrid subclassing both must
        # not slip through as an Agent.
        try:
            from agno.team.team import Team
        except ImportError:
            Team = None  # type: ignore[assignment, misc]
        if Team is not None and isinstance(self.agent, Team):
            raise TypeError(
                f"Env.agent does not accept a Team (got {received}); team environments "
                "arrive in the team release with member-level isolation"
            )
        # Discrimination is callable(x): Agent defines no __call__. Anything else
        # raises at construction, naming the received type.
        if isinstance(self.agent, Agent) or callable(self.agent):
            return
        raise TypeError(f"Env.agent must be an Agent or a zero-arg factory returning one, got {received}")

    def _source_agent(self) -> Agent:
        """One agent instance to fingerprint. For a factory env this constructs one
        instance per call -- documented behavior of calling the fingerprint methods
        directly; the rollouts runner instead computes both fingerprints from the
        first instance it constructs at run start."""
        if isinstance(self.agent, Agent):
            return self.agent
        return _validated_agent(self.agent())

    def env_fingerprint(self) -> str:
        return _env_fingerprint_of(self, self._source_agent())

    def policy_fingerprint(self) -> str:
        agent = self._source_agent()
        model = getattr(agent, "model", None)
        if model is None:
            raise EnvFingerprintError("policy_fingerprint needs a model; the agent has none")
        return _policy_fingerprint_of(model)

    def env_matches(self, other: Any) -> bool:
        """False when either side's env fingerprint is None -- a plain == would pass
        trivially when both are None, a false green in exactly the case the feature
        exists for."""
        return _fingerprints_match(_env_fingerprint_or_none(self), _env_fingerprint_or_none(other))


def _validated_agent(product: Any) -> Any:
    """A factory product is validated where it is materialized: the Team exclusion
    would otherwise be bypassed by wrapping the Team in a lambda. A Team is rejected
    by type BEFORE the Agent accept (a hybrid subclassing both must not slip through;
    it has `arun`, so the duck check cannot catch it either); anything that cannot
    run at all is rejected by the duck check, which deliberately still admits
    agent-shaped stand-ins -- the engine's subject contract is duck-typed."""
    received = type(product).__name__
    try:
        from agno.team.team import Team
    except ImportError:
        Team = None  # type: ignore[assignment, misc]
    if Team is not None and isinstance(product, Team):
        raise TypeError(
            f"Env.agent factory returned a Team ({received}); team environments arrive "
            "in the team release with member-level isolation"
        )
    if not callable(getattr(product, "arun", None)):
        raise TypeError(f"Env.agent factory must return an Agent, got {received}")
    return product


def _resolved_task_id(task: EnvTask, index: int) -> str:
    """The display/selection id: the declared one, or t1..tN positionally."""
    return task.id if task.id is not None else f"t{index + 1}"


def _canonical(payload: Any) -> str:
    """Canonical JSON. Never default=str: object reprs can embed memory addresses and
    flip the hash across processes, reporting "environment drifted" forever between
    two identical envs."""
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise EnvFingerprintError(f"fingerprint component is not JSON-serializable: {exc}") from exc


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _scorer_digest(scorer: Scorer) -> str:
    digest = getattr(scorer, "digest", None)
    if digest is None or not callable(digest):
        raise EnvFingerprintError(
            f"scorer {type(scorer).__name__} has no digest(); the env_fingerprint degrades to None"
        )
    return digest()


def _declared_tool_schemas(agent: Agent) -> List[Dict[str, Any]]:
    """The declared tool schemas, hashed as declared -- never after parse_tools.

    Strict-mode schema mutation depends on output_schema crossed with model
    capabilities, so a post-parse_tools hash would be a function of the model,
    breaking the env/policy split. Hashing declared schemas also avoids parse_tools'
    side effect on agent._tool_instructions.
    """
    tools = getattr(agent, "tools", None)
    if tools is None:
        return []
    if not isinstance(tools, (list, tuple)):
        # A callable tools factory resolves per run; there is no declared schema.
        raise EnvFingerprintError("agent.tools is a factory; declared tool schemas cannot be fingerprinted")
    schemas: List[Dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict):
            schemas.append(tool)
        elif isinstance(tool, Toolkit):
            merged = dict(tool.functions)
            merged.update(getattr(tool, "async_functions", {}) or {})
            for name in sorted(merged):
                schemas.append(merged[name].to_dict())
        elif isinstance(tool, Function):
            schemas.append(tool.to_dict())
        elif callable(tool):
            schemas.append(Function.from_callable(tool).to_dict())
        else:
            raise EnvFingerprintError(f"cannot fingerprint tool of type {type(tool).__name__}")
    # Name-less dict tools (provider builtins like {"type": "file_search"}) would all
    # sort under "" and leak declaration order into the hash; the canonical-JSON
    # tiebreak keeps the fingerprint order-insensitive for them too.
    return sorted(schemas, key=lambda schema: (str(schema.get("name", "")), _canonical(schema)))


def _prompt_component(value: Any, label: str) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise EnvFingerprintError(f"agent.{label} is {type(value).__name__}; only strings and lists fingerprint")


def _env_fingerprint_of(env: "Env", agent: Agent, model: Optional[Model] = None) -> str:
    """sha256 over the environment identity: tasks, scorer, declared tools, prompt
    strings (agent-level and model-level), declared session_state, and termination
    settings.

    Model-level system_prompt/instructions are prompt-shaped and therefore
    environment, not policy: they enter here and are excluded from the policy
    payload. `model` is the model whose prompt fields count -- the runner passes the
    EFFECTIVE model so a prompt-bearing override reads as an environment change;
    callers that omit it get the agent's declared model.

    Every component failure surfaces as EnvFingerprintError -- including exceptions
    raised while BUILDING the payload (a sourceless scorer, a schema builder choking
    on an exotic tool) -- so the runner's catch-and-degrade-to-None is complete and a
    fingerprint can never crash a run.
    """
    if model is None:
        model = getattr(agent, "model", None)
    try:
        payload = {
            "tasks": [
                [_resolved_task_id(task, index), task.input, task.expected] for index, task in enumerate(env.tasks)
            ],
            "scorer": _scorer_digest(env.scorer),
            "tools": _declared_tool_schemas(agent),
            "instructions": _prompt_component(getattr(agent, "instructions", None), "instructions"),
            "description": _prompt_component(getattr(agent, "description", None), "description"),
            "system_message": _prompt_component(getattr(agent, "system_message", None), "system_message"),
            "model_prompt": model_prompt_payload(model),
            "session_state": getattr(agent, "session_state", None),
            "termination": {
                "timeout_seconds": env.timeout_seconds,
                "tool_call_limit": getattr(agent, "tool_call_limit", None),
            },
        }
    except EnvFingerprintError:
        raise
    except Exception as exc:
        raise EnvFingerprintError(f"fingerprint component failed: {type(exc).__name__}: {exc}") from exc
    return _sha256(payload)


def _policy_fingerprint_of(model: Model) -> str:
    """sha256 over the policy identity: model class, id, provider, base_url, and
    every enumerated request-shaping param (see agno.scorer._model). The id is in
    the payload: gpt-5.5 and gpt-5.5-mini must not hash identically -- that is
    exactly the drift the split exists to catch."""
    try:
        payload: Dict[str, Any] = model_identity_payload(model)
    except EnvFingerprintError:
        raise
    except Exception as exc:
        raise EnvFingerprintError(f"fingerprint component failed: {type(exc).__name__}: {exc}") from exc
    return _sha256(payload)


def _env_fingerprint_or_none(obj: Any) -> Optional[str]:
    fingerprint = getattr(obj, "env_fingerprint", None)
    if callable(fingerprint):
        try:
            return fingerprint()
        except EnvFingerprintError:
            return None
    return fingerprint


def _fingerprints_match(left: Optional[str], right: Optional[str]) -> bool:
    if left is None or right is None:
        return False
    return left == right
