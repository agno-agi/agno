from unittest.mock import AsyncMock

import pytest

from agno.os.interfaces.slack.helpers import extract_event_context, resolve_slack_bot

# -- extract_event_context sender identity --


def test_extract_event_context_both_user_and_bot_id_preserved():
    ctx = extract_event_context({"text": "hi", "channel": "C1", "user": "U123", "bot_id": "B456", "ts": "111"})
    assert ctx["user"] == "U123"
    assert ctx["bot_id"] == "B456"


def test_extract_event_context_bot_only_message():
    ctx = extract_event_context({"text": "hi", "channel": "C1", "bot_id": "B456", "ts": "111"})
    assert ctx["user"] == ""
    assert ctx["bot_id"] == "B456"


def test_extract_event_context_human_message():
    ctx = extract_event_context({"text": "hi", "channel": "C1", "user": "U123", "ts": "111"})
    assert ctx["user"] == "U123"
    assert ctx["bot_id"] == ""


def test_extract_event_context_empty_when_neither():
    ctx = extract_event_context({"text": "hi", "channel": "C1", "ts": "111"})
    assert ctx["user"] == ""
    assert ctx["bot_id"] == ""


# -- resolve_slack_bot --


@pytest.mark.asyncio
async def test_resolve_slack_bot_resolves_name():
    mock_client = AsyncMock()
    mock_client.bots_info = AsyncMock(return_value={"bot": {"name": "My Bot"}})

    resolved_id, display_name = await resolve_slack_bot(mock_client, "B123456")

    mock_client.bots_info.assert_awaited_once_with(bot="B123456")
    assert resolved_id == "B123456"
    assert display_name == "My Bot"


@pytest.mark.asyncio
async def test_resolve_slack_bot_fallback_on_error():
    mock_client = AsyncMock()
    mock_client.bots_info = AsyncMock(side_effect=Exception("API error"))

    resolved_id, display_name = await resolve_slack_bot(mock_client, "B123456")

    assert resolved_id == "B123456"
    assert display_name is None
