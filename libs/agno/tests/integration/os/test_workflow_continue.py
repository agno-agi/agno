"""Integration tests for the workflow /continue endpoint."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.factory import WorkflowFactory
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, UserInputField
from agno.workflow.workflow import Workflow


# -- simple executor functions (no LLM needed) --
def _gather(si: StepInput) -> StepOutput:
    return StepOutput(content="Data gathered")


def _detailed(si: StepInput) -> StepOutput:
    return StepOutput(content="Detailed analysis complete")


def _quick(si: StepInput) -> StepOutput:
    return StepOutput(content="Quick summary complete")


def _deep(si: StepInput) -> StepOutput:
    return StepOutput(content="Deep dive complete")


def _surface(si: StepInput) -> StepOutput:
    return StepOutput(content="Surface review complete")


def _report(si: StepInput) -> StepOutput:
    prev = si.previous_step_content or "nothing"
    return StepOutput(content=f"Final report based on: {prev}")


def _collect_user_input(si: StepInput) -> StepOutput:
    user_input = (si.additional_data or {}).get("user_input", {})
    return StepOutput(content=f"Research topic: {user_input.get('topic')}; details: {user_input.get('extra_details')}")


class WorkflowFactoryInput(BaseModel):
    mode: str = "default"


@pytest.fixture
def hitl_client(temp_storage_db_file):
    """Create a TestClient with a HITL workflow containing two Conditions."""
    db = SqliteDb(db_file=temp_storage_db_file)
    workflow = Workflow(
        name="decision-tree",
        id="decision-tree",
        db=db,
        steps=[
            Step(name="gather", executor=_gather),
            Condition(
                name="first_decision",
                requires_confirmation=True,
                confirmation_message="Run detailed analysis?",
                on_reject=OnReject.else_branch,
                steps=[Step(name="detailed", executor=_detailed)],
                else_steps=[Step(name="quick", executor=_quick)],
            ),
            Condition(
                name="second_decision",
                requires_confirmation=True,
                confirmation_message="Deep dive or surface review?",
                on_reject=OnReject.else_branch,
                steps=[Step(name="deep", executor=_deep)],
                else_steps=[Step(name="surface", executor=_surface)],
            ),
            Step(name="report", executor=_report),
        ],
    )
    app = AgentOS(workflows=[workflow]).get_app()
    return TestClient(app)


@pytest.fixture
def factory_hitl_client(temp_storage_db_file):
    """Create a TestClient with a HITL workflow factory."""
    db = SqliteDb(db_file=temp_storage_db_file)

    def build_workflow(ctx):
        return Workflow(
            name="decision-tree-factory",
            id="generated-decision-tree",
            db=db,
            metadata={"mode": getattr(ctx.input, "mode", None)},
            steps=[
                Step(name="gather", executor=_gather),
                Condition(
                    name="first_decision",
                    requires_confirmation=True,
                    confirmation_message="Run detailed analysis?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="detailed", executor=_detailed)],
                    else_steps=[Step(name="quick", executor=_quick)],
                ),
                Condition(
                    name="second_decision",
                    requires_confirmation=True,
                    confirmation_message="Deep dive or surface review?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=_deep)],
                    else_steps=[Step(name="surface", executor=_surface)],
                ),
                Step(name="report", executor=_report),
            ],
        )

    workflow_factory = WorkflowFactory(
        db=db,
        id="decision-tree-factory",
        factory=build_workflow,
        input_schema=WorkflowFactoryInput,
    )
    app = AgentOS(workflows=[workflow_factory]).get_app()
    return TestClient(app)


@pytest.fixture
def user_input_hitl_client(temp_storage_db_file):
    """Create a TestClient with a workflow that pauses for structured user input."""
    db = SqliteDb(db_file=temp_storage_db_file)
    workflow = Workflow(
        name="research-assistant",
        id="research-assistant",
        db=db,
        steps=[
            Step(
                name="collect_research_input",
                executor=_collect_user_input,
                requires_user_input=True,
                user_input_message="Please provide your research request:",
                user_input_schema=[
                    UserInputField(name="topic", field_type="str", required=True),
                    UserInputField(name="extra_details", field_type="str", required=False),
                ],
            ),
        ],
    )
    app = AgentOS(workflows=[workflow]).get_app()
    return TestClient(app)


@pytest.fixture
def router_hitl_client(temp_storage_db_file):
    """Create a TestClient with a workflow that pauses for router selection."""
    db = SqliteDb(db_file=temp_storage_db_file)
    workflow = Workflow(
        name="router-workflow",
        id="router-workflow",
        db=db,
        steps=[
            Router(
                name="analysis_router",
                choices=[
                    Step(name="quick_analysis", executor=_quick),
                    Step(name="deep_analysis", executor=_deep),
                ],
                requires_user_input=True,
                user_input_message="Select the type of analysis to perform:",
            ),
            Step(name="report", executor=_report),
        ],
    )
    app = AgentOS(workflows=[workflow]).get_app()
    return TestClient(app)


def _collect_sse_chunks(response):
    """Parse SSE stream into list of JSON chunks."""
    chunks = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            data = line[6:]
            if data != "[DONE]":
                chunks.append(json.loads(data))
    return chunks


def _find_event(chunks, event_name):
    """Find first chunk with given event name."""
    for c in chunks:
        if c.get("event") == event_name:
            return c
    return None


def _parse_ws_message(message: str):
    """Parse JSON or SSE-formatted WebSocket messages into event dictionaries."""
    if message.startswith("event: "):
        for line in message.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
    return json.loads(message)


def _receive_ws_event(websocket, event_name: str, max_messages: int = 20):
    """Receive WebSocket messages until the requested event arrives."""
    seen = []
    for _ in range(max_messages):
        event = _parse_ws_message(websocket.receive_text())
        seen.append(event.get("event"))
        if event.get("event") == event_name:
            return event
    raise AssertionError(f"Expected {event_name}, got: {seen}")


# =============================================================================
# Non-streaming tests
# =============================================================================


def test_continue_confirm_then_reject(hitl_client):
    """Test full HITL cycle: run -> pause -> confirm -> pause -> reject -> complete."""
    # 1. Start workflow — should pause at first Condition
    r = hitl_client.post("/workflows/decision-tree/runs", data={"message": "go", "stream": "false"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "PAUSED"
    assert d["step_requirements"][-1]["step_name"] == "first_decision"

    run_id = d["run_id"]
    session_id = d["session_id"]

    # 2. Confirm first decision — should pause at second Condition
    reqs = d["step_requirements"]
    reqs[-1]["confirmed"] = True
    r2 = hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id, "step_requirements": json.dumps(reqs)},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["status"] == "PAUSED"
    assert d2["step_requirements"][-1]["step_name"] == "second_decision"

    # 3. Reject second decision — should complete with else branch
    reqs2 = d2["step_requirements"]
    reqs2[-1]["confirmed"] = False
    r3 = hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id, "step_requirements": json.dumps(reqs2)},
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["status"] == "COMPLETED"
    assert d3["step_results"][1]["steps"][0]["content"] == "Detailed analysis complete"
    assert d3["step_results"][2]["steps"][0]["content"] == "Surface review complete"


def test_continue_confirm_both(hitl_client):
    """Test confirming both Conditions takes the main branch for both."""
    r = hitl_client.post("/workflows/decision-tree/runs", data={"message": "go", "stream": "false"})
    d = r.json()
    run_id = d["run_id"]
    session_id = d["session_id"]

    # Confirm first
    reqs = d["step_requirements"]
    reqs[-1]["confirmed"] = True
    r2 = hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id, "step_requirements": json.dumps(reqs)},
    )
    d2 = r2.json()
    assert d2["status"] == "PAUSED"

    # Confirm second (active requirement is the last one)
    reqs2 = d2["step_requirements"]
    reqs2[-1]["confirmed"] = True
    r3 = hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id, "step_requirements": json.dumps(reqs2)},
    )
    d3 = r3.json()
    assert d3["status"] == "COMPLETED"
    assert d3["step_results"][1]["steps"][0]["content"] == "Detailed analysis complete"
    assert d3["step_results"][2]["steps"][0]["content"] == "Deep dive complete"


def test_continue_factory_workflow_with_factory_input(factory_hitl_client):
    """Factory workflows should be resumable through /continue."""
    run_response = factory_hitl_client.post(
        "/workflows/decision-tree-factory/runs",
        data={
            "message": "go",
            "stream": "false",
            "factory_input": json.dumps({"mode": "guided"}),
        },
    )
    assert run_response.status_code == 200
    run_data = run_response.json()
    assert run_data["status"] == "PAUSED"

    run_id = run_data["run_id"]
    session_id = run_data["session_id"]
    requirements = run_data["step_requirements"]
    requirements[-1]["confirmed"] = True

    continue_response = factory_hitl_client.post(
        f"/workflows/decision-tree-factory/runs/{run_id}/continue",
        data={
            "stream": "false",
            "session_id": session_id,
            "factory_input": json.dumps({"mode": "guided"}),
            "step_requirements": json.dumps(requirements),
        },
    )
    assert continue_response.status_code == 200
    continue_data = continue_response.json()
    assert continue_data["status"] == "PAUSED"
    assert continue_data["run_id"] == run_id
    assert continue_data["step_requirements"]


def test_continue_409_on_completed_run(hitl_client):
    """Test that continuing an already-completed run returns 409."""
    r = hitl_client.post("/workflows/decision-tree/runs", data={"message": "go", "stream": "false"})
    d = r.json()
    run_id = d["run_id"]
    session_id = d["session_id"]

    # Confirm first
    reqs = d["step_requirements"]
    reqs[-1]["confirmed"] = True
    r2 = hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id, "step_requirements": json.dumps(reqs)},
    )

    # Confirm second (active is last)
    reqs2 = r2.json()["step_requirements"]
    reqs2[-1]["confirmed"] = True
    hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id, "step_requirements": json.dumps(reqs2)},
    )

    # Try to continue completed run
    r4 = hitl_client.post(
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "false", "session_id": session_id},
    )
    assert r4.status_code == 409


def test_continue_404_unknown_workflow(hitl_client):
    """Test that continuing on an unknown workflow returns 404."""
    r = hitl_client.post(
        "/workflows/unknown/runs/fake-run-id/continue",
        data={"stream": "false"},
    )
    assert r.status_code == 404


# =============================================================================
# Streaming tests
# =============================================================================


def test_continue_streaming_confirm_then_reject(hitl_client):
    """Test full HITL cycle with streaming: run -> pause -> confirm -> pause -> reject -> complete."""
    # 1. Start workflow (streaming) — should get StepPaused event
    with hitl_client.stream(
        "POST",
        "/workflows/decision-tree/runs",
        data={"message": "go", "stream": "true"},
    ) as r:
        assert r.status_code == 200
        chunks = _collect_sse_chunks(r)

    paused = _find_event(chunks, "StepPaused")
    assert paused is not None, f"Expected StepPaused, got: {[c.get('event') for c in chunks]}"
    assert paused["step_name"] == "first_decision"

    run_id = paused["run_id"]
    session_id = paused["session_id"]

    # 2. Confirm first decision (streaming) — should get another StepPaused
    reqs = [
        {
            "step_id": paused.get("step_id", ""),
            "step_name": paused["step_name"],
            "step_index": paused["step_index"],
            "requires_confirmation": True,
            "confirmation_message": paused.get("confirmation_message"),
            "confirmed": True,
            "on_reject": "else",
            "step_type": "Condition",
        }
    ]
    with hitl_client.stream(
        "POST",
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "true", "session_id": session_id, "step_requirements": json.dumps(reqs)},
    ) as r2:
        assert r2.status_code == 200
        chunks2 = _collect_sse_chunks(r2)

    paused2 = _find_event(chunks2, "StepPaused")
    assert paused2 is not None, f"Expected StepPaused, got: {[c.get('event') for c in chunks2]}"
    assert paused2["step_name"] == "second_decision"

    # 3. Reject second decision (streaming) — should get WorkflowCompleted
    reqs2 = [
        {
            "step_id": paused2.get("step_id", ""),
            "step_name": paused2["step_name"],
            "step_index": paused2["step_index"],
            "requires_confirmation": True,
            "confirmation_message": paused2.get("confirmation_message"),
            "confirmed": False,
            "on_reject": "else",
            "step_type": "Condition",
        }
    ]
    with hitl_client.stream(
        "POST",
        f"/workflows/decision-tree/runs/{run_id}/continue",
        data={"stream": "true", "session_id": session_id, "step_requirements": json.dumps(reqs2)},
    ) as r3:
        assert r3.status_code == 200
        chunks3 = _collect_sse_chunks(r3)

    completed = _find_event(chunks3, "WorkflowCompleted")
    assert completed is not None, f"Expected WorkflowCompleted, got: {[c.get('event') for c in chunks3]}"


# =============================================================================
# WebSocket tests
# =============================================================================


def test_websocket_continue_confirmation_pauses_again(hitl_client):
    """WebSocket continue should resolve confirmation HITL and stream the next pause."""
    with hitl_client.websocket_connect("/workflows/ws") as websocket:
        _receive_ws_event(websocket, "connected")

        websocket.send_json({"action": "start-workflow", "workflow_id": "decision-tree", "message": "go"})
        paused = _receive_ws_event(websocket, "StepPaused")
        assert paused["step_name"] == "first_decision"

        websocket.send_json(
            {
                "action": "continue-workflow",
                "workflow_id": "decision-tree",
                "run_id": paused["run_id"],
                "session_id": paused["session_id"],
                "step_requirements": [
                    {
                        "step_name": paused["step_name"],
                        "step_index": paused["step_index"],
                        "confirmed": True,
                    }
                ],
            }
        )

        continued = _receive_ws_event(websocket, "StepContinued")
        assert continued["step_name"] == "first_decision"
        paused_again = _receive_ws_event(websocket, "StepPaused")
        assert paused_again["step_name"] == "second_decision"


def test_websocket_continue_user_input(user_input_hitl_client):
    """WebSocket continue should pass user_input values into the resumed step."""
    with user_input_hitl_client.websocket_connect("/workflows/ws") as websocket:
        _receive_ws_event(websocket, "connected")

        websocket.send_json({"action": "start-workflow", "workflow_id": "research-assistant", "message": "go"})
        paused = _receive_ws_event(websocket, "StepPaused")
        assert paused["step_name"] == "collect_research_input"
        assert paused["requires_user_input"] is True

        websocket.send_json(
            {
                "action": "continue-workflow",
                "workflow_id": "research-assistant",
                "run_id": paused["run_id"],
                "session_id": paused["session_id"],
                "step_requirements": [
                    {
                        "step_name": paused["step_name"],
                        "step_index": paused["step_index"],
                        "user_input": {
                            "topic": "Artificial Intelligence in Healthcare",
                            "extra_details": "Focus on diagnostics",
                        },
                    }
                ],
            }
        )

        completed = _receive_ws_event(websocket, "WorkflowCompleted")
        assert "Artificial Intelligence in Healthcare" in completed["content"]
        assert "Focus on diagnostics" in completed["content"]


def test_websocket_continue_router_selection(router_hitl_client):
    """WebSocket continue should pass selected_choices into router HITL."""
    with router_hitl_client.websocket_connect("/workflows/ws") as websocket:
        _receive_ws_event(websocket, "connected")

        websocket.send_json({"action": "start-workflow", "workflow_id": "router-workflow", "message": "go"})
        paused = _receive_ws_event(websocket, "RouterPaused")
        assert paused["step_name"] == "analysis_router"

        websocket.send_json(
            {
                "action": "continue-workflow",
                "workflow_id": "router-workflow",
                "run_id": paused["run_id"],
                "session_id": paused["session_id"],
                "step_requirements": [
                    {
                        "step_name": paused["step_name"],
                        "step_index": paused["step_index"],
                        "selected_choices": ["deep_analysis"],
                    }
                ],
            }
        )

        completed = _receive_ws_event(websocket, "WorkflowCompleted")
        assert "Deep dive complete" in completed["content"]


def test_websocket_continue_events_replay_on_reconnect(hitl_client):
    """Continuation events should be buffered and replayable after WebSocket reconnect."""
    run_id = None
    session_id = None
    last_event_index = None

    with hitl_client.websocket_connect("/workflows/ws") as websocket:
        _receive_ws_event(websocket, "connected")

        websocket.send_json({"action": "start-workflow", "workflow_id": "decision-tree", "message": "go"})
        paused = _receive_ws_event(websocket, "StepPaused")
        run_id = paused["run_id"]
        session_id = paused["session_id"]
        last_event_index = paused.get("event_index")

        websocket.send_json(
            {
                "action": "continue-workflow",
                "workflow_id": "decision-tree",
                "run_id": run_id,
                "session_id": session_id,
                "step_requirements": [
                    {
                        "step_name": paused["step_name"],
                        "step_index": paused["step_index"],
                        "confirmed": True,
                    }
                ],
            }
        )
        _receive_ws_event(websocket, "StepContinued")
        _receive_ws_event(websocket, "StepPaused")

    with hitl_client.websocket_connect("/workflows/ws") as websocket:
        _receive_ws_event(websocket, "connected")

        websocket.send_json(
            {
                "action": "reconnect",
                "workflow_id": "decision-tree",
                "run_id": run_id,
                "session_id": session_id,
                "last_event_index": last_event_index,
            }
        )
        replay = _receive_ws_event(websocket, "replay")
        assert replay["status"] == "PAUSED"
        continued = _receive_ws_event(websocket, "StepContinued")
        assert continued["event_index"] > last_event_index
        paused_again = _receive_ws_event(websocket, "StepPaused")
        assert paused_again["step_name"] == "second_decision"
