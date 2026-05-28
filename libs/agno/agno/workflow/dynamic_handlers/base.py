"""Shared types and the base SpawnHandler interface for dynamic workflows.

Phase 1 of the dynamic-workflows refactor: the previous god-object `_SpawnState` is
split into three orthogonal concerns so each new spawn type (Condition, Loop,
Parallel, Router) can plug in cleanly:

- `_RunContext`: workflow execution context, immutable per run.
- `_TrailBuilder`: the running trail as a tree of _TrailNode + mutation primitives.
- `_StreamBridge`: opt-in event-sink for live streaming.

Each `_SpawnHandler` subclass implements one spawn type (agent / condition / loop /
parallel / router) and takes these three args. The driver tool closures forward the
LLM's arguments into the appropriate handler.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from agno.run.base import RunContext
    from agno.run.workflow import ExecutedStepRecord, WorkflowRunOutput
    from agno.session.workflow import WorkflowSession
    from agno.workflow.types import StepOutput, WorkflowExecutionInput


# Node kinds in the internal trail tree. Leaves are "agent". Composites mirror the
# static workflow primitives so emitted StepOutputs match what static produces.
TrailNodeKind = Literal["agent", "condition", "loop", "parallel", "router"]


@dataclass
class _TrailNode:
    """Internal tree node for the running trail.

    Agent leaves carry the role/instructions/input/output. Composite nodes (loop,
    parallel, condition, router) carry children. The tree is what we use during a
    run to express nesting; at the end we flatten it into two persisted shapes:

    - `WorkflowRunOutput.step_results`: nested StepOutputs (static-compatible).
    - `WorkflowRunOutput.executed_steps`: flat list of leaf ExecutedStepRecords
      with `parent_id` pointing at the composite that birthed them.
    """

    kind: TrailNodeKind
    step_id: str = field(default_factory=lambda: str(uuid4()))
    parent_id: Optional[str] = None
    iteration: int = 0

    # Agent-leaf fields
    role: Optional[str] = None
    instructions: Optional[str] = None
    input: Optional[str] = None
    output: Optional["StepOutput"] = None
    tools: Optional[List[str]] = None
    model_tier: Optional[str] = None

    # Composite-node fields
    name: Optional[str] = None  # composite step name (e.g. "maybe_fact_check")
    branch: Optional[str] = None  # for Condition: "if" or "else"
    children: List["_TrailNode"] = field(default_factory=list)


@dataclass
class _RunContext:
    """Workflow execution context, immutable per run.

    Carries everything a spawn handler needs to participate in the static-path
    infrastructure (Step.execute → events, retries, step_executor_runs persistence,
    history, media flow).
    """

    workflow: Optional[Any] = None
    workflow_run_response: Optional["WorkflowRunOutput"] = None
    run_context: Optional["RunContext"] = None
    workflow_session: Optional["WorkflowSession"] = None
    execution_input: Optional["WorkflowExecutionInput"] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    store_executor_outputs: bool = True
    add_workflow_history_to_steps: Optional[bool] = None
    num_history_runs: int = 3
    background_tasks: Optional[Any] = None
    add_dependencies_to_context: Optional[bool] = None
    add_session_state_to_context: Optional[bool] = None


@dataclass
class _TrailBuilder:
    """Mutable trail + iteration counter + spawn cap, with a lock for concurrency.

    Single source of truth for the running trail during one workflow run. Spawn
    handlers append nodes here; at end-of-run we flatten into step_results and
    executed_steps on the workflow_run_response.
    """

    root_children: List[_TrailNode] = field(default_factory=list)
    leaf_records: List["ExecutedStepRecord"] = field(default_factory=list)
    previous_step_outputs: Dict[str, "StepOutput"] = field(default_factory=dict)
    iteration: int = 0
    spawn_count: int = 0
    max_steps: int = 10
    lock: threading.Lock = field(default_factory=threading.Lock)

    def claim_iteration(self) -> Optional[int]:
        """Atomically take the next iteration number or return None if max_steps is hit."""
        with self.lock:
            if self.spawn_count >= self.max_steps:
                return None
            n = self.iteration
            self.iteration += 1
            self.spawn_count += 1
            return n

    def add_top_level(self, node: _TrailNode) -> None:
        with self.lock:
            self.root_children.append(node)

    def add_leaf_record(self, record: "ExecutedStepRecord") -> None:
        with self.lock:
            self.leaf_records.append(record)


@dataclass
class _StreamBridge:
    """Opt-in streaming bridge. When set, every event a spawn emits goes to event_sink."""

    event_sink: Optional[Callable[[Any], None]] = None
    stream_events: bool = False
    stream_executor_events: bool = True

    @property
    def active(self) -> bool:
        return self.event_sink is not None

    def emit(self, event: Any) -> None:
        if self.event_sink is not None:
            self.event_sink(event)


class _SpawnHandler(ABC):
    """Base class for one spawn type (agent / condition / loop / parallel / router).

    A handler is stateless aside from references to the driver's policy (model,
    allowed_tools, etc.). Each `spawn` call takes the run's three context objects
    plus spawn-specific kwargs, runs the spawn, and returns the trail node it built.
    """

    @abstractmethod
    def spawn(
        self,
        ctx: _RunContext,
        trail: _TrailBuilder,
        stream: _StreamBridge,
        **kwargs: Any,
    ) -> _TrailNode:
        """Execute one spawn, append it to the trail, return the node."""
        raise NotImplementedError
