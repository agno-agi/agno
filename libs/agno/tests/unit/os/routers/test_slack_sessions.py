from unittest.mock import AsyncMock, Mock

import pytest
from slack_sdk.errors import SlackApiError

from agno.os.interfaces.slack.utils import SlackSessions


def _api_error(code: str) -> SlackApiError:
    return SlackApiError("failed", Mock(data={"ok": False, "error": code}))


@pytest.mark.asyncio
async def test_agents_api_is_used_first():
    client = AsyncMock()
    sessions = SlackSessions(client)

    await sessions.set_status("C1", "1.1", "processing", legacy_text="Thinking...")
    await sessions.set_status("C1", "1.1", "active")

    assert [c.kwargs["status"] for c in client.agents_sessions_setStatus.await_args_list] == ["processing", "active"]
    client.assistant_threads_setStatus.assert_not_awaited()
    assert sessions.legacy is False


@pytest.mark.asyncio
async def test_falls_back_to_assistant_api_and_stays_there():
    client = AsyncMock()
    client.agents_sessions_setStatus = AsyncMock(side_effect=_api_error("missing_scope"))
    sessions = SlackSessions(client, loading_messages=["one", "two"])

    await sessions.set_status("C1", "1.1", "processing", legacy_text="Thinking...")
    await sessions.set_status("C1", "1.1", "suspended")
    await sessions.set_status("C1", "1.1", "active")

    assert sessions.legacy is True
    # Only the first call tried the agent API; the rest went straight to the assistant API
    assert client.agents_sessions_setStatus.await_count == 1
    calls = client.assistant_threads_setStatus.await_args_list
    assert calls[0].kwargs["status"] == "Thinking..."
    assert calls[0].kwargs["loading_messages"] == ["one", "two"]
    assert calls[1].kwargs["status"] == ""
    assert "loading_messages" not in calls[1].kwargs
    assert calls[2].kwargs["status"] == ""


@pytest.mark.asyncio
async def test_transient_error_does_not_flip_to_legacy():
    client = AsyncMock()
    client.agents_sessions_setStatus = AsyncMock(side_effect=_api_error("ratelimited"))
    sessions = SlackSessions(client)

    await sessions.set_status("C1", "1.1", "active")

    assert sessions.legacy is False
    client.assistant_threads_setStatus.assert_not_awaited()


@pytest.mark.asyncio
async def test_assistant_event_pins_legacy_api():
    client = AsyncMock()
    sessions = SlackSessions(client)
    sessions.use_assistant_api()

    await sessions.set_status("C1", "1.1", "processing", legacy_text="Working")
    await sessions.rename("C1", "1.1", "Title")

    client.agents_sessions_setStatus.assert_not_awaited()
    client.agents_sessions_rename.assert_not_awaited()
    client.assistant_threads_setStatus.assert_awaited_once()
    client.assistant_threads_setTitle.assert_awaited_once_with(channel_id="C1", thread_ts="1.1", title="Title")


@pytest.mark.asyncio
async def test_rename_falls_back():
    client = AsyncMock()
    client.agents_sessions_rename = AsyncMock(side_effect=_api_error("unknown_method"))
    sessions = SlackSessions(client)

    await sessions.rename("C1", "1.1", "Title")

    client.assistant_threads_setTitle.assert_awaited_once_with(channel_id="C1", thread_ts="1.1", title="Title")
    assert sessions.legacy is True


@pytest.mark.asyncio
async def test_suggested_prompts_skip_empty_and_omit_thread_on_agent_view():
    client = AsyncMock()
    sessions = SlackSessions(client)

    await sessions.set_suggested_prompts("C1", [])
    client.assistant_threads_setSuggestedPrompts.assert_not_awaited()

    # On the Agent view prompts belong to the Messages tab; a thread would be rejected
    prompts = [{"title": "Help", "message": "help me"}]
    await sessions.set_suggested_prompts("C1", prompts, thread_ts="1.1")
    client.assistant_threads_setSuggestedPrompts.assert_awaited_once_with(channel_id="C1", prompts=prompts)


@pytest.mark.asyncio
async def test_suggested_prompts_keep_thread_on_assistant_view():
    client = AsyncMock()
    sessions = SlackSessions(client)
    sessions.use_assistant_api()

    prompts = [{"title": "Help", "message": "help me"}]
    await sessions.set_suggested_prompts("C1", prompts, thread_ts="1.1")
    client.assistant_threads_setSuggestedPrompts.assert_awaited_once_with(
        channel_id="C1", prompts=prompts, thread_ts="1.1"
    )


@pytest.mark.asyncio
async def test_errors_are_swallowed():
    client = AsyncMock()
    client.agents_sessions_setStatus = AsyncMock(side_effect=RuntimeError("boom"))
    client.assistant_threads_setSuggestedPrompts = AsyncMock(side_effect=RuntimeError("boom"))
    sessions = SlackSessions(client)

    await sessions.set_status("C1", "1.1", "active")
    await sessions.set_suggested_prompts("C1", [{"title": "a", "message": "a"}])
