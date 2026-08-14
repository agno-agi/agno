"""Unit tests for A2AClient."""

from datetime import datetime
from typing import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from agno.client.a2a import (
    A2AClient,
)
from agno.client.a2a.utils import map_stream_events_to_run_events
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunStartedEvent
from a2a.types import (
    Task,
    TaskStatus,
    Message,
    TextPart,
    TaskStatusUpdateEvent,
    Role,
    Part,
)


# Mock wrapper for async iterator
async def mock_async_iter(items):
    for item in items:
        yield item


class TestA2AClient:
    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Test successful message send."""
        with patch("a2a.client.ClientFactory.connect") as mock_connect:
            mock_sdk_client = MagicMock()
            mock_connect.return_value = mock_sdk_client

            # Create a valid Task object
            # Note: A2ABaseModel / Pydantic usage
            # We assume minimal valid construction
            status = TaskStatus(state="completed", timestamp=datetime.now().isoformat())
            msg = Message(role=Role.agent, message_id="msg-1", parts=[Part(root=TextPart(text="The answer is 4"))])
            task = Task(
                id="task-123",
                context_id="ctx-456",
                status=status,
                history=[msg],
                artifacts=[],
                kind="task",
                metadata={},
            )

            mock_sdk_client.send_message.side_effect = lambda *args, **kwargs: mock_async_iter([(task, None)])

            client = A2AClient("http://localhost:7777")
            result = await client.send_message("What is 2 + 2?")

            assert result.task_id == "task-123"
            assert result.content == "The answer is 4"
            assert result.is_completed
            mock_connect.assert_called_once()
            mock_sdk_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_message_success(self):
        """Test successful message streaming."""
        with patch("a2a.client.ClientFactory.connect") as mock_connect:
            mock_sdk_client = MagicMock()
            mock_connect.return_value = mock_sdk_client

            # Prepare sequence of events
            ts = datetime.now().isoformat()
            # 1. Task working
            task1 = Task(
                id="t1",
                context_id="ctx-1",
                status=TaskStatus(state="working", timestamp=ts),
                history=[],
                artifacts=[],
                kind="task",
                metadata={},
            )
            event1 = TaskStatusUpdateEvent(
                task_id="t1",
                context_id="ctx-1",
                status=TaskStatus(state="working", timestamp=ts),
                final=False,
                kind="status-update",
            )

            # 2. Content update (via task history expansion in SDK)
            msg_p1 = Message(role=Role.agent, message_id="m1", parts=[Part(root=TextPart(text="Hello"))])
            task2 = task1.model_copy()
            task2.history = [msg_p1]
            event2 = None  # Just task update

            # 3. Content update 2
            msg_p2 = Message(role=Role.agent, message_id="m2", parts=[Part(root=TextPart(text="Hello World"))])
            task3 = task1.model_copy()
            task3.history = [msg_p2]
            event3 = None

            # 4. Completed
            task4 = task3.model_copy()
            task4.status = TaskStatus(state="completed", timestamp=ts)
            event4 = TaskStatusUpdateEvent(
                task_id="t1", context_id="ctx-1", status=task4.status, final=True, kind="status-update"
            )

            items = [
                (task1, event1),
                (task2, event2),
                (task3, event3),
                (task4, event4),
            ]

            mock_sdk_client.send_message.side_effect = lambda *args, **kwargs: mock_async_iter(items)

            client = A2AClient("http://localhost:7777")
            events = []
            async for e in client.stream_message("Hi"):
                events.append(e)

            # We expect content events for deltas "Hello" and " World"
            # And status events

            content_events = [e for e in events if e.is_content]
            assert len(content_events) == 2
            assert content_events[0].content == "Hello"
            assert content_events[1].content == " World"

            completed_events = [e for e in events if e.is_completed]
            assert completed_events
            assert completed_events[0].is_final

    @pytest.mark.asyncio
    async def test_stream_message_terminal_status_update_carries_metadata(self):
        """Regression test: out-of-band metadata rides the final=True status-update
        (the A2A spec's terminal event). map_stream_events_to_run_events must read
        event.metadata off that terminal event and forward it onto RunCompletedEvent,
        rather than dropping it. (Port of #9224 to the a2a-sdk ClientFactory path.)"""
        with patch("a2a.client.ClientFactory.connect") as mock_connect:
            mock_sdk_client = MagicMock()
            mock_connect.return_value = mock_sdk_client

            ts = datetime.now().isoformat()

            # 1. Task working (non-final status-update)
            task1 = Task(
                id="t1",
                context_id="ctx-1",
                status=TaskStatus(state="working", timestamp=ts),
                history=[],
                artifacts=[],
                kind="task",
                metadata={},
            )
            event1 = TaskStatusUpdateEvent(
                task_id="t1",
                context_id="ctx-1",
                status=TaskStatus(state="working", timestamp=ts),
                final=False,
                kind="status-update",
            )

            # 2. Content update via task history expansion
            msg_p1 = Message(role=Role.agent, message_id="m1", parts=[Part(root=TextPart(text="Hello"))])
            task2 = task1.model_copy()
            task2.history = [msg_p1]
            event2 = None  # task-only update

            # 3. Terminal status-update carrying out-of-band metadata
            task3 = task2.model_copy()
            event3 = TaskStatusUpdateEvent(
                task_id="t1",
                context_id="ctx-1",
                status=TaskStatus(state="completed", timestamp=ts),
                final=True,
                kind="status-update",
                metadata={"refetch_model": True},
            )

            items = [
                (task1, event1),
                (task2, event2),
                (task3, event3),
            ]

            mock_sdk_client.send_message.side_effect = lambda *args, **kwargs: mock_async_iter(items)

            client = A2AClient("http://localhost:7777")

            async def raw_stream() -> AsyncIterator:
                async for event in client.stream_message(message="Hello"):
                    yield event

            run_events = [
                event async for event in map_stream_events_to_run_events(raw_stream(), agent_id="agent-1")
            ]

            assert [type(e) for e in run_events] == [
                RunStartedEvent,
                RunContentEvent,
                RunCompletedEvent,
            ]
            completed = run_events[-1]
            assert completed.content == "Hello"
            assert completed.metadata == {"refetch_model": True}

    @pytest.mark.asyncio
    async def test_get_sdk_client_card_resolution_failure(self):
        """Test that _get_sdk_client raises RemoteServerUnavailableError with original_error preserved.

        When the A2A server is unreachable or the agent card cannot be resolved,
        ClientFactory.connect() raises an exception. _get_sdk_client should catch
        that and re-raise as RemoteServerUnavailableError, preserving the original
        exception so callers can inspect the root cause (e.g. connection refused,
        card resolution failure, DNS failure).
        """
        from agno.exceptions import RemoteServerUnavailableError

        original_exc = ConnectionError("Failed to resolve agent card: connection refused")

        with patch("a2a.client.ClientFactory.connect", side_effect=original_exc):
            client = A2AClient("http://localhost:7777")

            with pytest.raises(RemoteServerUnavailableError) as exc_info:
                await client._get_sdk_client()

            assert exc_info.value.base_url == "http://localhost:7777"
            assert exc_info.value.original_error is original_exc

    def test_get_agent_card_success(self):
        """Test get_agent_card (sync)."""
        with patch("agno.client.a2a.client.get_default_sync_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "name": "Test Agent",
                "capabilities": ["streaming"],
                "version": "1.0",
                "url": "http://localhost:7777",
            }
            mock_cli = MagicMock()
            mock_cli.get.return_value = mock_response
            mock_get_client.return_value = mock_cli

            client = A2AClient("http://localhost:7777")
            card = client.get_agent_card()

            assert card is not None
            assert card.name == "Test Agent"
            assert "streaming" in card.capabilities
