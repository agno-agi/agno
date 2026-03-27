"""Unit tests for A2AClient."""

from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any
from datetime import datetime

import pytest
from httpx import HTTPStatusError, Request, Response

from agno.client.a2a import (
    A2AClient,
    StreamEvent,
    TaskResult,
)
from agno.exceptions import RemoteServerUnavailableError
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
                metadata={}
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
            task1 = Task(id="t1", context_id="ctx-1", status=TaskStatus(state="working", timestamp=ts), history=[], artifacts=[], kind="task", metadata={})
            event1 = TaskStatusUpdateEvent(task_id="t1", context_id="ctx-1", status=TaskStatus(state="working", timestamp=ts), final=False, kind="status-update")
            
            # 2. Content update (via task history expansion in SDK)
            msg_p1 = Message(role=Role.agent, message_id="m1", parts=[Part(root=TextPart(text="Hello"))])
            task2 = task1.model_copy()
            task2.history = [msg_p1]
            event2 = None # Just task update
            
            # 3. Content update 2
            msg_p2 = Message(role=Role.agent, message_id="m2", parts=[Part(root=TextPart(text="Hello World"))])
            task3 = task1.model_copy()
            task3.history = [msg_p2]
            event3 = None
            
            # 4. Completed
            task4 = task3.model_copy()
            task4.status = TaskStatus(state="completed", timestamp=ts)
            event4 = TaskStatusUpdateEvent(task_id="t1", context_id="ctx-1", status=task4.status, final=True, kind="status-update")
            
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

    def test_get_agent_card_success(self):
        """Test get_agent_card (sync)."""
        with patch("agno.client.a2a.client.get_default_sync_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "name": "Test Agent",
                "capabilities": ["streaming"],
                "version": "1.0",
                "url": "http://localhost:7777"
            }
            mock_cli = MagicMock()
            mock_cli.get.return_value = mock_response
            mock_get_client.return_value = mock_cli
            
            client = A2AClient("http://localhost:7777")
            card = client.get_agent_card()
            
            assert card is not None
            assert card.name == "Test Agent"
            assert "streaming" in card.capabilities
