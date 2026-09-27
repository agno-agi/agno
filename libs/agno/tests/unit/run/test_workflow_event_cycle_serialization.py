"""Workflow event serialization survives cyclic object graphs.

dataclasses.asdict() traverses every field with NO cycle detection, and a
workflow event's deep fields can reach back to the event itself:
run_output.events contains the event, and
step_requirements[].step_input.workflow_session.runs[].events contains it
too - the WS HITL continue leg produces exactly that shape once the event
lands on the live run's event list. The blowup was racy in the wild
(depends on whether the append beat the serialization) and silently
dropped the event from every sink: to_json failed, the event-stream
publish failed, and the WebSocket delivery failed.
"""

import json

from agno.run.base import RunStatus
from agno.run.workflow import WorkflowPausedEvent, WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.utils.serialize import json_serializer
from agno.workflow.types import StepInput, StepRequirement


def _build_cyclic_paused_event() -> WorkflowPausedEvent:
    """The exact field path from the field repro:
    event.step_requirements[].step_input.workflow_session.runs[].events[]
    -> the same event object."""
    event = WorkflowPausedEvent(run_id="r-cycle", workflow_id="wf-1", workflow_name="WF", session_id="s-cycle")
    run_output = WorkflowRunOutput(
        run_id="r-cycle", workflow_id="wf-1", workflow_name="WF", session_id="s-cycle", status=RunStatus.paused
    )
    run_output.events = [event]  # the live run carries the event...
    session = WorkflowSession(session_id="s-cycle", workflow_id="wf-1", runs=[run_output])
    step_input = StepInput(input="v1.2.3", workflow_session=session)
    requirement = StepRequirement(
        step_id="step-1",
        step_name="Inspect Release",
        step_index=0,
        requires_confirmation=True,
        step_input=step_input,  # ...and the requirement's input reaches the live session
    )
    event.step_requirements = [requirement]
    return event


class TestCyclicEventSerialization:
    def test_paused_event_reaching_itself_serializes(self):
        event = _build_cyclic_paused_event()

        data = event.to_dict()  # RecursionError on unfixed source

        assert data["run_id"] == "r-cycle"
        reqs = data["step_requirements"]
        assert reqs and reqs[0]["step_id"] == "step-1"
        # The whole payload must survive the wire encoding too
        json.dumps(data, default=json_serializer)
        assert event.to_json()

    def test_deep_fields_are_restored_after_serialization(self):
        """The asdict cycle-guard temporarily clears the deep fields; a
        failure to restore would corrupt the LIVE event other sinks and the
        session store still read."""
        event = _build_cyclic_paused_event()
        requirement = event.step_requirements[0]

        event.to_dict()

        assert event.step_requirements == [requirement], "deep fields must be restored after to_dict"
        assert requirement.step_input is not None and requirement.step_input.workflow_session is not None

    def test_run_output_cycle_still_covered(self):
        """The previously-guarded cycle (run_output.events -> event) keeps
        working with the widened guard."""
        event = WorkflowPausedEvent(run_id="r-cycle2", workflow_id="wf-1", session_id="s")
        run_output = WorkflowRunOutput(run_id="r-cycle2", workflow_id="wf-1", session_id="s")
        run_output.events = [event]
        event.run_output = run_output

        data = event.to_dict()
        assert "run_output" not in data  # excluded by long-standing contract
        json.dumps(data, default=json_serializer)
