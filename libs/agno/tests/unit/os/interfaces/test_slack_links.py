"""Super Agent in Slack under authorization: each member acts as the AgentOS user with their Slack email."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os.interfaces.slack.handlers import _NOT_LINKED_MESSAGE, _SIGN_IN_FIRST, handle_message
from agno.os.interfaces.slack.links import SlackLinks, match_member
from agno.os.interfaces.slack.security import can_act, sender_principal

from .conftest import BOT_USER_ID, make_async_client_mock, make_ctx, make_event_body, make_event_context

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
_AUTHORIZE = "agno.os.interfaces.slack.security.resolve_principal_authorization"
_MATCH = "agno.os.interfaces.slack.links.match_member"
JWT_KEY = "slack-links-jwt-verification-key-at-least-32-chars"
_MESSAGE_TS = iter(range(1, 100_000))


class _Directory:
    """A user directory holding the given ids, as AgentOS(user_directory=True) lends one on app.state."""

    def __init__(self, *rows):
        self.rows = {row["id"]: row for row in rows}

    async def aget(self, id):
        return self.rows.get(id)


def _user(id, disabled=False):
    return {"id": id, "disabled": disabled}


def _member(email="Kaus@Agno.com", **overrides):
    user = {"id": "U123", "team_id": "T123", "is_email_confirmed": True, "profile": {"email": email}}
    user.update(overrides)
    return {"ok": True, "user": user}


def _app(directory):
    return SimpleNamespace(state=SimpleNamespace(user_store=directory))


@pytest.fixture(params=["sync", "async"])
def links(request, tmp_path):
    db_class = SqliteDb if request.param == "sync" else AsyncSqliteDb
    return SlackLinks(db_class(db_file=str(tmp_path / "links.db")))


def _ctx(links, directory, **overrides):
    ctx = make_ctx(resolve_user_identity=True, **overrides)
    ctx.links = links
    ctx.app = _app(directory)
    return ctx


async def _send(ctx, client, **body):
    # Each message gets its own timestamp, so it is not taken for a redelivery of an earlier one
    body.setdefault("ts", f"1700000000.{next(_MESSAGE_TS):06d}")
    with (
        patch(_AUTHORIZE, AsyncMock(return_value=None)),
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(**body), client, ctx)
    return run_event


# -- the store --


@pytest.mark.asyncio
async def test_a_link_is_stored_and_replaced(links):
    await links.link("T1", "U1", "alice@agno.com")
    assert await links.principal("T1", "U1") == "alice@agno.com"
    await links.link("T1", "U1", "bob@agno.com")
    assert await links.principal("T1", "U1") == "bob@agno.com"
    assert await links.principal("T2", "U1") is None


@pytest.mark.asyncio
async def test_a_lookup_without_the_workspace_finds_only_a_single_link(links):
    await links.link("T1", "U1", "alice@agno.com")
    assert await links.principal(None, "U1") == "alice@agno.com"
    assert await links.slack_user("alice@agno.com", None) == "U1"
    assert await links.slack_user("alice@agno.com", "T2") is None
    await links.link("T2", "U1", "alice@agno.com")
    assert await links.principal(None, "U1") is None


# -- matching a member by email --


@pytest.mark.asyncio
async def test_a_member_matches_the_user_whose_id_is_their_email():
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    assert await match_member(_app(_Directory(_user("kaus@agno.com"))), client, "T123", "U123") == "kaus@agno.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "member",
    [
        _member(is_email_confirmed=False),
        _member(is_restricted=True),
        _member(is_ultra_restricted=True),
        _member(is_bot=True),
        _member(deleted=True),
        _member(team_id="T_OTHER_ORG"),
        _member(email=""),
        _member(email="someone@else.com"),
    ],
)
async def test_only_a_confirmed_full_member_of_the_workspace_with_a_match_matches(member):
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=member)
    assert await match_member(_app(_Directory(_user("kaus@agno.com"))), client, "T123", "U123") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "directory",
    [
        _Directory(_user("kaus@agno.com", disabled=True)),
        # Two ids that differ only in case are ambiguous
        _Directory(_user("kaus@agno.com"), _user("Kaus@Agno.com")),
        None,
    ],
)
async def test_a_disabled_ambiguous_or_missing_user_does_not_match(directory):
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    assert await match_member(_app(directory), client, "T123", "U123") is None


@pytest.mark.asyncio
async def test_a_failed_slack_lookup_does_not_match():
    client = make_async_client_mock()
    client.users_info = AsyncMock(side_effect=RuntimeError("ratelimited"))
    assert await match_member(_app(_Directory(_user("kaus@agno.com"))), client, "T123", "U123") is None


# -- a message --


@pytest.mark.asyncio
async def test_a_matched_member_runs_as_that_user_and_is_linked_once(links):
    ctx = _ctx(links, _Directory(_user("kaus@agno.com")))
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    with (
        patch(_AUTHORIZE, AsyncMock(return_value=None)) as authorize,
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(ts="1700000001.000001"), client, ctx)
    assert run_event.call_args.args[0].user_id == "kaus@agno.com"
    # That user's own roles and disabled flag decide
    assert authorize.await_args.args[1] == "kaus@agno.com"
    assert await links.principal("T123", "U123") == "kaus@agno.com"
    notice = client.chat_postMessage.call_args.kwargs
    assert notice["channel"] == "U123" and "`kaus@agno.com`" in notice["text"]
    # Stored: the next message reads the link, without asking Slack or telling them again
    client.chat_postMessage.reset_mock()
    with patch(_MATCH, AsyncMock()) as match:
        assert (await _send(ctx, client)).call_args.args[0].user_id == "kaus@agno.com"
    assert not match.called and not client.chat_postMessage.called


@pytest.mark.asyncio
async def test_an_unmatched_member_is_refused_with_what_to_do(links):
    ctx = _ctx(links, _Directory(_user("someone@agno.com")))
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    assert not (await _send(ctx, client)).called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _NOT_LINKED_MESSAGE + _SIGN_IN_FIRST
    assert await links.principal("T123", "U123") is None


@pytest.mark.asyncio
async def test_a_member_who_signs_in_later_is_matched_on_their_next_message(links):
    directory = _Directory()
    ctx = _ctx(links, directory)
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    assert not (await _send(ctx, client)).called
    directory.rows["kaus@agno.com"] = _user("kaus@agno.com")
    assert (await _send(ctx, client)).called


@pytest.mark.asyncio
async def test_a_matched_but_refused_user_does_not_run(links):
    ctx = _ctx(links, _Directory(_user("kaus@agno.com")))
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    with (
        patch(_AUTHORIZE, AsyncMock(side_effect=PermissionError("Permission required: teams:superagent:run"))),
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(ts="1700000002.000001"), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"].startswith("Not run: Permission required")


@pytest.mark.asyncio
async def test_users_map_is_the_only_mapping_when_set(links):
    ctx = _ctx(links, _Directory(_user("kaus@agno.com")), users={"U_OTHER": "alice@agno.com"})
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_member())
    # A member the map leaves out is not matched by email
    with patch(_MATCH, AsyncMock(return_value="kaus@agno.com")) as match:
        assert not (await _send(ctx, client)).called
    assert not match.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _NOT_LINKED_MESSAGE


@pytest.mark.asyncio
async def test_a_refusal_for_a_top_level_message_shows_in_the_channel(links):
    ctx = _ctx(links, _Directory())
    client = make_async_client_mock()
    await _send(ctx, client, text=f"<@{BOT_USER_ID}> hi", channel_type="channel", event_type="app_mention")
    # Slack hides an ephemeral posted into a message that has no replies yet
    assert client.chat_postEphemeral.call_args.kwargs["thread_ts"] is None


@pytest.mark.asyncio
async def test_a_refusal_for_a_threaded_message_stays_in_its_thread(links):
    ctx = _ctx(links, _Directory())
    client = make_async_client_mock()
    await _send(
        ctx, client, text=f"<@{BOT_USER_ID}> hi", channel_type="channel", event_type="app_mention", thread_ts="1.0"
    )
    assert client.chat_postEphemeral.call_args.kwargs["thread_ts"] == "1.0"


# -- approvals, Stop and Task results use the same identity --


@pytest.mark.asyncio
async def test_a_clicker_is_matched_the_same_way_as_a_sender(links):
    ctx = _ctx(links, _Directory(_user("kaus@agno.com")))
    client = make_async_client_mock()
    run = make_event_context(owner="U_ORIGINAL", user_id="kaus@agno.com", team_id="T123")
    # The same person may decide on their own run once matched, like a sender
    client.users_info = AsyncMock(return_value=_member(id="U_SAME_PERSON"))
    assert await can_act(ctx, "U_SAME_PERSON", run, client)
    client.users_info = AsyncMock(return_value=_member(email="someone@agno.com", id="U_STRANGER"))
    assert not await can_act(ctx, "U_STRANGER", run, client)


@pytest.mark.asyncio
async def test_a_task_result_reads_the_stored_link(links):
    ctx = _ctx(links, _Directory(_user("kaus@agno.com")))
    await links.link("T123", "U123", "kaus@agno.com")
    with patch(_MATCH, AsyncMock()) as match:
        assert await sender_principal(ctx, "T123", "U123", make_async_client_mock()) == "kaus@agno.com"
    assert not match.called


# -- AgentOS --


def _os(db, *, authorization=True, user_directory=True, **slack_overrides):
    pytest.importorskip("slack_bolt")
    from agno.os import AgentOS, Authorization
    from agno.os.interfaces.slack import Slack
    from agno.os.manager import OSManager
    from tests.unit.os.test_manager import OfflineModel

    authz = Authorization(verification_keys=[JWT_KEY], algorithm="HS256", audience="slack-links")
    os = AgentOS(
        id="slack-links",
        db=db,
        telemetry=False,
        authorization=authz if authorization else None,
        manager=OSManager(model=OfflineModel()),
        user_directory=True if user_directory else None,
    )
    settings = {"team": os.manager, "token": "xoxb-test", "signing_secret": "slack-secret"}
    settings.update(slack_overrides)
    os.interfaces.append(Slack(**settings))
    return os


def test_super_agent_starts_under_authorization_with_resolve_user_identity(tmp_path):
    os = _os(SqliteDb(db_file=str(tmp_path / "os.db")), resolve_user_identity=True)
    os.get_app()
    assert isinstance(os.interfaces[-1].ctx.links, SlackLinks)


@pytest.mark.parametrize(
    "settings",
    [
        {"resolve_user_identity": False},
        {"resolve_user_identity": True, "user_directory": False},
    ],
)
def test_super_agent_under_authorization_still_requires_identity_mapping(tmp_path, settings):
    os = _os(SqliteDb(db_file=str(tmp_path / "os.db")), **settings)
    with pytest.raises(ValueError, match="requires Slack identity mapping"):
        os.get_app()


def test_a_users_map_is_not_linked_by_email(tmp_path):
    os = _os(SqliteDb(db_file=str(tmp_path / "os.db")), resolve_user_identity=True, users={"U1": "alice@agno.com"})
    os.get_app()
    assert os.interfaces[-1].ctx.links is None


def test_without_authorization_nothing_is_linked(tmp_path):
    os = _os(SqliteDb(db_file=str(tmp_path / "os.db")), authorization=False, resolve_user_identity=True)
    os.get_app()
    assert os.interfaces[-1].ctx.links is None
