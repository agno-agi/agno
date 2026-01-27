"""Integration tests for running Teams in AgentOS."""

import json
from unittest.mock import AsyncMock, patch

from agno.run import RunContext
from agno.team.team import Team


def test_create_team_run(test_os_client, test_team: Team):
    """Test creating a team run using form input."""
    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={"message": "Hello, world!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["team_id"] == test_team.id
    assert response_json["content"] is not None


def test_create_team_run_streaming(test_os_client, test_team: Team):
    """Test creating a team run with streaming enabled."""
    with test_os_client.stream(
        "POST",
        f"/teams/{test_team.id}/runs",
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
        assert first_chunk.get("team_id") == test_team.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0


def test_running_unknown_team_returns_404(test_os_client):
    """Test running an unknown team returns a 404 error."""
    response = test_os_client.post(
        "/teams/unknown-team/runs",
        data={"message": "Hello, world!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Team not found"


def test_create_team_run_without_message_returns_422(test_os_client, test_team: Team):
    """Test that missing required message field returns validation error."""
    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422


def test_passing_kwargs_to_team_run(test_os_client, test_team: Team):
    """Test passing kwargs to a team run."""

    def assert_run_context(run_context: RunContext):
        assert run_context.user_id == "test-user-123"
        assert run_context.session_id == "test-session-123"
        assert run_context.session_state == {"test_session_state": "test-session-state"}
        assert run_context.dependencies == {"test_dependencies": "test-dependencies"}
        assert run_context.metadata == {"test_metadata": "test-metadata"}
        assert run_context.knowledge_filters == {"test_knowledge_filters": "test-knowledge-filters"}

    test_team.pre_hooks = [assert_run_context]

    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "Hello, world!",
            "user_id": "test-user-123",
            "session_id": "test-session-123",
            "session_state": {"test_session_state": "test-session-state"},
            "dependencies": {"test_dependencies": "test-dependencies"},
            "metadata": {"test_metadata": "test-metadata"},
            "knowledge_filters": {"test_knowledge_filters": "test-knowledge-filters"},
            "stream": "false",
            "add_dependencies_to_context": True,
            "add_session_state_to_context": True,
            "add_history_to_context": False,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["team_id"] == test_team.id
    assert response_json["content"] is not None


def test_create_team_run_with_kwargs(test_os_client, test_team: Team):
    """Test that the create_team_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    # Patch deep_copy to return the same instance so our mock works
    # (AgentOS uses create_fresh=True which calls deep_copy)
    with (
        patch.object(test_team, "deep_copy", return_value=test_team),
        patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            f"/teams/{test_team.id}/runs",
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
