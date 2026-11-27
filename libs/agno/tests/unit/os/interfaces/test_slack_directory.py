"""authorize_senders runs an agent, team or workflow as each Slack sender's AgentOS directory user."""

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, UserDirectory
from agno.os.authz import Authorization
from agno.os.interfaces.slack import Slack, security
from agno.os.interfaces.slack.handlers import handle_message

from .conftest import (
    BOT_USER_ID,
    SIGNING_SECRET,
    TOKEN,
    make_async_client_mock,
    make_ctx,
    make_event_body,
    make_event_context,
)

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
SECRET = "slack-directory-secret-at-least-32-bytes"
SENDER = "slack:T123:U123"
DENIED = security._PERMISSION_MESSAGE.format(scope="agents:agent-1:run")


def _app(
    tmp_path,
    default_role: bool = True,
    user_isolation: bool = False,
    member_scopes=("agents:run",),
    **directory_kwargs,
):
    """An AgentOS app with a user directory and a "member" role that may run agent-1."""
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256")
    auth.define_role("member", list(member_scopes), default=default_role)
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    directory = UserDirectory(**directory_kwargs) if directory_kwargs else True
    agent_os = AgentOS(
        id="slack-directory",
        db=db,
        agents=[Agent(id="agent-1")],
        authorization=auth,
        user_directory=directory,
        user_isolation=user_isolation,
        telemetry=False,
    )
    return agent_os.get_app()


async def _users_info(user):
    """A users.info response naming user a full member of T123."""
    return {"ok": True, "user": {"id": user, "team_id": "T123"}}


def _member(**fields):
    """A users.info response for U123, a full member of T123, with fields overridden."""
    member = {"id": "U123", "team_id": "T123", "profile": {"email": "test@example.com", "display_name": "Test User"}}
    member.update(fields)
    return {"ok": True, "user": member}


async def _send(ctx, member=None, **body_kwargs):
    """Handle one Slack message; users.info returns member, or raises it when it is an exception."""
    client = make_async_client_mock()
    if isinstance(member, Exception):
        client.users_info = AsyncMock(side_effect=member)
    elif member is not None:
        client.users_info = AsyncMock(return_value=member)
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(**body_kwargs), client, ctx)
    return run_event, client


def _ephemeral(client):
    """The text of the last ephemeral, None when there was none."""
    return client.chat_postEphemeral.call_args.kwargs["text"] if client.chat_postEphemeral.called else None


@pytest.mark.asyncio
async def test_without_authorize_senders_nothing_changes(tmp_path):
    app = _app(tmp_path)
    run_event, client = await _send(make_ctx().bind(app))
    assert run_event.called and run_event.call_args.args[0].authority is None
    assert await app.state.user_store.acount() == 0


@pytest.mark.asyncio
async def test_sender_is_created_once_with_the_default_role_and_runs_as_it(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True).bind(app)
    run_event, _ = await _send(ctx)
    event_context = run_event.call_args.args[0]
    assert (event_context.user_id, event_context.authority is not None) == (SENDER, True)
    user = await app.state.user_store.aget(SENDER)
    assert (user["name"], user["email"]) == ("Test User", None)
    assert await app.state.role_store.aroles_of(SENDER) == ["member"]
    await _send(ctx, ts="1700000000.000200", event_id="Ev2")
    assert await app.state.user_store.acount() == 1


@pytest.mark.asyncio
async def test_without_a_default_role_the_sender_waits_for_an_assigned_role(tmp_path):
    app = _app(tmp_path, default_role=False)
    ctx = make_ctx(authorize_senders=True).bind(app)
    run_event, client = await _send(ctx)
    assert not run_event.called and _ephemeral(client) == DENIED
    assert await app.state.user_store.aget(SENDER) is not None
    await app.state.role_store.aassign(SENDER, "member")
    run_event, _ = await _send(ctx, ts="1700000000.000200", event_id="Ev2")
    assert run_event.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolve, confirmed, principal, email",
    [
        (True, True, "test@example.com", "test@example.com"),
        (True, False, SENDER, None),
        (False, True, SENDER, "test@example.com"),
    ],
    ids=["resolved", "unconfirmed", "label-only"],
)
async def test_confirmed_email_names_the_user_only_under_resolve_user_identity(
    tmp_path, resolve, confirmed, principal, email
):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, resolve_user_identity=resolve).bind(app)
    run_event, _ = await _send(ctx, member=_member(is_email_confirmed=confirmed))
    assert run_event.call_args.args[0].user_id == principal
    # Without resolve_user_identity the confirmed email only labels the user in /users
    assert (await app.state.user_store.aget(principal))["email"] == email


@pytest.mark.asyncio
async def test_guest_starts_disabled_and_another_organizations_member_is_refused(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, resolve_user_identity=True).bind(app)
    guest = _member(is_email_confirmed=True, is_restricted=True)
    run_event, client = await _send(ctx, member=guest)
    # A guest's email never names a user, and the user waits for an admin to turn it on
    assert not run_event.called and _ephemeral(client) == security._DISABLED_MESSAGE
    assert (await app.state.user_store.aget(SENDER))["disabled"] is True
    await app.state.user_store.aset_disabled(SENDER, False)
    run_event, _ = await _send(ctx, member=guest, ts="1700000000.000200", event_id="Ev2")
    assert run_event.call_args.args[0].user_id == SENDER
    run_event, client = await _send(
        ctx, member=_member(team_id="T_OTHER"), user="U_OUT", ts="1700000000.000300", event_id="Ev3"
    )
    assert not run_event.called and _ephemeral(client) == security._NOT_A_MEMBER_MESSAGE
    assert await app.state.user_store.acount() == 1


@pytest.mark.asyncio
async def test_disabled_sender_is_refused(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True).bind(app)
    await _send(ctx)
    await app.state.user_store.aset_disabled(SENDER, True)
    run_event, client = await _send(ctx, ts="1700000000.000200", event_id="Ev2")
    assert not run_event.called and _ephemeral(client) == security._DISABLED_MESSAGE


@pytest.mark.asyncio
async def test_bot_user_without_a_bot_id_is_never_a_directory_user(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True).bind(app)
    run_event, _ = await _send(ctx, member=_member(is_bot=True))
    assert not run_event.called
    assert await app.state.user_store.acount() == 0


@pytest.mark.asyncio
async def test_another_app_is_refused_under_authorize_senders(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, client = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    # Only people run under authorize_senders, so an app is refused, in the thread since it cannot see an ephemeral
    assert not run_event.called
    assert client.chat_postMessage.call_args.kwargs["text"] == security._APP_NOT_ALLOWED_MESSAGE
    client = make_async_client_mock()
    # A webhook post names only its own bot id; bots.info names the app, which is refused the same way
    client.bots_info = AsyncMock(
        return_value={"ok": True, "bot": {"id": "B_HOOK", "app_id": "A_OTHER", "name": "hook"}}
    )
    body = make_event_body(user="", bot_id="B_HOOK", subtype="bot_message", ts="1700000000.000200", event_id="Ev2")
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(body, client, ctx)
    assert not run_event.called
    # An app never becomes a user in the directory
    assert await app.state.user_store.acount() == 0


@pytest.mark.asyncio
async def test_another_app_without_authorize_senders_runs_unchecked(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(respond_to_other_apps=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    # Without authorize_senders every app is answered, and its run has no authority of its own
    assert run_event.called and run_event.call_args.args[0].authority is None
    assert await app.state.user_store.acount() == 0
    ctx = make_ctx(respond_to_other_apps=False).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER", ts="1700000000.000300", event_id="Ev3")
    assert not run_event.called


@pytest.mark.asyncio
async def test_users_mapping_is_ignored_under_authorize_senders(tmp_path):
    app = _app(tmp_path)
    await app.state.role_store.aassign("alice", "member")
    agent = Agent(id="agent-1")
    slack = Slack(
        agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, authorize_senders=True, users={"U123": "alice"}
    )
    with patch("agno.os.app.log_warning") as warning:
        AgentOS(id="slack-directory", agents=[agent], interfaces=[slack], telemetry=False).get_app()
    assert any("Slack(users=...) is ignored under authorize_senders" in call.args[0] for call in warning.call_args_list)
    ctx = make_ctx(authorize_senders=True, users={"U123": "alice"}).bind(app)
    run_event, _ = await _send(ctx)
    # The sender runs as their own directory user, not as the principal users= maps them to
    assert run_event.call_args.args[0].user_id == SENDER
    assert await app.state.user_store.aget(SENDER) is not None
    run_event, _ = await _send(ctx, user="U_UNMAPPED", ts="1700000000.000200", event_id="Ev2")
    assert run_event.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        {"user": "U123"},
        {"user": "", "bot_id": "B_HOOK", "subtype": "bot_message"},
        {"user": "U_BOT", "bot_id": "B_OTHER"},
    ],
    ids=["person", "webhook", "bot-user"],
)
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_sender_slack_cannot_name_is_refused(tmp_path, event, fail_closed):
    app = _app(tmp_path, fail_closed=fail_closed)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    client = make_async_client_mock()
    client.users_info = AsyncMock(side_effect=RuntimeError("ratelimited"))
    client.bots_info = AsyncMock(side_effect=RuntimeError("ratelimited"))
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(**event), client, ctx)
    # Who sent it cannot be established, so fail_closed does not apply, as for an unverifiable token
    assert not run_event.called
    if event["user"] == "U123":
        assert _ephemeral(client) == security._SLACK_UNAVAILABLE_MESSAGE
    assert await app.state.user_store.acount() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_unreachable_directory_follows_fail_closed_and_roles_still_decide(tmp_path, fail_closed):
    app = _app(tmp_path, fail_closed=fail_closed)
    ctx = make_ctx(authorize_senders=True, resolve_user_identity=True).bind(app)
    await _send(ctx)
    with patch.object(app.state.user_store, "aget", AsyncMock(side_effect=RuntimeError("db down"))):
        run_event, client = await _send(ctx, ts="1700000000.000200", event_id="Ev2")
        # A newcomer whose Slack email is unconfirmed
        new_run_event, new_client = await _send(ctx, user="U_NEW", ts="1700000000.000300", event_id="Ev3")
    if fail_closed:
        assert not run_event.called and not new_run_event.called
        assert _ephemeral(client) == security._DIRECTORY_UNAVAILABLE_MESSAGE
    else:
        # Failing open skips only creating the user: the sender's own user and roles still decide
        assert run_event.call_args.args[0].user_id == SENDER
        assert run_event.call_args.args[0].authority is not None
        # A newcomer is no directory user, so no default role applies, and never runs as their unconfirmed email
        assert not new_run_event.called and _ephemeral(new_client) == DENIED


@pytest.mark.asyncio
@pytest.mark.parametrize("user_isolation", [False, True])
async def test_stop_follows_the_cancel_rule(tmp_path, user_isolation):
    app = _app(tmp_path, user_isolation=user_isolation)
    ctx = make_ctx(authorize_senders=True).bind(app)
    await _send(ctx)
    await app.state.role_store.aassign("slack:T123:U_OTHER", "member")
    run = make_event_context(owner="U123", user_id=SENDER, team_id="T123", entity_id="agent-1")
    client = make_async_client_mock()
    client.users_info = AsyncMock(side_effect=_users_info)
    # Anyone who may run the agent may stop a run, and only its owner under user isolation, as a cancel over HTTP
    assert await security.can_stop(ctx, "U_OTHER", run, client) is not user_isolation
    assert await security.can_stop(ctx, "U123", run, client)
    await app.state.user_store.aset_disabled(SENDER, True)
    assert not await security.can_stop(ctx, "U123", run, client)


@pytest.mark.asyncio
@pytest.mark.parametrize("user_isolation", [False, True])
async def test_owner_stops_a_run_before_it_is_authorized(tmp_path, user_isolation):
    app = _app(tmp_path, user_isolation=user_isolation)
    ctx = make_ctx(authorize_senders=True).bind(app)
    await _send(ctx)
    # Until the run is authorized it carries the raw Slack id and no authority, which is no directory user
    run = make_event_context(owner="U123", user_id="U123", team_id="T123", entity_id="agent-1")
    client = make_async_client_mock()
    client.users_info = AsyncMock(side_effect=_users_info)
    assert await security.can_stop(ctx, "U123", run, client)
    assert not await security.can_stop(ctx, "U_OTHER", run, client)


@pytest.mark.asyncio
async def test_sender_message_reads_the_directory_once(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True).bind(app)
    with patch.object(app.state.user_store, "ais_disabled", AsyncMock(return_value=False)) as disabled:
        run_event, _ = await _send(ctx)
    # Creating the user reads its row, so its disabled switch is not read a second time, as over HTTP
    assert run_event.called and disabled.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_guest_never_runs_when_creating_their_user_fails(tmp_path, fail_closed):
    app = _app(tmp_path, fail_closed=fail_closed)
    ctx = make_ctx(authorize_senders=True).bind(app)
    guest = _member(is_restricted=True)
    with patch.object(app.state.user_store, "aset_disabled", AsyncMock(side_effect=RuntimeError("db down"))):
        run_event, _ = await _send(ctx, member=guest)
    assert not run_event.called
    run_event, _ = await _send(ctx, member=guest, ts="1700000000.000200", event_id="Ev2")
    # The user was created disabled, so the default role never applies before an admin turns it on
    assert not run_event.called and (await app.state.user_store.aget(SENDER))["disabled"] is True


@pytest.mark.asyncio
async def test_owner_stops_their_run_without_a_slack_lookup(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True).bind(app)
    await _send(ctx)
    run = make_event_context(owner="U123", user_id=SENDER, team_id="T123", entity_id="agent-1")
    client = make_async_client_mock()
    client.users_info = AsyncMock(side_effect=RuntimeError("ratelimited"))
    # A new interface has no cached lookup, as after a restart
    assert await security.can_stop(make_ctx(authorize_senders=True).bind(app), "U123", run, client)
    assert not await security.can_stop(make_ctx(authorize_senders=True).bind(app), "U_OTHER", run, client)


@pytest.mark.asyncio
async def test_app_is_told_once_per_thread(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    _, first = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_UNMAPPED")
    _, second = await _send(
        ctx,
        user="",
        bot_id="B_OTHER",
        app_id="A_UNMAPPED",
        ts="1700000000.000200",
        thread_ts="1700000000.000100",
        event_id="Ev2",
    )
    # An app that answers every message would otherwise trade refusals with the bot
    assert first.chat_postMessage.call_args.kwargs["text"] == security._APP_NOT_ALLOWED_MESSAGE
    assert not second.chat_postMessage.called


@pytest.mark.asyncio
async def test_app_is_told_only_when_it_mentions_the_bot(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True, reply_to_mentions_only=False).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", BOT_USER_ID
    channel = {"user": "", "bot_id": "B_OTHER", "app_id": "A_UNMAPPED", "channel_type": "channel"}
    mention = f"<@{BOT_USER_ID}> summarize PR #123"
    notified, quiet = await _send(ctx, text="PR #123 opened", **channel)
    mentioned, told = await _send(ctx, text=mention, ts="1700000000.000300", event_id="Ev3", **channel)
    # A notification is refused without a word; a message to the bot is told why
    assert not notified.called and not quiet.chat_postMessage.called
    assert not mentioned.called and told.chat_postMessage.call_args.kwargs["text"] == security._APP_NOT_ALLOWED_MESSAGE


def test_agent_os_without_slack_starts_without_the_slack_dependencies(tmp_path, monkeypatch):
    import sys

    # An install without the Slack extra: the Slack interface cannot be imported
    for name in list(sys.modules):
        if name.startswith("agno.os.interfaces.slack"):
            monkeypatch.delitem(sys.modules, name, raising=False)
        elif name.split(".")[0] in ("slack_sdk", "slack_bolt"):
            monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "slack_sdk", None)
    agent_os = AgentOS(
        id="no-slack",
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        agents=[Agent(id="agent-1")],
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
        telemetry=False,
    )
    assert agent_os.get_app() is not None


@pytest.mark.parametrize("has_db", [True, False], ids=["db", "no-db"])
def test_authorize_senders_without_a_database_warns_once(tmp_path, has_db):
    agent = Agent(id="agent-1")
    interfaces = [
        Slack(agent=agent, prefix=prefix, token=TOKEN, signing_secret=SIGNING_SECRET, authorize_senders=True)
        for prefix in ("/slack/a", "/slack/b")
    ]
    # A user directory is optional; only a missing database leaves senders unchecked
    db = {"db": SqliteDb(db_file=str(tmp_path / "os.db"))} if has_db else {}
    with patch("agno.os.app.log_warning") as warning:
        AgentOS(id="slack-directory", agents=[agent], interfaces=interfaces, telemetry=False, **db).get_app()
    warnings = [call.args[0] for call in warning.call_args_list]
    assert sum("Slack(authorize_senders=True) runs each sender" in text for text in warnings) == (0 if has_db else 1)
