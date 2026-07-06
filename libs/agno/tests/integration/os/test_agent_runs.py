"""Integration tests for running Agents in AgentOS."""

import json
from unittest.mock import AsyncMock, patch

from agno.agent.agent import Agent
from agno.run import RunContext


def test_create_agent_run(test_os_client, test_agent: Agent):
    """Test creating an agent run using form input."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={"message": "Hello, world!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["agent_id"] == test_agent.id
    assert response_json["content"] is not None


def test_create_agent_run_streaming(test_os_client, test_agent: Agent):
    """Test creating an agent run with streaming enabled."""
    with test_os_client.stream(
        "POST",
        f"/agents/{test_agent.id}/runs",
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
        assert first_chunk.get("agent_id") == test_agent.id

        # Verify content across chunks
        content_chunks = [chunk.get("content") for chunk in chunks if chunk.get("content")]
        assert len(content_chunks) > 0


def test_running_unknown_agent_returns_404(test_os_client):
    """Test running an unknown agent returns a 404 error."""
    response = test_os_client.post(
        "/agents/unknown-agent/runs",
        data={"message": "Hello, world!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_create_agent_run_without_message_returns_422(test_os_client, test_agent: Agent):
    """Test that missing required message field returns validation error."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422


def test_create_agent_run_with_kwargs(test_os_client, test_agent: Agent):
    """Test that the create_agent_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    # Patch deep_copy to return the same instance so our mock works
    # (AgentOS uses create_fresh=True which calls deep_copy)
    with (
        patch.object(test_agent, "deep_copy", return_value=test_agent),
        patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            f"/agents/{test_agent.id}/runs",
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


def test_create_agent_run_with_media_kwargs_no_duplicate(test_os_client, test_agent: Agent):
    """Regression for #8771: media fields arriving as request kwargs must not collide
    with the explicit ``images=``/``audio=``/``videos=``/``files=`` params of ``arun``.

    A RemoteAgent (e.g. a remote team member) serializes ``images``/``audio``/``videos``
    into JSON form fields. On the server these are not declared parameters of
    ``create_agent_run``, so they fall through into ``kwargs``. Passing both
    ``images=...`` explicitly and ``**kwargs`` (which also holds ``images``) previously
    raised ``TypeError: arun() got multiple values for keyword argument 'images'``.
    """

    class MockRunOutput:
        def to_dict(self):
            return {}

    # Mimic what the AgentOS client sends for a remote agent run.
    images_payload = json.dumps([{"content": None, "url": "https://example.com/a.png"}])
    audio_payload = json.dumps([{"content": None, "url": "https://example.com/a.mp3"}])
    videos_payload = json.dumps([{"content": None, "url": "https://example.com/a.mp4"}])

    with (
        patch.object(test_agent, "deep_copy", return_value=test_agent),
        patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            f"/agents/{test_agent.id}/runs",
            data={
                "message": "Describe this",
                "stream": "false",
                "images": images_payload,
                "audio": audio_payload,
                "videos": videos_payload,
                # A normal non-media kwarg must still be forwarded.
                "extra_field": "foo",
            },
        )

        # Without the fix this raises TypeError inside the handler -> HTTP 500.
        assert response.status_code == 200

        # arun must have been called exactly once, with each media kwarg present once.
        assert mock_arun.call_count == 1
        call_kwargs = mock_arun.call_args.kwargs
        assert "images" in call_kwargs
        assert "audio" in call_kwargs
        assert "videos" in call_kwargs
        # The explicit media params win; the raw JSON strings from kwargs are not
        # forwarded (no UploadFile was sent, so they resolve to None).
        assert call_kwargs["images"] != images_payload
        assert call_kwargs["audio"] != audio_payload
        assert call_kwargs["videos"] != videos_payload
        # Non-media kwargs are still forwarded untouched.
        assert call_kwargs["extra_field"] == "foo"


def test_create_agent_run_streaming_with_media_kwargs_no_duplicate(test_os_client, test_agent: Agent):
    """Streaming variant of the #8771 regression.

    The streaming path forwards the same explicit media params plus ``**kwargs`` into
    ``agent_response_streamer``, which also binds them to named params, so the duplicate
    ``images`` kwarg must be stripped before the call too.
    """

    async def _fake_arun(*args, **kwargs):
        from agno.run.agent import RunContentEvent

        yield RunContentEvent(run_id="run-1", content="hello")

    images_payload = json.dumps([{"content": None, "url": "https://example.com/a.png"}])

    with (
        patch.object(test_agent, "deep_copy", return_value=test_agent),
        patch.object(test_agent, "arun", side_effect=_fake_arun) as mock_arun,
    ):
        with test_os_client.stream(
            "POST",
            f"/agents/{test_agent.id}/runs",
            data={
                "message": "Describe this",
                "stream": "true",
                "images": images_payload,
            },
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        # A duplicate-kwarg TypeError would surface as a RunError event, not content.
        assert "hello" in body
        assert mock_arun.call_count == 1
        assert mock_arun.call_args.kwargs["images"] != images_payload


def test_kwargs_propagate_to_run_context(test_os_client, test_agent: Agent):
    """Test passing kwargs to an agent run."""

    def assert_run_context(run_context: RunContext):
        assert run_context.user_id == "test-user-123"
        assert run_context.session_id == "test-session-123"
        assert "test_session_state" in run_context.session_state
        assert run_context.session_state["test_session_state"] == "test-session-state"
        assert run_context.dependencies == {"test_dependencies": "test-dependencies"}
        assert run_context.metadata == {"test_metadata": "test-metadata"}
        assert run_context.knowledge_filters == {"test_knowledge_filters": "test-knowledge-filters"}

    test_agent.pre_hooks = [assert_run_context]

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Hello, world!",
            "stream": "false",
            "user_id": "test-user-123",
            "session_id": "test-session-123",
            "session_state": {"test_session_state": "test-session-state"},
            "dependencies": {"test_dependencies": "test-dependencies"},
            "metadata": {"test_metadata": "test-metadata"},
            "knowledge_filters": {"test_knowledge_filters": "test-knowledge-filters"},
            "add_dependencies_to_context": True,
            "add_session_state_to_context": True,
            "add_history_to_context": False,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["agent_id"] == test_agent.id
    assert response_json["content"] is not None
