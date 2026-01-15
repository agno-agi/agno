"""Integration tests for running Workflows in AgentOS."""

import json
from unittest.mock import AsyncMock, patch

from agno.workflow.workflow import Workflow


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
