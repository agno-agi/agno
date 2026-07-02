"""Integration tests for running Workflows in AgentOS."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport
from pydantic import BaseModel

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.workflow.factory import WorkflowFactory
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def _factory_workflow_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content=f"Factory workflow handled: {step_input.message}")


class FactoryWorkflowInput(BaseModel):
    flavor: str = "default"


def test_create_workflow_run(test_os_client, test_workflow: Workflow):
    """Test creating a workflow run using form input."""
    response = test_os_client.post(
        f"/workflows/{test_workflow.id}/runs",
        data={"message": "Hello, world!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["workflow_id"] == test_workflow.id
    assert response_json["content"] is not None


def test_create_workflow_run_streaming(test_os_client, test_workflow: Workflow):
    """Test creating a workflow run with streaming enabled."""
    with test_os_client.stream(
        "POST",
        f"/workflows/{test_workflow.id}/runs",
        data={
            "message": "Hello, world!",
            "stream": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Collect streaming chunks
        chunks = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]  # Remove 'data: ' prefix
                if data != "[DONE]":
                    chunks.append(json.loads(data))

        # Verify we received data
        assert len(chunks) > 0

        # Check first chunk has expected fields
        first_chunk = chunks[0]
        assert first_chunk.get("run_id") is not None
        assert first_chunk.get("workflow_id") == test_workflow.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0


def test_running_unknown_workflow_returns_404(test_os_client):
    """Test running an unknown workflow returns a 404 error."""
    response = test_os_client.post(
        "/workflows/unknown-workflow/runs",
        data={"message": "Hello, world!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow not found"


def test_create_workflow_run_without_message_returns_422(test_os_client, test_workflow: Workflow):
    """Test that missing required message field returns validation error."""
    response = test_os_client.post(
        f"/workflows/{test_workflow.id}/runs",
        data={},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422


def test_create_workflow_run_with_kwargs(test_os_client, test_workflow: Workflow):
    """Test that the create_agent_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    # Patch deep_copy to return the same instance so our mock works
    # (AgentOS uses create_fresh=True which calls deep_copy)
    with (
        patch.object(test_workflow, "deep_copy", return_value=test_workflow),
        patch.object(test_workflow, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            f"/workflows/{test_workflow.id}/runs",
            data={
                "message": "Hello, world!",
                "stream": "false",
                # Passing some extra fields to the run endpoint
                "extra_field": "foo",
                "extra_field_two": "bar",
            },
        )
        assert response.status_code == 200

        # Asserting our extra fields were passed as kwargs
        call_args = mock_arun.call_args
        assert call_args.kwargs["extra_field"] == "foo"
        assert call_args.kwargs["extra_field_two"] == "bar"


@pytest.fixture
def factory_workflow_client(temp_storage_db_file):
    """Create a TestClient with a workflow factory registered in AgentOS."""
    db = SqliteDb(db_file=temp_storage_db_file)

    def build_workflow(ctx):
        return Workflow(
            name="factory-workflow",
            id="generated-workflow",
            steps=[Step(name="step1", executor=_factory_workflow_step)],
            db=db,
            metadata={"flavor": getattr(ctx.input, "flavor", None)},
        )

    workflow_factory = WorkflowFactory(
        db=db,
        id="factory-workflow",
        factory=build_workflow,
        input_schema=FactoryWorkflowInput,
    )

    app = AgentOS(workflows=[workflow_factory]).get_app()
    return TestClient(app)


def test_factory_workflow_get_run_and_list_runs(factory_workflow_client):
    """Factory workflows should support run polling and run listing after creation."""
    create_response = factory_workflow_client.post(
        "/workflows/factory-workflow/runs",
        data={
            "message": "Hello from factory workflow",
            "stream": "false",
            "factory_input": json.dumps({"flavor": "vanilla"}),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert create_response.status_code == 200

    run_data = create_response.json()
    run_id = run_data["run_id"]
    session_id = run_data["session_id"]

    get_response = factory_workflow_client.get(
        f"/workflows/factory-workflow/runs/{run_id}",
        params={"session_id": session_id, "factory_input": json.dumps({"flavor": "vanilla"})},
    )
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["run_id"] == run_id
    assert get_data["workflow_id"] == "factory-workflow"

    list_response = factory_workflow_client.get(
        "/workflows/factory-workflow/runs",
        params={"session_id": session_id, "factory_input": json.dumps({"flavor": "vanilla"})},
    )
    assert list_response.status_code == 200
    runs = list_response.json()
    assert any(run["run_id"] == run_id for run in runs)


@pytest.fixture
def websocket_factory_client(temp_storage_db_file):
    """Create a WebSocket TestClient with an authorized workflow factory.

    The fixture records what the factory sees in ``factory_calls`` so tests can
    assert on the trusted JWT context *after* the run without swallowing
    assertions inside the factory callback (which would surface as opaque
    "Factory error: ..." frames).
    """

    secret = "x" * 40
    os_id = "ws-factory-os"

    db = SqliteDb(db_file=temp_storage_db_file)
    factory_calls: list[dict] = []

    def websocket_workflow_step(_: StepInput) -> StepOutput:
        return StepOutput(content="ok")

    def build_workflow(ctx):
        factory_calls.append(
            {
                "claims": dict(ctx.trusted.claims) if ctx.trusted.claims else {},
                "scopes": set(ctx.trusted.scopes) if ctx.trusted.scopes else set(),
            }
        )
        return Workflow(
            id="ws-factory",
            name="ws-factory",
            steps=[Step(name="s", executor=websocket_workflow_step)],
            db=db,
        )

    app = AgentOS(
        id=os_id,
        workflows=[
            WorkflowFactory(
                id="ws-factory",
                db=db,
                factory=build_workflow,
            )
        ],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret],
            algorithm="HS256",
        ),
        telemetry=False,
    ).get_app()

    with TestClient(app) as client:
        yield {
            "client": client,
            "secret": secret,
            "os_id": os_id,
            "factory_calls": factory_calls,
        }


def _issue_token(secret: str, os_id: str, sub: str, scopes: list[str]) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "aud": os_id,
            "scopes": scopes,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        secret,
        algorithm="HS256",
    )


def _authenticate_ws(ws, token: str, expected_user_id: str) -> None:
    connection_event = json.loads(ws.receive_text())
    assert connection_event["event"] == "connected"

    ws.send_text(json.dumps({"action": "authenticate", "token": token}))

    for _ in range(5):
        frame = json.loads(ws.receive_text())
        if frame.get("event") == "authenticated" and frame.get("user_id") == expected_user_id:
            return
    raise AssertionError(f"Did not receive authenticated event for user_id={expected_user_id}")


def _drain_until(ws, predicate, max_frames: int = 20) -> str:
    """Read text frames until ``predicate(frame_text)`` is truthy or the limit is hit."""
    for _ in range(max_frames):
        frame = ws.receive_text()
        if predicate(frame):
            return frame
    raise AssertionError(f"No frame matched predicate within {max_frames} frames")


def test_websocket_workflow_factory_receives_trusted_jwt_context(
    websocket_factory_client,
):
    """Regression for #8684: WS start-workflow must forward JWT context to factory.

    Assertions live in the test body (not the factory callback) so a regression
    shows up as a clear diff on captured claims/scopes rather than an opaque
    ``Factory error: ...`` frame.
    """

    client = websocket_factory_client["client"]
    secret = websocket_factory_client["secret"]
    os_id = websocket_factory_client["os_id"]
    factory_calls = websocket_factory_client["factory_calls"]

    token = _issue_token(secret, os_id, sub="alice", scopes=["workflows:run"])

    with client.websocket_connect("/workflows/ws") as ws:
        _authenticate_ws(ws, token, expected_user_id="alice")

        ws.send_text(
            json.dumps(
                {
                    "action": "start-workflow",
                    "workflow_id": "ws-factory",
                    "message": "go",
                }
            )
        )

        started = _drain_until(ws, lambda f: "WorkflowStarted" in f)
        assert '"workflow_id": "ws-factory"' in started

    assert len(factory_calls) == 1, "Factory should be built exactly once"
    call = factory_calls[0]
    assert call["claims"].get("sub") == "alice", (
        f"Factory did not see trusted JWT sub. Saw claims={call['claims']}. "
        "This means websocket_user_context was not forwarded to "
        "handle_workflow_via_websocket — see agno/os/router.py."
    )
    assert "workflows:run" in call["scopes"], f"Factory did not see trusted JWT scopes. Saw scopes={call['scopes']}."


def test_websocket_workflow_factory_rejects_missing_scope(
    websocket_factory_client,
):
    """A token without ``workflows:run`` must be blocked at the dispatcher RBAC gate.

    The factory must not even be invoked in this case — the reject happens
    before ``handle_workflow_via_websocket`` is called.
    """

    client = websocket_factory_client["client"]
    secret = websocket_factory_client["secret"]
    os_id = websocket_factory_client["os_id"]
    factory_calls = websocket_factory_client["factory_calls"]

    token = _issue_token(secret, os_id, sub="alice", scopes=[])

    with client.websocket_connect("/workflows/ws") as ws:
        _authenticate_ws(ws, token, expected_user_id="alice")

        ws.send_text(
            json.dumps(
                {
                    "action": "start-workflow",
                    "workflow_id": "ws-factory",
                    "message": "go",
                }
            )
        )

        error_frame = json.loads(_drain_until(ws, lambda f: '"event": "error"' in f))
        assert error_frame["event"] == "error"
        assert "permission" in error_frame["error"].lower()

    assert factory_calls == [], "Factory must not be invoked when RBAC rejects the call"


# =============================================================================
# Workflow Version Tests
# =============================================================================


@pytest.fixture
def versioned_workflow_client(temp_storage_db_file):
    """Create a TestClient with a DB-only AgentOS containing two published workflow versions."""
    db = SqliteDb(db_file=temp_storage_db_file)

    db.create_component_with_config(
        component_id="versioned-wf",
        component_type=ComponentType.WORKFLOW,
        name="Workflow Alpha",
        config={"name": "Workflow Alpha", "id": "versioned-wf", "description": "First version"},
        stage="published",
    )
    db.upsert_config(
        component_id="versioned-wf",
        config={"name": "Workflow Beta", "id": "versioned-wf", "description": "Second version"},
        stage="published",
    )

    agent_os = AgentOS(db=db)
    app = agent_os.get_app()
    return TestClient(app)


def test_get_workflow_version_returns_specific_version(versioned_workflow_client):
    """Test GET /workflows/{id}?version=1 returns version 1 config."""
    response = versioned_workflow_client.get("/workflows/versioned-wf", params={"version": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Workflow Alpha"
    assert data["description"] == "First version"


def test_get_workflow_version_returns_different_version(versioned_workflow_client):
    """Test GET /workflows/{id}?version=2 returns version 2 config."""
    response = versioned_workflow_client.get("/workflows/versioned-wf", params={"version": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Workflow Beta"
    assert data["description"] == "Second version"


def test_get_workflow_without_version_returns_current(versioned_workflow_client):
    """Test GET /workflows/{id} without version returns latest published version."""
    response = versioned_workflow_client.get("/workflows/versioned-wf")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Workflow Beta"
    assert data["description"] == "Second version"


def test_get_workflow_nonexistent_version_returns_404(versioned_workflow_client):
    """Test GET /workflows/{id}?version=999 returns 404."""
    response = versioned_workflow_client.get("/workflows/versioned-wf", params={"version": 999})
    assert response.status_code == 404


# =============================================================================
# Workflow Version Tests (Async)
# =============================================================================


@pytest.fixture
def versioned_workflow_app(temp_storage_db_file):
    """Create a FastAPI app with a DB-only AgentOS containing two published workflow versions."""
    db = SqliteDb(db_file=temp_storage_db_file)

    db.create_component_with_config(
        component_id="versioned-wf",
        component_type=ComponentType.WORKFLOW,
        name="Workflow Alpha",
        config={"name": "Workflow Alpha", "id": "versioned-wf", "description": "First version"},
        stage="published",
    )
    db.upsert_config(
        component_id="versioned-wf",
        config={"name": "Workflow Beta", "id": "versioned-wf", "description": "Second version"},
        stage="published",
    )

    agent_os = AgentOS(db=db)
    return agent_os.get_app()


@pytest.mark.asyncio
async def test_aget_workflow_version_returns_specific_version(versioned_workflow_app):
    """Test async GET /workflows/{id}?version=1 returns version 1 config."""
    async with httpx.AsyncClient(transport=ASGITransport(app=versioned_workflow_app), base_url="http://test") as client:
        response = await client.get("/workflows/versioned-wf", params={"version": 1})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Workflow Alpha"
        assert data["description"] == "First version"


@pytest.mark.asyncio
async def test_aget_workflow_version_returns_different_version(versioned_workflow_app):
    """Test async GET /workflows/{id}?version=2 returns version 2 config."""
    async with httpx.AsyncClient(transport=ASGITransport(app=versioned_workflow_app), base_url="http://test") as client:
        response = await client.get("/workflows/versioned-wf", params={"version": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Workflow Beta"
        assert data["description"] == "Second version"


@pytest.mark.asyncio
async def test_aget_workflow_without_version_returns_current(versioned_workflow_app):
    """Test async GET /workflows/{id} without version returns latest published version."""
    async with httpx.AsyncClient(transport=ASGITransport(app=versioned_workflow_app), base_url="http://test") as client:
        response = await client.get("/workflows/versioned-wf")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Workflow Beta"
        assert data["description"] == "Second version"


@pytest.mark.asyncio
async def test_aget_workflow_nonexistent_version_returns_404(versioned_workflow_app):
    """Test async GET /workflows/{id}?version=999 returns 404."""
    async with httpx.AsyncClient(transport=ASGITransport(app=versioned_workflow_app), base_url="http://test") as client:
        response = await client.get("/workflows/versioned-wf", params={"version": 999})
        assert response.status_code == 404
