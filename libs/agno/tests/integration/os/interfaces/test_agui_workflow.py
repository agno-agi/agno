import os
from typing import Dict

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

from ._agui_sse import (
    assert_event_absent,
    assert_valid_wire_stream,
    get_event_types,
    make_request_body,
    parse_sse_events,
)

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui import AGUI  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"),
]

THREAD_ID = "workflow-thread"
RUN_ID = "workflow-run"
CLIENT_STATE = {"seen": 0}


def summarize_length(step_input: StepInput) -> StepOutput:
    """A step with no model, so the interface has to surface its output itself."""
    previous = str(step_input.previous_step_content or "")
    return StepOutput(content=f"The greeting was {len(previous.split())} words long.")


# Every test below reads the same run, so it is paid for once per module.
@pytest.fixture(scope="module")
def response():
    greeter = Agent(
        name="workflow-greeter",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Greet the user in one short sentence.",
        telemetry=False,
    )
    workflow = Workflow(
        id="agui-integration-workflow",
        name="Greeting Workflow",
        steps=[
            Step(name="Greet", agent=greeter),
            Step(name="Measure", executor=summarize_length),
        ],
        telemetry=False,
    )
    agent_os = AgentOS(workflows=[workflow], interfaces=[AGUI(workflow=workflow)], telemetry=False)
    # As a context manager so the app lifespan runs, which is what a served AgentOS does.
    with TestClient(agent_os.get_app()) as client:
        return client.post(
            "/agui",
            json=make_request_body("Say hello", state=CLIENT_STATE, thread_id=THREAD_ID, run_id=RUN_ID),
        )


@pytest.fixture(scope="module")
def events(response):
    return parse_sse_events(response.text)


class TestWorkflowOverAGUI:
    """A Workflow served over AG-UI, run end to end against a real model."""

    def test_workflow_run_completes_end_to_end(self, response, events):
        assert response.status_code == 200

        types = get_event_types(events)
        assert_event_absent(types, "RUN_ERROR")

        assert types[0] == "RUN_STARTED"
        assert types[-1] == "RUN_FINISHED"

    def test_the_served_stream_obeys_the_protocol_framing_rules(self, events):
        """The hand-built chunk lists in the mapper suites cannot stand in for this one."""
        assert_valid_wire_stream(events)

    def test_every_step_span_is_balanced(self, events):
        started = [e.get("stepName") for e in events if e.get("type") == "STEP_STARTED"]
        finished = [e.get("stepName") for e in events if e.get("type") == "STEP_FINISHED"]

        assert started == ["Greet", "Measure"]
        assert finished == ["Greet", "Measure"]

    def test_both_the_agent_step_and_the_plain_step_produce_text(self, events):
        by_message: Dict[str, str] = {}
        for event in events:
            if event.get("type") == "TEXT_MESSAGE_CONTENT":
                by_message.setdefault(event["messageId"], "")
                by_message[event["messageId"]] += event["delta"]

        messages = list(by_message.values())
        assert len(messages) >= 2
        assert any("words long" in message for message in messages)

    def test_state_snapshots_bracket_the_run_and_carry_the_state(self, events):
        types = get_event_types(events)
        snapshots = [e["snapshot"] for e in events if e.get("type") == "STATE_SNAPSHOT"]

        assert types[1] == "STATE_SNAPSHOT"
        assert types[-2] == "STATE_SNAPSHOT"
        assert types[-1] == "RUN_FINISHED"

        assert snapshots[0] == CLIENT_STATE

        # Nothing here writes session state of its own: the terminal WorkflowCompletedEvent
        # carries none, and a plain function step gets no handle on it. So the closing
        # snapshot is the client's own state plus the run identity the interface handed
        # down. Asserting it exactly is what keeps other internals out of the browser.
        assert snapshots[-1] == {**CLIENT_STATE, "current_session_id": THREAD_ID, "current_run_id": RUN_ID}
