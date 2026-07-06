"""Unit tests for A2AClient using a2a-sdk.

These tests mock the underlying a2a-sdk Client + AgentCard resolution
so they can run without a live A2A server. The a2a-sdk types are
constructed directly with valid Pydantic models so the tests exercise
the real translation path between SDK and Agno objects.
"""

from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.client.a2a import (
    A2AClient,
    StreamEvent,
    TaskResult,
)
from agno.exceptions import RemoteServerUnavailableError


# ---------------------------------------------------------------------------
# Helpers: build a2a-sdk Pydantic objects for tests
# ---------------------------------------------------------------------------


def _make_agent_card(url: str = "http://localhost:7777"):
    """Build a minimal AgentCard for tests."""
    from a2a.types import AgentCapabilities, AgentCard

    return AgentCard(
        name="test-agent",
        url=url,
        description="test agent",
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )


def _make_completed_task(task_id: str = "task-123", context_id: str = "ctx-456", agent_text: str = "hi"):
    """Build a completed a2a Task with a single agent text history entry."""
    from a2a.types import (
        Message as A2AMessage,
        Part,
        Role,
        Task as A2ATask,
        TaskState,
        TaskStatus,
        TextPart,
    )

    return A2ATask(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=TaskState.completed),
        history=[
            A2AMessage(
                message_id="m1",
                role=Role.agent,
                parts=[Part(root=TextPart(text=agent_text))],
            )
        ],
        artifacts=[],
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestA2AClientInit:
    """A2AClient initialization keeps the previous public shape."""

    def test_init_default_values(self):
        client = A2AClient("http://localhost:7777")
        assert client.base_url == "http://localhost:7777"
        assert client.timeout == 30
        assert client.protocol == "json-rpc"  # default is now JSON-RPC (was 'rest' pre-a2a-sdk)
        # SDK client is created lazily on first call.
        assert client._sdk_client is None

    def test_init_custom_timeout(self):
        client = A2AClient("http://localhost:8080/", timeout=60, protocol="json-rpc")
        assert client.base_url == "http://localhost:8080"  # Trailing slash stripped
        assert client.timeout == 60
        assert client.protocol == "json-rpc"

    def test_init_does_not_eagerly_resolve_card(self):
        """Constructor must stay cheap: it should not touch the network."""
        with patch("agno.client.a2a.client.A2ACardResolver") as mock_resolver_cls:
            A2AClient("http://localhost:7777")
            mock_resolver_cls.assert_not_called()


class TestSendMessage:
    """send_message delegates to the a2a-sdk Client and converts the response."""

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """The SDK yields a ``(Task, status_update, artifact_update)`` tuple in
        non-streaming mode. ``A2AClient.send_message`` must turn that into
        a populated :class:`TaskResult`."""
        completed_task = _make_completed_task(agent_text="The answer is 4")
        # Real SDK shape: tuple(Task, status_update, artifact_update)
        sdk_event = (completed_task, None, None)

        mock_client = MagicMock()
        mock_client.send_message = MagicMock(return_value=_async_iter([sdk_event]))

        with patch.object(A2AClient, "_ensure_sdk_client", AsyncMock(return_value=mock_client)):
            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            result = await client.send_message(message="What is 2 + 2?")

        assert isinstance(result, TaskResult)
        assert result.content == "The answer is 4"
        assert result.is_completed
        assert result.task_id == "task-123"
        assert result.context_id == "ctx-456"

        # Verify the SDK was driven with a proper Message payload.
        mock_client.send_message.assert_called_once()
        sent_message = mock_client.send_message.call_args.args[0]
        assert sent_message.role.value == "user"
        assert sent_message.parts[0].root.text == "What is 2 + 2?"

    @pytest.mark.asyncio
    async def test_send_message_user_id_in_metadata(self):
        """The user_id kwarg must land in the message metadata as ``userId``."""
        completed_task = _make_completed_task()
        mock_client = MagicMock()
        mock_client.send_message = MagicMock(return_value=_async_iter([(completed_task, None, None)]))

        with patch.object(A2AClient, "_ensure_sdk_client", AsyncMock(return_value=mock_client)):
            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            await client.send_message(message="hi", user_id="alice-123")

        sent_message = mock_client.send_message.call_args.args[0]
        assert sent_message.metadata is not None
        assert sent_message.metadata.get("userId") == "alice-123"

    @pytest.mark.asyncio
    async def test_send_message_with_context_id(self):
        """context_id is preserved on the outgoing message."""
        completed_task = _make_completed_task()
        mock_client = MagicMock()
        mock_client.send_message = MagicMock(return_value=_async_iter([(completed_task, None, None)]))

        with patch.object(A2AClient, "_ensure_sdk_client", AsyncMock(return_value=mock_client)):
            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            await client.send_message(message="hi", context_id="ctx-abc")

        sent_message = mock_client.send_message.call_args.args[0]
        assert sent_message.context_id == "ctx-abc"

    @pytest.mark.asyncio
    async def test_send_message_connection_error_during_card_resolve(self):
        with patch.object(
            A2AClient,
            "_ensure_sdk_client",
            AsyncMock(side_effect=RemoteServerUnavailableError("boom", "http://localhost:7777", None)),
        ):
            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            with pytest.raises(RemoteServerUnavailableError):
                await client.send_message(message="hi")

    @pytest.mark.asyncio
    async def test_send_message_runtime_error_during_call(self):
        """Errors raised inside the SDK call must surface as RemoteServerUnavailableError."""
        mock_client = MagicMock()
        mock_client.send_message = MagicMock(side_effect=RuntimeError("upstream boom"))

        with patch.object(A2AClient, "_ensure_sdk_client", AsyncMock(return_value=mock_client)):
            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            with pytest.raises(RemoteServerUnavailableError) as exc_info:
                await client.send_message(message="hi")
            assert "upstream boom" in str(exc_info.value)


class TestStreamMessage:
    """stream_message yields StreamEvent objects translated from SDK responses."""

    @pytest.mark.asyncio
    async def test_stream_message_yields_terminal_task(self):
        """The SDK yields one or more (Task, status_update, artifact_update)
        tuples. ``A2AClient.stream_message`` must translate them into
        ``StreamEvent`` objects with the right ``event_type`` and
        ``is_final`` flags."""
        terminal_task = _make_completed_task(agent_text="hello")
        sdk_terminal = (terminal_task, None, None)

        mock_client = MagicMock()
        mock_client.send_message = MagicMock(return_value=_async_iter([sdk_terminal]))

        with patch.object(A2AClient, "_ensure_sdk_client", AsyncMock(return_value=mock_client)):
            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            events: List[StreamEvent] = []
            async for evt in client.stream_message(message="hello"):
                events.append(evt)

        assert len(events) == 1
        assert events[0].event_type == "task"
        assert events[0].is_final


class TestEnsureSdkClient:
    """Lazy resolution of the AgentCard and SDK client."""

    @pytest.mark.asyncio
    async def test_ensure_sdk_client_resolves_card(self):
        from a2a.client import ClientFactory

        fake_card = _make_agent_card()
        fake_sdk_client = MagicMock()

        with patch("agno.client.a2a.client.A2ACardResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.get_agent_card = AsyncMock(return_value=fake_card)
            mock_resolver_cls.return_value = mock_resolver

            with patch.object(ClientFactory, "create", return_value=fake_sdk_client) as mock_create:
                client = A2AClient("http://localhost:7777", timeout=15, protocol="json-rpc")
                got = await client._ensure_sdk_client()

        assert got is fake_sdk_client
        # Card resolution used the configured timeout.
        mock_resolver.get_agent_card.assert_awaited_once()
        # ClientFactory.create was called with the resolved card.
        mock_create.assert_called_once_with(fake_card)
        # Subsequent calls do not re-resolve.
        again = await client._ensure_sdk_client()
        assert again is fake_sdk_client
        assert mock_resolver.get_agent_card.await_count == 1

    @pytest.mark.asyncio
    async def test_ensure_sdk_client_card_failure(self):
        with patch("agno.client.a2a.client.A2ACardResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.get_agent_card = AsyncMock(side_effect=ConnectionError("nope"))
            mock_resolver_cls.return_value = mock_resolver

            client = A2AClient("http://localhost:7777", protocol="json-rpc")
            with pytest.raises(RemoteServerUnavailableError) as exc_info:
                await client._ensure_sdk_client()
            # The original error message is preserved on the exception chain.
            assert isinstance(exc_info.value.original_error, ConnectionError)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for x in items:
        yield x
