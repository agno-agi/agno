"""authorize_senders runs an agent, team or workflow as each Slack sender's AgentOS directory user."""

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, UserDirectory
from agno.os.authz import Authorization
from agno.os.authz.run_context import restore_authorization
from agno.os.interfaces.slack import Slack, security
from agno.os.interfaces.slack.handlers import handle_message
from agno.run.authorization import InterfaceAuthorization

from .conftest import (
    BOT_USER_ID,
    SIGNING_SECRET,
    TOKEN,
    make_async_client_mock,
    make_ctx,
    make_event_body,
    make_event_context,
    make_service_account,
)

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
SECRET = "slack-directory-secret-at-least-32-bytes"
SENDER = "slack:T123:U123"
DENIED = security._PERMISSION_MESSAGE.format(scope="agents:agent-1:run")


def _app(
    tmp_path,
    default_role: bool = True,
    audit: bool = False,
    user_isolation: bool = False,
    member_scopes=("agents:run",),
    **directory_kwargs,
):
    """An AgentOS app with a user directory and a "member" role that may run agent-1."""
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audit=audit)
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
    # Without Slack(service_account=...) the run is not capped by the bot
    assert not isinstance(event_context.authority, InterfaceAuthorization)
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
async def test_another_app_not_in_allowed_apps_is_refused_under_authorize_senders(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, client = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    # As users= refuses a sender it does not map, an app allowed_apps= does not list is refused, in the thread
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
@pytest.mark.parametrize("authorize_senders", [True, False], ids=["authorize-senders", "without-authorize-senders"])
async def test_allowed_apps_run_as_their_service_accounts_in_any_mode(tmp_path, authorize_senders):
    app = _app(tmp_path)
    make_service_account(app, "reviewbot", ["agents:agent-1:run"])
    ctx = make_ctx(
        authorize_senders=authorize_senders, respond_to_other_apps=True, allowed_apps={"A_OTHER": "reviewbot"}
    ).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    assert run_event.call_args.args[0].user_id == "sa:reviewbot"
    run_event, client = await _send(
        ctx, user="", bot_id="B_OTHER", app_id="A_UNLISTED", ts="1700000000.000200", event_id="Ev2"
    )
    assert not run_event.called
    assert client.chat_postMessage.call_args.kwargs["text"] == security._APP_NOT_ALLOWED_MESSAGE
    # A post Slack cannot say is a person's or an app's is refused, as an unverifiable sender
    run_event, client = await _send(
        ctx,
        member=RuntimeError("ratelimited"),
        user="U_BOT",
        bot_id="B_OTHER",
        app_id="A_UNLISTED",
        ts="1700000000.000300",
        event_id="Ev3",
    )
    assert not run_event.called and _ephemeral(client) == security._SLACK_UNAVAILABLE_MESSAGE
    assert await app.state.user_store.acount() == 0


@pytest.mark.asyncio
async def test_another_app_without_authorize_senders_or_allowed_apps_runs_unchecked(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(respond_to_other_apps=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    # Without authorize_senders or allowed_apps= every app is answered, and its run has no authority of its own
    assert run_event.called and run_event.call_args.args[0].authority is None
    assert await app.state.user_store.acount() == 0
    ctx = make_ctx(respond_to_other_apps=False).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER", ts="1700000000.000300", event_id="Ev3")
    assert not run_event.called


@pytest.mark.asyncio
async def test_app_users_maps_keeps_users_with_allowed_apps(tmp_path):
    app = _app(tmp_path)
    await app.state.role_store.aassign("alice", "member")
    ctx = make_ctx(respond_to_other_apps=True, users={"B_OTHER": "alice"}, allowed_apps={"A_ELSE": "reviewbot"}).bind(
        app
    )
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    # An app whose bot id users= maps runs as that mapping
    assert run_event.call_args.args[0].user_id == "alice"


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_app_mapped_to_a_service_account_runs_with_its_scopes(tmp_path, revoked):
    app = _app(tmp_path)
    make_service_account(app, "reviewbot", ["agents:agent-1:run"], revoked=revoked)
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True, allowed_apps={"A_OTHER": "reviewbot"}).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    run_event, _ = await _send(ctx, user="", bot_id="B_OTHER", app_id="A_OTHER")
    assert run_event.called is not revoked
    if not revoked:
        assert run_event.call_args.args[0].user_id == "sa:reviewbot"
        assert run_event.call_args.args[0].authority.context.admin_scope == app.state.admin_scope
    run_event, client = await _send(
        ctx, user="", bot_id="B_OTHER", app_id="A_UNMAPPED", ts="1700000000.000200", event_id="Ev2"
    )
    # allowed_apps= is a closed list; an app cannot see an ephemeral, so it is told in the thread
    assert not run_event.called and not client.chat_postEphemeral.called
    assert client.chat_postMessage.call_args.kwargs["text"] == security._APP_NOT_ALLOWED_MESSAGE
    # A service account is never a directory user
    assert await app.state.user_store.acount() == 0


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
async def test_stop_refused_under_user_isolation_is_audited(tmp_path):
    app = _app(tmp_path, user_isolation=True, audit=True)
    ctx = make_ctx(authorize_senders=True).bind(app)
    run = make_event_context(owner="U123", user_id=SENDER, team_id="T123", entity_id="agent-1")
    client = make_async_client_mock()
    client.users_info = AsyncMock(side_effect=_users_info)
    assert not await security.can_stop(ctx, "U_OTHER", run, client)
    assert app.state.service_account_verifier.db.count_authz_audit_events(decisions=True) == 1


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
async def test_run_decisions_are_audited(tmp_path):
    app = _app(tmp_path, default_role=False, audit=True)
    ctx = make_ctx(authorize_senders=True).bind(app)
    run_event, _ = await _send(ctx)
    assert not run_event.called
    await app.state.role_store.aassign(SENDER, "member")
    run_event, _ = await _send(ctx, ts="1700000000.000200", event_id="Ev2")
    assert run_event.called
    # One denied and one allowed decision, as the REST route gate writes them, for the route the message stands for
    events = app.state.service_account_verifier.db.read_authz_audit_events(decisions=True)
    assert [event["target"] for event in events] == ["SLACK /agents/agent-1/runs"] * 2


@pytest.mark.asyncio
async def test_role_check_that_raises_refuses_the_message(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True).bind(app)
    with patch.object(security, "resolve_principal_authorization", AsyncMock(side_effect=RuntimeError("roles down"))):
        run_event, client = await _send(ctx)
    # A provider that raised is a denial, as over HTTP
    assert not run_event.called
    assert _ephemeral(client) == security._PERMISSIONS_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_sender_message_reads_the_directory_once(tmp_path):
    app = _app(tmp_path)
    ctx = make_ctx(authorize_senders=True).bind(app)
    with patch.object(app.state.user_store, "ais_disabled", AsyncMock(return_value=False)) as disabled:
        run_event, _ = await _send(ctx)
    # Creating the user reads its row, so its disabled switch is not read a second time, as over HTTP
    assert run_event.called and disabled.await_count == 0


@pytest.mark.asyncio
async def test_unreadable_disabled_switch_failing_closed_is_an_outage(tmp_path):
    app = _app(tmp_path, fail_closed=True, auto_provision=False)
    ctx = make_ctx(authorize_senders=True).bind(app)
    with patch.object(app.state.user_store, "ais_disabled", AsyncMock(side_effect=RuntimeError("db down"))):
        run_event, client = await _send(ctx)
    # The web answers 503 "User directory unavailable"; the account is not disabled
    assert not run_event.called
    assert _ephemeral(client) == security._DIRECTORY_UNAVAILABLE_MESSAGE


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
    ctx = make_ctx(authorize_senders=True, respond_to_other_apps=True, allowed_apps={"A_OK": "reviewbot"}).bind(app)
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
    ctx = make_ctx(
        authorize_senders=True,
        respond_to_other_apps=True,
        reply_to_mentions_only=False,
        allowed_apps={"A_OK": "reviewbot"},
    ).bind(app)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("account", ["created", "missing", "unknown-app"])
async def test_bot_service_account_true_uses_the_account_named_after_its_app(tmp_path, account):
    app = _app(tmp_path)
    if account == "created":
        make_service_account(app, "slack-a0self", ["agents:agent-1:run"])
    ctx = make_ctx(authorize_senders=True, service_account=True).bind(app)
    ctx.bot_id, ctx.bot_user_id = "B_SELF", "U_SELF"
    client = make_async_client_mock()
    # The bot's own app id comes from bots.info for its bot id, as another app's does
    if account == "unknown-app":
        client.bots_info = AsyncMock(side_effect=RuntimeError("ratelimited"))
    else:
        client.bots_info = AsyncMock(
            return_value={"ok": True, "bot": {"id": "B_SELF", "app_id": "A0SELF", "name": "s"}}
        )
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    if account == "created":
        assert isinstance(run_event.call_args.args[0].authority, InterfaceAuthorization)
    else:
        # Switched on, a bot whose account cannot be found refuses rather than run uncapped
        assert not run_event.called and _ephemeral(client) == security._BOT_SERVICE_ACCOUNT_MESSAGE


def test_allowed_apps_without_respond_to_other_apps_warns():
    agent = Agent(id="agent-1")
    slack = Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, allowed_apps={"A_OK": "reviewbot"})
    with patch("agno.os.app.log_warning") as warning:
        AgentOS(id="slack-directory", agents=[agent], interfaces=[slack], telemetry=False).get_app()
    assert any("respond_to_other_apps=True" in call.args[0] for call in warning.call_args_list)


@pytest.mark.parametrize(
    "setting",
    [{"service_account": "slack-bot"}, {"service_account": ""}, {"allowed_apps": {"A_OK": "reviewbot"}}],
    ids=["bot", "empty-name", "apps"],
)
def test_service_account_without_a_database_warns(setting):
    agent = Agent(id="agent-1")
    slack = Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, respond_to_other_apps=True, **setting)
    with patch("agno.os.app.log_warning") as warning:
        AgentOS(id="slack-directory", agents=[agent], interfaces=[slack], telemetry=False).get_app()
    assert any("Set AgentOS(db=...)" in call.args[0] for call in warning.call_args_list)


@pytest.mark.asyncio
async def test_bot_service_account_caps_every_run(tmp_path):
    app = _app(tmp_path, member_scopes=("agents:run", "tasks:write"))
    make_service_account(app, "slack-bot", ["agents:agent-1:run"])
    ctx = make_ctx(authorize_senders=True, service_account="slack-bot").bind(app)
    run_event, _ = await _send(ctx)
    authority = run_event.call_args.args[0].authority
    assert isinstance(authority, InterfaceAuthorization)
    # The member may write Tasks, but every run through this bot is also checked against its own service account
    await authority.arequire("agents", "run", "agent-1")
    await authority.caller.arequire("tasks", "write")
    with pytest.raises(PermissionError):
        await authority.arequire("tasks", "write")
    # A restored run, such as a background or queued one, keeps the cap
    restored = restore_authorization(app, authority.snapshot())
    assert isinstance(restored, InterfaceAuthorization)
    await restored.arequire("agents", "run", "agent-1")
    with pytest.raises(PermissionError):
        await restored.arequire("tasks", "write")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scopes, revoked, message",
    [
        (["agents:agent-1:run"], True, security._BOT_SERVICE_ACCOUNT_MESSAGE),
        (["agents:agent-2:run"], False, security._BOT_PERMISSION_MESSAGE.format(scope="agents:agent-1:run")),
    ],
    ids=["revoked", "other-agent"],
)
async def test_bot_whose_service_account_cannot_run_the_agent_refuses(tmp_path, scopes, revoked, message):
    app = _app(tmp_path)
    make_service_account(app, "slack-bot", scopes, revoked=revoked)
    ctx = make_ctx(authorize_senders=True, service_account="slack-bot").bind(app)
    run_event, client = await _send(ctx)
    assert not run_event.called and _ephemeral(client) == message


@pytest.mark.asyncio
async def test_bot_service_account_caps_an_otherwise_unchecked_run(tmp_path):
    app = _app(tmp_path)
    make_service_account(app, "slack-bot", ["agents:agent-1:run"])
    ctx = make_ctx(service_account="slack-bot").bind(app)
    run_event, _ = await _send(ctx)
    event_context = run_event.call_args.args[0]
    authority = event_context.authority
    # The sender is still the run's caller, so Company tools see a person; only the bot's account is checked
    assert not authority.service_account and authority.context.principal_id == event_context.user_id
    await authority.arequire("agents", "run", "agent-1")
    with pytest.raises(PermissionError):
        await authority.arequire("tasks", "write")
    restored = restore_authorization(app, authority.snapshot())
    with pytest.raises(PermissionError):
        await restored.arequire("tasks", "write")


@pytest.mark.asyncio
async def test_bot_service_account_caps_a_users_mapped_run_as_the_mapped_user(tmp_path):
    agent = Agent(id="agent-1")
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    app = AgentOS(id="slack-directory", db=db, agents=[agent], telemetry=False).get_app()
    make_service_account(app, "slack-bot", ["agents:agent-1:run"])
    ctx = make_ctx(users={"U123": "alice"}, service_account="slack-bot").bind(app)
    run_event, _ = await _send(ctx)
    # Without authorization only the bot's account decides, still for the user users= maps the sender to
    assert run_event.call_args.args[0].authority.context.principal_id == "alice"
