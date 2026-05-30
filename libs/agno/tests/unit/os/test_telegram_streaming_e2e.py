"""
Comprehensive E2E tests for Telegram interface streaming, events, and edge cases.

Tests cover:
- Dispatch table event handling for all event types
- StreamState lifecycle (build_display_html, send_or_edit, flush, finalize)
- BotState dedup, session persistence (timestamp IDs, DB recovery), /new command
- Router: streaming path, sync path, error handling, group/DM differences
- Edge cases: empty content, overflow, terminal events, team vs agent prefixing
"""

import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _install_fake_telebot():
    telebot = types.ModuleType("telebot")
    telebot_async = types.ModuleType("telebot.async_telebot")
    telebot_apihelper = types.ModuleType("telebot.apihelper")

    class AsyncTeleBot:
        def __init__(self, token=None):
            self.token = token

    class TeleBot:
        def __init__(self, token=None):
            self.token = token

    class ApiTelegramException(Exception):
        pass

    telebot.TeleBot = TeleBot
    telebot_async.AsyncTeleBot = AsyncTeleBot
    telebot_apihelper.ApiTelegramException = ApiTelegramException
    sys.modules.setdefault("telebot", telebot)
    sys.modules.setdefault("telebot.async_telebot", telebot_async)
    sys.modules.setdefault("telebot.apihelper", telebot_apihelper)


_install_fake_telebot()

ROUTER_MODULE = "agno.os.interfaces.telegram.router"
SECURITY_MODULE = "agno.os.interfaces.telegram.security"


@pytest.fixture(autouse=True)
def _bypass_webhook_security():
    with patch(f"{ROUTER_MODULE}.validate_webhook_secret_token", return_value=True):
        yield


def _build_telegram_client(
    agent=None,
    team=None,
    workflow=None,
    stream=False,
    show_reasoning=False,
    error_message=None,
    token=None,
):
    from fastapi import APIRouter

    from agno.os.interfaces.telegram.router import attach_routes

    router = APIRouter(prefix="/telegram")
    kwargs: dict = dict(
        router=router,
        agent=agent,
        team=team,
        workflow=workflow,
        streaming=stream,
        show_reasoning=show_reasoning,
    )
    if token is not None:
        kwargs["token"] = token
    if error_message is not None:
        kwargs["error_message"] = error_message
    attach_routes(**kwargs)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _text_update(text="Hello", chat_id=12345, user_id=67890, msg_id=100, chat_type="private"):
    update = {
        "update_id": int(time.monotonic() * 1000) % 1000000,
        "message": {
            "message_id": msg_id,
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
        },
    }
    return update


def _group_update(text="Hello", chat_id=99999, user_id=67890, msg_id=200, reply_to_msg_id=None):
    msg = {
        "message_id": msg_id,
        "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "text": text,
    }
    if reply_to_msg_id:
        msg["reply_to_message"] = {
            "message_id": reply_to_msg_id,
            "from": {"id": 11111, "is_bot": True, "first_name": "Bot"},
        }
    return {"update_id": int(time.monotonic() * 1000) % 1000000 + 1, "message": msg}


# =============================================================================
# StreamState unit tests
# =============================================================================


class TestStreamState:
    def test_build_display_html_empty(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        assert state.build_display_html() == ""

    def test_build_display_html_status_only(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        state.add_status("Reasoning...")
        html = state.build_display_html()
        assert "<blockquote>" in html
        assert "Reasoning..." in html

    def test_build_display_html_content_only(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        state.accumulated_content = "Hello **world**"
        html = state.build_display_html()
        assert "<b>world</b>" in html
        assert "<blockquote" not in html

    def test_build_display_html_status_and_content(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        state.add_status("Used web_search")
        state.accumulated_content = "Result"
        html = state.build_display_html()
        assert "<blockquote>" in html
        assert "Used web_search" in html
        assert "Result" in html

    def test_close_pending_statuses(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        state.add_status("Using tool...")
        state.add_status("Already done")
        state.add_status("Reasoning...")
        state.close_pending_statuses()
        assert state.status_lines == ["Using tool", "Already done", "Reasoning"]

    def test_update_status_replaces_matching_line(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        state.add_status("Using web_search...")
        state.add_status("Reasoning...")
        state.replace_status("Using web_search...", "Used web_search")
        assert state.status_lines == ["Used web_search", "Reasoning..."]

    def test_html_escaping_in_status(self):
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        state.add_status("Using <dangerous>&tool...")
        html = state.build_display_html()
        assert "&lt;dangerous&gt;&amp;tool..." in html
        assert "<dangerous>" not in html

    @pytest.mark.asyncio
    async def test_send_or_edit_skips_empty_html(self):
        from agno.os.interfaces.telegram.state import StreamState

        bot = AsyncMock()
        state = StreamState(
            bot=bot,
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        await state.send_or_edit("")
        await state.send_or_edit("   ")
        bot.send_message.assert_not_called()
        bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_or_edit_creates_message_first_time(self):
        from agno.os.interfaces.telegram.state import StreamState

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
        state = StreamState(
            bot=bot,
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        await state.send_or_edit("<b>hello</b>")
        assert state.sent_message_id == 42
        bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_or_edit_edits_on_second_call(self):
        from agno.os.interfaces.telegram.state import StreamState

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
        state = StreamState(
            bot=bot,
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        await state.send_or_edit("<b>hello</b>")
        await state.send_or_edit("<b>hello world</b>")
        assert bot.edit_message_text.call_count == 1

    @pytest.mark.asyncio
    async def test_finalize_with_no_content_does_nothing(self):
        from agno.os.interfaces.telegram.state import StreamState

        bot = AsyncMock()
        state = StreamState(
            bot=bot,
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        await state.finalize()
        bot.send_message.assert_not_called()


# =============================================================================
# BotState unit tests
# =============================================================================


class TestBotState:
    def _make_bot_state(self):
        from agno.os.interfaces.telegram.state import BotState, build_session_store_config

        agent = AsyncMock()
        agent.db = None
        cfg = build_session_store_config(agent, "agent")
        return BotState(bot=AsyncMock(), session_config=cfg)

    def test_dedup_rejects_duplicate(self):
        bot_state = self._make_bot_state()
        assert bot_state.is_duplicate_update(1) is False
        assert bot_state.is_duplicate_update(1) is True

    def test_dedup_allows_different_ids(self):
        bot_state = self._make_bot_state()
        assert bot_state.is_duplicate_update(1) is False
        assert bot_state.is_duplicate_update(2) is False

    @pytest.mark.asyncio
    async def test_find_latest_session_returns_none_when_empty(self):
        from agno.db.base import AsyncBaseDb
        from agno.os.interfaces.telegram.state import build_session_store_config, find_latest_session_id

        mock_db = AsyncMock(spec=AsyncBaseDb)
        mock_db.get_sessions.return_value = ([], 0)
        agent = AsyncMock()
        agent.db = mock_db
        cfg = build_session_store_config(agent, "agent")

        result = await find_latest_session_id(cfg, "user1", "test-agent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_latest_session_returns_session_id(self):
        from agno.db.base import AsyncBaseDb
        from agno.os.interfaces.telegram.state import build_session_store_config, find_latest_session_id

        mock_db = AsyncMock(spec=AsyncBaseDb)
        mock_db.get_sessions.return_value = ([{"session_id": "tg:12345:abc123"}], 1)
        agent = AsyncMock()
        agent.db = mock_db
        cfg = build_session_store_config(agent, "agent")

        result = await find_latest_session_id(cfg, "user1", "test-agent", session_scope="tg:12345")
        assert result == "tg:12345:abc123"
        mock_db.get_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_find_latest_session_no_cache(self):
        from agno.db.base import AsyncBaseDb
        from agno.os.interfaces.telegram.state import build_session_store_config, find_latest_session_id

        mock_db = AsyncMock(spec=AsyncBaseDb)
        mock_db.get_sessions.return_value = ([{"session_id": "tg:12345:abc123"}], 1)
        agent = AsyncMock()
        agent.db = mock_db
        cfg = build_session_store_config(agent, "agent")

        # Each call queries DB — no caching
        await find_latest_session_id(cfg, "user1", "test-agent")
        await find_latest_session_id(cfg, "user1", "test-agent")
        assert mock_db.get_sessions.await_count == 2


# =============================================================================
# Event dispatch tests
# =============================================================================


class TestEventDispatch:
    @pytest.mark.asyncio
    async def test_normalize_strips_team_prefix(self):
        from agno.os.interfaces.telegram.events import _strip_team_prefix

        assert _strip_team_prefix("TeamRunContent") == "RunContent"
        assert _strip_team_prefix("RunContent") == "RunContent"
        assert _strip_team_prefix("TeamToolCallStarted") == "ToolCallStarted"

    @pytest.mark.asyncio
    async def test_all_run_events_have_handlers(self):
        from agno.agent import RunEvent
        from agno.os.interfaces.telegram.events import HANDLERS

        # Key events that must have handlers
        required = [
            RunEvent.reasoning_started,
            RunEvent.reasoning_completed,
            RunEvent.tool_call_started,
            RunEvent.tool_call_completed,
            RunEvent.tool_call_error,
            RunEvent.run_content,
            RunEvent.run_intermediate_content,
            RunEvent.run_completed,
            RunEvent.run_error,
            RunEvent.run_cancelled,
            RunEvent.memory_update_started,
            RunEvent.memory_update_completed,
        ]
        for ev in required:
            assert ev.value in HANDLERS, f"Missing handler for {ev.value}"

    @pytest.mark.asyncio
    async def test_all_workflow_events_have_handlers(self):
        from agno.os.interfaces.telegram.events import HANDLERS
        from agno.run.workflow import WorkflowRunEvent

        required = [
            WorkflowRunEvent.workflow_started,
            WorkflowRunEvent.workflow_completed,
            WorkflowRunEvent.workflow_error,
            WorkflowRunEvent.workflow_cancelled,
            WorkflowRunEvent.step_started,
            WorkflowRunEvent.step_completed,
            WorkflowRunEvent.step_error,
            WorkflowRunEvent.step_output,
            WorkflowRunEvent.workflow_agent_started,
            WorkflowRunEvent.workflow_agent_completed,
            WorkflowRunEvent.loop_execution_started,
            WorkflowRunEvent.loop_iteration_started,
            WorkflowRunEvent.loop_iteration_completed,
            WorkflowRunEvent.loop_execution_completed,
            WorkflowRunEvent.parallel_execution_started,
            WorkflowRunEvent.parallel_execution_completed,
            WorkflowRunEvent.condition_execution_started,
            WorkflowRunEvent.condition_execution_completed,
            WorkflowRunEvent.router_execution_started,
            WorkflowRunEvent.router_execution_completed,
            WorkflowRunEvent.steps_execution_started,
            WorkflowRunEvent.steps_execution_completed,
        ]
        for ev in required:
            assert ev.value in HANDLERS, f"Missing handler for {ev.value}"

    @pytest.mark.asyncio
    async def test_workflow_suppression(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="workflow",
            error_message="err",
        )
        chunk = MagicMock()
        chunk.content = "should be suppressed"
        # RunContent is suppressed in workflow mode
        result = await dispatch_stream_event("RunContent", chunk, state)
        assert result is False
        assert state.accumulated_content == ""  # content was suppressed

    @pytest.mark.asyncio
    async def test_team_intermediate_content_suppressed(self):
        """For teams, intermediate content should be ignored (team leader consolidates)."""
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="team",
            error_message="err",
        )
        chunk = MagicMock()
        chunk.content = "intermediate from member"
        chunk.event = "RunIntermediateContent"
        result = await dispatch_stream_event("RunIntermediateContent", chunk, state)
        assert result is False
        assert state.accumulated_content == ""  # suppressed for teams

    @pytest.mark.asyncio
    async def test_agent_intermediate_content_accumulated(self):
        """For non-team agents, intermediate content should be accumulated."""
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        chunk = MagicMock()
        chunk.content = "some content"
        result = await dispatch_stream_event("RunIntermediateContent", chunk, state)
        assert result is False
        assert state.accumulated_content == "some content"

    @pytest.mark.asyncio
    async def test_run_error_is_terminal(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="Error occurred",
        )
        chunk = MagicMock()
        chunk.content = "something went wrong"
        result = await dispatch_stream_event("RunError", chunk, state)
        assert result is True  # terminal
        assert state.accumulated_content != ""
        assert state.accumulated_content == "Error occurred"

    @pytest.mark.asyncio
    async def test_run_cancelled_is_terminal(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="Error occurred",
        )
        chunk = MagicMock()
        chunk.content = "cancelled"
        result = await dispatch_stream_event("RunCancelled", chunk, state)
        assert result is True

    @pytest.mark.asyncio
    async def test_workflow_error_is_terminal(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="workflow",
            error_message="WF Error",
        )
        chunk = MagicMock()
        result = await dispatch_stream_event("WorkflowError", chunk, state)
        assert result is True
        assert state.accumulated_content != ""

    @pytest.mark.asyncio
    async def test_unknown_event_ignored(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        chunk = MagicMock()
        result = await dispatch_stream_event("SomeUnknownEvent", chunk, state)
        assert result is False

    @pytest.mark.asyncio
    async def test_tool_call_team_agent_prefix(self):
        """In team mode, tool call status should include [AgentName] prefix."""
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        state = StreamState(
            bot=bot,
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="team",
            error_message="err",
        )
        chunk = MagicMock()
        tool = MagicMock()
        tool.tool_name = "web_search"
        tool.tool_args = None
        chunk.tool = tool
        chunk.agent_name = "Researcher"
        await dispatch_stream_event("ToolCallStarted", chunk, state)
        assert any("Researcher: web_search..." in line for line in state.status_lines)

    @pytest.mark.asyncio
    async def test_memory_update_lifecycle(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        state = StreamState(
            bot=bot,
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="err",
        )
        chunk = MagicMock()
        await dispatch_stream_event("MemoryUpdateStarted", chunk, state)
        assert "Updating memory..." in state.status_lines

        await dispatch_stream_event("MemoryUpdateCompleted", chunk, state)
        assert "Updating memory" in state.status_lines
        assert "Updating memory..." not in state.status_lines

    @pytest.mark.asyncio
    async def test_step_output_sets_workflow_final_content(self):
        from agno.os.interfaces.telegram.events import dispatch_stream_event
        from agno.os.interfaces.telegram.state import StreamState

        state = StreamState(
            bot=AsyncMock(),
            chat_id=1,
            reply_to=None,
            message_thread_id=None,
            entity_type="workflow",
            error_message="err",
        )
        chunk = MagicMock()
        chunk.content = "final output from step"
        await dispatch_stream_event("StepOutput", chunk, state)
        assert state.workflow_final_content == "final output from step"


# =============================================================================
# Router integration tests
# =============================================================================


class TestRouterStreaming:
    """Test the full streaming path through the router."""

    def test_agent_streaming_full_lifecycle(self, monkeypatch):
        """Agent streaming: reasoning -> tool call -> content -> completed."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.agent import RunOutput

        events = []
        for ev_name, attrs in [
            ("ReasoningStarted", {}),
            ("ReasoningCompleted", {}),
            ("ToolCallStarted", {"tool": MagicMock(tool_name="calculator", tool_args=None), "agent_name": None}),
            ("ToolCallCompleted", {"tool": MagicMock(tool_name="calculator", tool_args=None)}),
            ("RunContent", {"content": "The answer is 42"}),
        ]:
            ev = MagicMock()
            ev.event = ev_name
            for k, v in attrs.items():
                setattr(ev, k, v)
            events.append(ev)

        run_output = MagicMock(spec=RunOutput)
        run_output.status = "COMPLETED"
        run_output.content = "The answer is 42"
        run_output.reasoning_content = None
        run_output.images = None
        run_output.audio = None
        run_output.videos = None
        run_output.files = None

        async def fake_stream(*args, **kwargs):
            for ev in events:
                yield ev
            yield run_output

        agent = AsyncMock()
        agent.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, stream=True)
            resp = client.post("/telegram/webhook", json=_text_update("what is 6*7"))

        assert resp.status_code == 200
        # Verify stream was called correctly
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_events"] is True
        assert call_kwargs["yield_run_output"] is True

        # Verify status lines were sent (may be via send, edit, or draft)
        all_calls = mock_bot.send_message.call_args_list + mock_bot.edit_message_text.call_args_list
        all_text = " ".join(str(c) for c in all_calls)
        assert "Reasoning" in all_text
        assert "calculator" in all_text

    def test_workflow_streaming_lifecycle(self, monkeypatch):
        """Workflow streaming: step started -> completed -> workflow completed."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        events = []
        for ev_name, attrs in [
            ("WorkflowStarted", {"workflow_name": "analysis"}),
            ("StepStarted", {"step_name": "gather_data"}),
            ("StepCompleted", {"step_name": "gather_data", "content": "data gathered"}),
            ("WorkflowCompleted", {"content": "Analysis complete"}),
        ]:
            ev = MagicMock()
            ev.event = ev_name
            for k, v in attrs.items():
                setattr(ev, k, v)
            events.append(ev)

        async def fake_stream(*args, **kwargs):
            for ev in events:
                yield ev

        workflow = AsyncMock()
        workflow.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(workflow=workflow, stream=True)
            resp = client.post("/telegram/webhook", json=_text_update("run analysis"))

        assert resp.status_code == 200
        workflow.arun.assert_called_once()
        # Workflows don't get yield_run_output
        call_kwargs = workflow.arun.call_args[1]
        assert "yield_run_output" not in call_kwargs

    def test_sync_path_sends_content(self, monkeypatch):
        """Non-streaming agent returns content that gets sent."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Hello from agent"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, stream=False)
            resp = client.post("/telegram/webhook", json=_text_update("Hello"))

        assert resp.status_code == 200
        # Content should be sent via send_chunked -> send_html
        send_calls = mock_bot.send_message.call_args_list
        any_content = any("Hello from agent" in str(c) for c in send_calls)
        assert any_content, f"Expected 'Hello from agent' in: {send_calls}"

    def test_sync_path_error_response(self, monkeypatch):
        """Non-streaming agent returning ERROR status sends error message."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "ERROR"
        mock_response.content = "Internal failure"

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, stream=False, error_message="Custom error")
            resp = client.post("/telegram/webhook", json=_text_update("fail"))

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        any_error = any("Custom error" in str(c) for c in send_calls)
        assert any_error, f"Expected 'Custom error' in: {send_calls}"

    def test_sync_path_none_response(self, monkeypatch):
        """Non-streaming agent returning None sends error message."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=None)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, stream=False)
            resp = client.post("/telegram/webhook", json=_text_update("fail"))

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        any_error = any("error" in str(c).lower() for c in send_calls)
        assert any_error

    def test_show_reasoning_sends_reasoning_block(self, monkeypatch):
        """show_reasoning=True should send reasoning content."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Answer"
        mock_response.reasoning_content = "I thought about this carefully..."
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, stream=False, show_reasoning=True)
            resp = client.post("/telegram/webhook", json=_text_update("think"))

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        any_reasoning = any("I thought about this carefully" in str(c) for c in send_calls)
        assert any_reasoning


# =============================================================================
# Edge cases and production scenarios
# =============================================================================


class TestEdgeCases:
    def test_bot_message_ignored(self, monkeypatch):
        """Messages from bots should be silently ignored."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        mock_bot = AsyncMock()

        update = {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": True, "first_name": "OtherBot"},
                "chat": {"id": 12345, "type": "private"},
                "text": "Hello",
            },
        }

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=update)

        assert resp.status_code == 200
        agent.arun.assert_not_called()

    def test_no_message_returns_ignored(self, monkeypatch):
        """Webhook with no message field returns 'ignored'."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json={"update_id": 1})

        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_duplicate_update_id_rejected(self, monkeypatch):
        """Same update_id should be deduped."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=MagicMock(status="COMPLETED", content="ok"))
        mock_bot = AsyncMock()

        update = _text_update("Hello")
        update["update_id"] = 42

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp1 = client.post("/telegram/webhook", json=update)
            resp2 = client.post("/telegram/webhook", json=update)

        assert resp1.json()["status"] == "processing"
        assert resp2.json()["status"] == "duplicate"

    def test_invalid_secret_token_returns_403(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")

        agent = AsyncMock()
        mock_bot = AsyncMock()

        with (
            patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot),
            patch(f"{ROUTER_MODULE}.validate_webhook_secret_token", return_value=False),
        ):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json=_text_update("Hello"),
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            )

        assert resp.status_code == 403

    def test_commands_start_help_new(self, monkeypatch):
        """All three commands should be handled without calling agent."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)

            for cmd in ["/start", "/help", "/new"]:
                update = _text_update(cmd)
                update["update_id"] = hash(cmd) % 1000000
                resp = client.post("/telegram/webhook", json=update)
                assert resp.status_code == 200

        # Agent should never be called for commands
        agent.arun.assert_not_called()

    def test_status_endpoint(self, monkeypatch):
        """GET /status should return available."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")

        agent = AsyncMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.get("/telegram/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "available"
