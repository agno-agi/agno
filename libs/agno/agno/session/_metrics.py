"""Accumulate only the unaccounted portion of each agent or team run."""

from copy import deepcopy
from dataclasses import fields
from typing import TYPE_CHECKING, Any, Dict, Iterable, Iterator, Union

from agno.metrics import BaseMetrics, RunMetrics, SessionMetrics
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput

if TYPE_CHECKING:
    from agno.session.agent import AgentSession
    from agno.session.team import TeamSession


def _with_members(runs: Iterable[Union[RunOutput, TeamRunOutput]]) -> Iterator[Union[RunOutput, TeamRunOutput]]:
    for run in runs:
        yield run
        if isinstance(run, TeamRunOutput):
            yield from _with_members(run.member_responses)


def initialize_session_metrics(session: Union["AgentSession", "TeamSession"]) -> None:
    """Freeze loaded contributions before continuation can mutate the session's runs.

    Keep this runtime state outside dataclass fields so it is not serialized.
    Cached sessions retain their snapshots across checkpoints and continuations.
    """
    if "_accounted_run_metrics" in session.__dict__:
        return
    accounted = {}
    if session.session_data and session.session_data.get("session_metrics") is not None:
        accounted = {
            run.run_id: deepcopy(run.metrics)
            for run in _with_members(session.runs or [])
            if run.run_id is not None and run.metrics is not None
        }
    session.__dict__["_accounted_run_metrics"] = accounted


def update_session_metrics(
    session: Union["AgentSession", "TeamSession"],
    session_metrics: SessionMetrics,
    run_response: Union[RunOutput, TeamRunOutput],
) -> None:
    """Replace this run's previous contribution, preserving all other session usage."""
    if session.session_data is None:
        session.session_data = {}
    # New sessions can reach persistence directly, without the load helpers.
    accounted: Dict[str, RunMetrics] = session.__dict__.setdefault("_accounted_run_metrics", {})
    for run in _with_members([run_response]):
        if run.metrics is None:
            continue
        previous = accounted.get(run.run_id) if run.run_id is not None else None
        if previous is not None:
            session_metrics.accumulate_from_run(_negated_metrics(previous))
        session_metrics.accumulate_from_run(run.metrics)
        if run.run_id is not None:
            # Run objects and their metrics may be shared by shallow checkpoint copies.
            accounted[run.run_id] = deepcopy(run.metrics)
    session.session_data["session_metrics"] = session_metrics.to_dict()


def _negated_metrics(metrics: RunMetrics) -> RunMetrics:
    """Undo a contribution using the existing scalar and per-model merge semantics."""
    payload = metrics.to_dict()
    entries = [payload] + [entry for group in payload.get("details", {}).values() for entry in group]
    for entry in entries:
        for counter in fields(BaseMetrics):
            if entry.get(counter.name) is not None:
                entry[counter.name] = -entry[counter.name]
        for key in ("additional_metrics", "provider_metrics"):
            values: Any = entry.get(key)
            if isinstance(values, dict):
                entry[key] = {
                    name: -value if isinstance(value, (int, float)) else value for name, value in values.items()
                }
    return RunMetrics.from_dict(payload)
