"""Workflow structural events -> native AG-UI STATE (workflow_progress) + STEP.

A workflow's structural WorkflowRunEvents (started, step_*, loop/parallel/condition/
router_*, pause/continue, cancelled) surface as a flat steps[] progress object in
shared STATE -- the one channel the default AG-UI client auto-renders -- plus native
STEP_STARTED/STEP_FINISHED at flat step boundaries (emitted for protocol consistency;
they render nothing themselves). No CustomEvent: the author's own custom_event keeps
its passthrough via the RunEvent.custom_event handler.

v1 is intentionally FLAT: container events (loop/parallel/condition/router) are no-ops
here -- their inner steps emit their own step_started/completed and populate the list.
Grouping the topology is a deferred follow-up. Pause/cancel surface as a status only;
interactive resume is out of scope.
"""

import copy
from typing import Any, List, Optional

from ag_ui.core import (
    BaseEvent,
    EventType,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
)

from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.workflow_handlers import _event_value, _render_content
from agno.run.base import BaseRunOutputEvent
from agno.run.workflow import WorkflowRunEvent

_E = WorkflowRunEvent
_MAX_OUTPUT = 500  # cap step output stored in STATE so deltas stay small

_PAUSE_STEP = frozenset({_E.step_paused.value, _E.step_executor_paused.value, _E.step_output_review.value})
_PAUSE_WORKFLOW = frozenset({_E.workflow_paused.value, _E.router_paused.value})
_CONTINUE = frozenset({_E.step_continued.value, _E.step_executor_continued.value})


def _progress(state: StreamState) -> dict:
    if state.run_state is None:
        state.run_state = {}
    return state.run_state.setdefault("workflow_progress", {"status": "running", "steps": []})


def _baseline(state: StreamState) -> List[BaseEvent]:
    """First touch with no caller-supplied state: router.py emitted no initial snapshot
    and stream.py set no delta baseline -> establish one here so the workflow_progress
    deltas below have a reference to diff against."""
    if state.run_state is not None:
        return []
    state.run_state = {}
    state.set_state_snapshot(state.run_state)
    return [StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(state.run_state))]


def _emit_delta(state: StreamState) -> List[BaseEvent]:
    if state.run_state is None:
        return []
    ops = state.compute_state_delta(state.run_state)
    if not ops:
        return []
    state.set_state_snapshot(state.run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def _short(content: Any) -> Optional[str]:
    if content is None:
        return None
    text = _render_content(content)
    return text[:_MAX_OUTPUT] if text else None


def _open_step(steps: List[dict], index: Any) -> Optional[dict]:
    """Most recent not-yet-finished entry for this step_index (loops reuse indices)."""
    for step in reversed(steps):
        if step["step_index"] == index and step["status"] in ("running", "paused"):
            return step
    return None


def mark_completed(state: StreamState) -> None:
    """Promote a still-running workflow to 'completed' at terminal time. Never clobbers a
    'cancelled' / 'error' / 'paused' status already set by a structural event."""
    progress = state.workflow_progress
    if progress is not None and progress.get("status") == "running":
        progress["status"] = "completed"


def progress_handler(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Map one structural WorkflowRunEvent to a workflow_progress mutation (+ STEP)."""
    events = _baseline(state)
    value = _event_value(chunk)
    progress = _progress(state)
    state.workflow_progress = progress
    steps = progress["steps"]
    name = getattr(chunk, "step_name", None)
    raw_index = getattr(chunk, "step_index", None)
    index = list(raw_index) if isinstance(raw_index, tuple) else raw_index

    if value == _E.step_started.value:
        steps.append({"name": name, "status": "running", "step_index": index, "output": None})
        if name:
            events.append(StepStartedEvent(type=EventType.STEP_STARTED, step_name=name))
    elif value == _E.step_completed.value:
        step = _open_step(steps, index)
        if step is not None:
            step.update(status="completed", output=_short(getattr(chunk, "content", None)))
        if name:
            events.append(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name))
    elif value == _E.step_output.value:
        step = _open_step(steps, index)
        if step is not None:
            step["output"] = _short(getattr(chunk, "content", None))
    elif value == _E.step_error.value:
        step = _open_step(steps, index)
        if step is not None:
            step.update(status="error", output=_short(getattr(chunk, "error", None)))
        if name:
            events.append(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name))
    elif value in _PAUSE_STEP:
        step = _open_step(steps, index)
        if step is not None:
            step["status"] = "paused"
    elif value in _PAUSE_WORKFLOW:
        progress["status"] = "paused"
    elif value in _CONTINUE:
        step = _open_step(steps, index)
        if step is not None:
            step["status"] = "running"
    elif value == _E.workflow_cancelled.value:
        progress["status"] = "cancelled"
        state.cancelled = True
    # workflow_started initialises progress above; container/agent events are no-ops
    # (their inner step_started/completed populate the flat list).

    return events + _emit_delta(state)
