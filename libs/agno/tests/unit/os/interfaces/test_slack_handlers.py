import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.os.interfaces.slack.context import event_context_from_run, new_event_context
from agno.os.interfaces.slack.handlers import (
    _NOT_LINKED_MESSAGE,
    handle_app_home_opened,
    handle_assistant_thread_started,
    handle_message,
    handle_session_stopped,
    should_process,
)
from agno.os.interfaces.slack.helpers import DEFAULT_SUGGESTED_PROMPTS, slack_run_id

from .conftest import (
    BOT_ID,
    BOT_USER_ID,
    make_agent_mock,
    make_async_client_mock,
    make_ctx,
    make_event_body,
    make_stop_body,
    slack_error,
)

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
JWT_KEY = "slack-handlers-jwt-verification-key-at-least-32-chars"


# -- should_process --


@pytest.mark.parametrize(
    "event, expected",
    [
        ({"type": "message", "user": "U1", "text": "hi"}, True),
        # "Also send to channel" replies are answered
        ({"type": "message", "subtype": "thread_broadcast", "user": "U1", "text": "hi"}, True),
        ({"type": "message", "subtype": "message_changed", "user": "U1"}, False),
        ({"type": "message", "bot_id": BOT_ID, "text": "own"}, False),
        ({"type": "message", "user": BOT_USER_ID, "text": "own"}, False),
        ({"type": "message", "bot_id": "B_OTHER", "text": "other app"}, False),
        ({"type": "message", "subtype": "bot_message", "text": "legacy bot"}, False),
        ({"type": "message", "subtype": "file_share", "user": "U1", "text": "a file"}, True),
    ],
)
def test_should_process(event, expected):
    ctx = make_ctx()
    ctx.bot_id, ctx.bot_user_id = BOT_ID, BOT_USER_ID
    assert should_process(event, ctx) is expected


def test_should_process_logs_why_an_event_is_skipped():
    ctx = make_ctx()
    ctx.bot_id, ctx.bot_user_id = BOT_ID, BOT_USER_ID
    with patch("agno.os.interfaces.slack.handlers.log_debug") as debug:
        assert should_process({"type": "message", "bot_id": "B_OTHER", "text": "other app"}, ctx) is False
    debug.assert_called_once()
    assert debug.call_args.args[0].startswith("Slack event skipped: another app's message")


def test_should_process_other_apps_when_opted_in():
    ctx = make_ctx(respond_to_other_apps=True)
    ctx.bot_id, ctx.bot_user_id = BOT_ID, BOT_USER_ID
    assert should_process({"type": "message", "bot_id": "B_OTHER", "text": "hi"}, ctx) is True


def test_should_process_skips_bot_messages_while_own_ids_are_unknown():
    # auth.test failed, so the bot's own reply cannot be told apart from another app's
    ctx = make_ctx(respond_to_other_apps=True)
    assert should_process({"type": "message", "bot_id": "B_SELF_UNKNOWN", "text": "my own reply"}, ctx) is False
    assert should_process({"type": "message", "user": "U1", "text": "a person"}, ctx) is True


# -- slack_run_id --


def test_slack_run_id_is_one_id_per_message_and_instance():
    first = slack_run_id("T1", "agent-1", "C1", "1.0")
    assert first == slack_run_id("T1", "agent-1", "C1", "1.0")
    assert first != slack_run_id("T1", "agent-1", "C1", "2.0")
    assert first != slack_run_id("T1", "agent-1", "C2", "1.0")
    assert first != slack_run_id("T1", "agent-2", "C1", "1.0")


def test_app_mention_and_message_for_one_message_share_a_run_id():
    ctx = make_ctx()
    mention = new_event_context(make_event_body(event_type="app_mention", event_id="Ev1"), ctx)
    message = new_event_context(make_event_body(event_type="message", event_id="Ev2"), ctx)
    assert mention.run_id == message.run_id


# -- handle_message --


@pytest.mark.asyncio
async def test_handle_message_registers_resolves_and_runs():
    ctx = make_ctx()
    client = make_async_client_mock()
    body = make_event_body(
        text="hi &amp; bye <@U_SELF>", thread_ts="1699999999.000100", event_type="app_mention", channel_type="channel"
    )
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(body, client, ctx)
    event_context, run_client, run_ctx = run_event.call_args.args
    assert (run_client, run_ctx) == (client, ctx)
    assert event_context.text == "hi & bye Test User"
    assert event_context.session_id == "agent-1:C123:1699999999.000100"
    assert event_context.user_id == event_context.owner == "U123"
    assert event_context.channel_name == "general"
    assert event_context.event is body["event"]
    assert ctx.runs.find_run(event_context.run_id) is event_context


@pytest.mark.asyncio
async def test_handle_message_resolves_user_identity_with_cache():
    ctx = make_ctx(resolve_user_identity=True)
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(event_id="Ev1"), client, ctx)
        await handle_message(make_event_body(event_id="Ev2", ts="1700000000.000200"), client, ctx)
    assert run_event.call_args.args[0].user_id == "test@example.com"
    assert run_event.call_args.args[0].display_name == "Test User"
    # The sender is looked up once; the other users.info call names the bot
    assert [call.kwargs["user"] for call in client.users_info.await_args_list] == [BOT_USER_ID, "U123"]


@pytest.mark.asyncio
async def test_handle_message_names_sender_without_changing_user_id():
    ctx = make_ctx()
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(event_id="Ev1"), client, ctx)
        await handle_message(make_event_body(event_id="Ev2", ts="1700000000.000200"), client, ctx)
    event_context = run_event.call_args.args[0]
    assert event_context.display_name == "Test User"
    assert event_context.user_id == event_context.owner == "U123"
    # The sender is looked up once; the other users.info call names the bot
    assert [call.kwargs["user"] for call in client.users_info.await_args_list] == [BOT_USER_ID, "U123"]


@pytest.mark.asyncio
async def test_handle_message_user_token_post_resolves_the_human():
    # A user-token post carries both the human's user id and the app's bot id
    ctx = make_ctx(resolve_user_identity=True, respond_to_other_apps=True)
    ctx.bot_id, ctx.bot_user_id = BOT_ID, BOT_USER_ID
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(bot_id="B_OTHER"), client, ctx)
    event_context = run_event.call_args.args[0]
    assert (event_context.user_id, event_context.display_name) == ("test@example.com", "Test User")
    assert event_context.owner == "U123"
    client.bots_info.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,name,calls", [("missing_scope", None, 1), ("ratelimited", "Test User", 2)])
async def test_handle_message_unknown_sender_name_is_retried_only_after_a_transient_error(code, name, calls):
    ctx = make_ctx()
    client = make_async_client_mock()
    names = client.users_info.return_value
    failures = [slack_error(code)]

    async def users_info(user):
        if user == "U123" and failures:
            raise failures.pop()
        return names

    client.users_info = AsyncMock(side_effect=users_info)
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(event_id="Ev1"), client, ctx)
        await handle_message(make_event_body(event_id="Ev2", ts="1700000000.000200"), client, ctx)
    # A missing scope is kept for the TTL; a rate limit is looked up again on the next message
    assert run_event.call_args.args[0].display_name == name
    assert [call.kwargs["user"] for call in client.users_info.await_args_list].count("U123") == calls


@pytest.mark.asyncio
async def test_handle_message_legacy_session_probe_is_cached():
    agent = make_agent_mock()
    agent.aget_session = AsyncMock(return_value={"session_id": "agent-1:1699999999.000100"})
    ctx = make_ctx(agent=agent)
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        for i, ts in enumerate(["1700000000.000100", "1700000000.000200"]):
            body = make_event_body(event_id=f"Ev{i}", ts=ts, thread_ts="1699999999.000100")
            await handle_message(body, make_async_client_mock(), ctx)
    # Legacy key without channel_id, probed once per thread
    assert run_event.call_args.args[0].session_id == "agent-1:1699999999.000100"
    assert agent.aget_session.await_count == 1


@pytest.mark.asyncio
async def test_handle_message_remote_entity_skips_the_legacy_probe():
    remote = make_agent_mock()
    del remote.aget_session
    ctx = make_ctx(agent=remote)
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(thread_ts="1.0"), make_async_client_mock(), ctx)
    assert run_event.call_args.args[0].session_id == "agent-1:C123:1.0"


@pytest.mark.asyncio
async def test_handle_message_unmapped_user_gets_ephemeral_and_no_run():
    ctx = make_ctx(users={"U_OTHER": "alice"})
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _NOT_LINKED_MESSAGE
    run_id = new_event_context(make_event_body(), ctx).run_id
    assert ctx.runs.find_run(run_id) is None


@pytest.mark.asyncio
async def test_handle_message_unmapped_user_gets_one_ephemeral_for_the_mention_and_message_pair():
    ctx = make_ctx(users={"U_OTHER": "alice"})
    client = make_async_client_mock()

    async def slow_ephemeral(**kwargs):
        await asyncio.sleep(0.01)

    client.chat_postEphemeral = AsyncMock(side_effect=slow_ephemeral)
    mention = make_event_body(event_type="app_mention", event_id="Ev1")
    message = make_event_body(event_type="message", event_id="Ev2")
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await asyncio.gather(handle_message(mention, client, ctx), handle_message(message, client, ctx))
    assert not run_event.called
    assert client.chat_postEphemeral.await_count == 1


@pytest.mark.asyncio
async def test_handle_message_stopped_before_the_other_delivery_does_not_run():
    ctx = make_ctx()
    ctx.runs.record_stop(new_event_context(make_event_body(event_type="app_mention", event_id="Ev1"), ctx).run_id)
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(event_type="message", event_id="Ev2"), make_async_client_mock(), ctx)
    assert not run_event.called


@pytest.mark.asyncio
async def test_handle_message_mapped_user_runs_as_principal():
    ctx = make_ctx(users={"U123": "alice"})
    authority = object()
    with (
        patch("agno.os.interfaces.slack.security.resolve_principal_authorization", AsyncMock(return_value=authority)),
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(), make_async_client_mock(), ctx)
    event_context = run_event.call_args.args[0]
    assert (event_context.user_id, event_context.owner, event_context.authority) == ("alice", "U123", authority)


@pytest.mark.asyncio
async def test_handle_message_refused_principal_gets_ephemeral():
    ctx = make_ctx(users={"U123": "alice"})
    client = make_async_client_mock()
    refused = AsyncMock(side_effect=PermissionError("User is disabled"))
    with (
        patch("agno.os.interfaces.slack.security.resolve_principal_authorization", refused),
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == "Not run: User is disabled"


@pytest.mark.asyncio
async def test_handle_message_super_agent_authorizes_through_company():
    company = AsyncMock()
    company.authorize = AsyncMock(return_value=None)
    ctx = make_ctx(users={"U123": "alice"})
    ctx.company = company
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), make_async_client_mock(), ctx)
    company.authorize.assert_awaited_once_with(None, "alice", "agent-1")
    # With AgentOS authorization off there is no authority, and the message still runs as the principal
    assert run_event.call_args.args[0].user_id == "alice"


@pytest.mark.asyncio
async def test_handle_message_super_agent_without_users_is_refused_under_a_jwt_middleware():
    from agno.agent import Agent
    from agno.os import AgentOS
    from agno.os.middleware.jwt import JWTMiddleware

    app = AgentOS(id="slack-handlers", agents=[Agent(id="agent-1")], telemetry=False).get_app()
    # The documented pattern adds the middleware after get_app(), so the app flag is unset
    app.add_middleware(JWTMiddleware, verification_keys=[JWT_KEY], algorithm="HS256", authorization=True)
    ctx = make_ctx().bind(app)
    ctx.company = AsyncMock()
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _NOT_LINKED_MESSAGE


@pytest.mark.asyncio
async def test_handle_message_skips_channel_message_when_mentions_only():
    ctx = make_ctx()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(channel_type="channel"), make_async_client_mock(), ctx)
    assert not run_event.called


# -- Prompts and title --


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_app_home_opened_messages_tab_sets_prompts_without_thread_ts(streaming):
    ctx = make_ctx(streaming=streaming)
    client = make_async_client_mock()
    await handle_app_home_opened(
        {"event": {"type": "app_home_opened", "tab": "messages", "channel": "D1", "user": "U1"}}, client, ctx
    )
    client.assistant_threads_setSuggestedPrompts.assert_awaited_once_with(
        channel_id="D1", prompts=DEFAULT_SUGGESTED_PROMPTS
    )
    assert "Search the web" not in str(DEFAULT_SUGGESTED_PROMPTS)


@pytest.mark.asyncio
async def test_app_home_opened_refused_prompts_warn_once_not_per_open():
    from slack_sdk.errors import SlackApiError

    ctx = make_ctx()
    client = make_async_client_mock()
    client.assistant_threads_setSuggestedPrompts = AsyncMock(
        side_effect=SlackApiError("not_agent_app", {"ok": False, "error": "not_agent_app"})
    )
    opened = {"event": {"type": "app_home_opened", "tab": "messages", "channel": "D1", "user": "U1"}}
    with (
        patch("agno.os.interfaces.slack.handlers.log_warning") as warning,
        patch("agno.os.interfaces.slack.helpers.log_error") as error,
    ):
        # Each request gets its own bound copy of the context, as the listener builds it
        for _ in range(3):
            await handle_app_home_opened(opened, client, ctx.bind(None))
    assert warning.call_count == 1
    assert not error.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        {"type": "app_home_opened", "tab": "home", "channel": "D1"},
        {"type": "app_home_opened", "tab": "messages", "channel": "D1", "thread_ts": "1.0"},
    ],
)
async def test_app_home_opened_other_tabs_and_threads_set_no_prompts(event):
    client = make_async_client_mock()
    await handle_app_home_opened({"event": event}, client, make_ctx())
    assert not client.assistant_threads_setSuggestedPrompts.called


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_assistant_thread_started_sets_custom_prompts(streaming):
    prompts = [{"title": "Plan", "message": "Plan my week"}]
    ctx = make_ctx(streaming=streaming, suggested_prompts=prompts)
    client = make_async_client_mock()
    await handle_assistant_thread_started(
        {"event": {"assistant_thread": {"channel_id": "D1", "thread_ts": "1.0"}}}, client, ctx
    )
    client.assistant_threads_setSuggestedPrompts.assert_awaited_once_with(
        channel_id="D1", prompts=prompts, thread_ts="1.0"
    )


@pytest.mark.asyncio
async def test_assistant_thread_started_marks_the_thread_for_its_title():
    ctx = make_ctx()
    await handle_assistant_thread_started(
        {"event": {"assistant_thread": {"channel_id": "C123", "thread_ts": "5.0"}}}, make_async_client_mock(), ctx
    )
    # The first message takes the mark, so a later one keeps the title the user may have changed
    assert ctx.runs.take_thread_started("C123", "5.0") is True
    assert ctx.runs.take_thread_started("C123", "5.0") is False


@pytest.mark.asyncio
async def test_assistant_thread_started_without_channel_returns_early():
    client = make_async_client_mock()
    await handle_assistant_thread_started({"event": {"assistant_thread": {"thread_ts": "1.0"}}}, client, make_ctx())
    assert not client.assistant_threads_setSuggestedPrompts.called


# -- Stop --


@pytest.mark.asyncio
async def test_session_stopped_hands_the_stop_to_the_executor():
    ctx = make_ctx()
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.stop_runs", new_callable=AsyncMock) as stop_runs:
        await handle_session_stopped(make_stop_body(streaming_message_ts=["1.5"]), client, ctx)
        await handle_session_stopped(make_stop_body(), client, ctx)
    assert stop_runs.call_args_list[0].args == (ctx, client, "U123", "C123", "1700000000.000100", ["1.5"])
    assert stop_runs.call_args_list[1].args[5] == []


# -- event_context_from_run --


def _run(user_id: str, session_id: str = "agent-1:C9:3.0"):
    return SimpleNamespace(run_id="run-1", session_id=session_id, user_id=user_id)


@pytest.mark.asyncio
async def test_event_context_from_run_owner_from_the_card_first():
    ctx = make_ctx(users={"U_MAPPED": "alice"})
    event_context = await event_context_from_run(ctx, _run("alice"), owner="U_CARD")
    assert (event_context.owner, event_context.channel, event_context.thread_ts, event_context.user_id) == (
        "U_CARD",
        "C9",
        "3.0",
        "alice",
    )


@pytest.mark.asyncio
async def test_event_context_from_run_owner_from_mapped_users():
    event_context = await event_context_from_run(make_ctx(users={"U_MAPPED": "alice"}), _run("alice"))
    assert event_context.owner == "U_MAPPED"


@pytest.mark.asyncio
async def test_event_context_from_run_owner_by_email():
    client = make_async_client_mock()
    client.users_lookupByEmail = AsyncMock(return_value={"user": {"id": "U_EMAIL"}})
    event_context = await event_context_from_run(
        make_ctx(resolve_user_identity=True), _run("test@example.com"), client=client
    )
    assert event_context.owner == "U_EMAIL"


@pytest.mark.asyncio
async def test_event_context_from_run_plain_slack_id_and_legacy_session():
    event_context = await event_context_from_run(make_ctx(), _run("U123", session_id="agent-1:3.0"), channel="C1")
    assert (event_context.owner, event_context.channel, event_context.thread_ts) == ("U123", "C1", "3.0")
