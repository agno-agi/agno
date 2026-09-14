from unittest.mock import AsyncMock

import pytest

from agno.os.interfaces.slack.event_handler import AGNO_OS_URL, SlackEventHandler, build_home_view
from agno.os.interfaces.slack.helpers import BotNameResolver


def _handler(client: AsyncMock, description: str = "") -> SlackEventHandler:
    return SlackEventHandler(
        token="xoxb-test",
        ssl=None,
        entity=AsyncMock(),
        entity_id="agent-1",
        entity_name="Bot",
        entity_type="agent",
        entity_description=description or None,
        bot_name_resolver=BotNameResolver(),
        reply_to_mentions_only=False,
        resolve_user_identity=False,
        respond_to_other_apps=False,
        loading_text="Thinking...",
        loading_messages=None,
        task_display_mode="plan",
        buffer_size=100,
        client=client,
    )


def test_home_view_shows_name_description_and_agentos_link():
    view = build_home_view("Research Companion", "Answers research questions with sources.")
    assert view["type"] == "home"
    assert view["blocks"][0] == {"type": "header", "text": {"type": "plain_text", "text": "Research Companion"}}
    assert view["blocks"][1]["text"]["text"] == "Answers research questions with sources."
    assert AGNO_OS_URL in view["blocks"][-1]["elements"][0]["text"]
    assert "Powered by" in view["blocks"][-1]["elements"][0]["text"]


def test_home_view_without_description():
    view = build_home_view("Bot")
    assert [b["type"] for b in view["blocks"]] == ["header", "context"]


@pytest.mark.asyncio
async def test_home_tab_open_publishes_for_the_user():
    client = AsyncMock()
    await _handler(client, "desc").handle_home_opened({"tab": "home", "user": "U1"})
    kwargs = client.views_publish.await_args.kwargs
    assert kwargs["user_id"] == "U1"
    assert kwargs["view"]["blocks"][1]["text"]["text"] == "desc"


@pytest.mark.asyncio
async def test_publish_failure_is_logged_not_raised():
    client = AsyncMock()
    client.views_publish = AsyncMock(side_effect=RuntimeError("boom"))
    await _handler(client).publish_home("U1")
