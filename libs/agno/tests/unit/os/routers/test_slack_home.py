from unittest.mock import AsyncMock

import pytest

from agno.os.interfaces.slack.home import AGNO_OS_URL, HomeTab, build_home_view


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
async def test_publish_calls_views_publish_for_the_user():
    client = AsyncMock()
    await HomeTab(lambda: client, "Bot", "desc").publish("U1")
    kwargs = client.views_publish.await_args.kwargs
    assert kwargs["user_id"] == "U1"
    assert kwargs["view"]["type"] == "home"


@pytest.mark.asyncio
async def test_publish_failure_is_logged_not_raised():
    client = AsyncMock()
    client.views_publish = AsyncMock(side_effect=RuntimeError("boom"))
    await HomeTab(lambda: client, "Bot").publish("U1")
