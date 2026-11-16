"""Linking a Slack account to the AgentOS principal a person signs in as."""

import time
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os.interfaces.slack.handlers import _LINK_HOW, _NOT_LINKED_MESSAGE, handle_message
from agno.os.interfaces.slack.links import SlackLinks, parse_command
from agno.os.interfaces.slack.security import can_act

from .conftest import BOT_USER_ID, make_async_client_mock, make_ctx, make_event_body, make_event_context

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
_AUTHORIZE = "agno.os.interfaces.slack.security.resolve_principal_authorization"
JWT_KEY = "slack-links-jwt-verification-key-at-least-32-chars"


@pytest.fixture(params=["sync", "async"])
def links(request, tmp_path):
    db_class = SqliteDb if request.param == "sync" else AsyncSqliteDb
    return SlackLinks(db_class(db_file=str(tmp_path / "links.db")))


def _linked_ctx(links, **overrides):
    ctx = make_ctx(**overrides)
    ctx.links = links
    return ctx


@pytest.mark.parametrize(
    "text, expected",
    [
        ("link ABCDE-FGHJK", ("link", "ABCDE-FGHJK")),
        ("  LINK abcdefghjk ", ("link", "abcdefghjk")),
        ("unlink", ("unlink", "")),
        ("link", ("link", "")),
        ("link this to the doc please", None),
        ("please link ABCDE-FGHJK", None),
        ("hello", None),
    ],
)
def test_parse_command(text, expected):
    assert parse_command(text) == expected


# -- the store --


@pytest.mark.asyncio
async def test_a_code_links_one_account_once(links):
    code, expires_at = await links.issue_code("alice")
    assert expires_at > time.time()
    assert await links.redeem(code, "T1", "U1") == "alice"
    # Spent: a second redeemer, even with the same code, links nothing
    assert await links.redeem(code, "T1", "U2") is None
    assert await links.principal("T1", "U1") == "alice"
    assert await links.principal("T1", "U2") is None


@pytest.mark.asyncio
async def test_a_code_is_case_and_dash_insensitive(links):
    code, _ = await links.issue_code("alice")
    assert await links.redeem(code.replace("-", "").lower(), "T1", "U1") == "alice"


@pytest.mark.asyncio
async def test_an_expired_code_links_nothing(links):
    code, _ = await links.issue_code("alice")
    with patch("agno.os.interfaces.slack.links.time.time", return_value=time.time() + 3600):
        assert await links.redeem(code, "T1", "U1") is None
    assert await links.principal("T1", "U1") is None


@pytest.mark.asyncio
async def test_a_new_code_voids_the_earlier_one(links):
    first, _ = await links.issue_code("alice")
    second, _ = await links.issue_code("alice")
    assert await links.redeem(first, "T1", "U1") is None
    assert await links.redeem(second, "T1", "U1") == "alice"


@pytest.mark.asyncio
async def test_a_voided_code_links_nothing(links):
    code, _ = await links.issue_code("alice")
    await links.void(code)
    assert await links.redeem(code, "T1", "U1") is None


@pytest.mark.asyncio
async def test_linking_again_replaces_the_principals_account_in_that_workspace(links):
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T1", "U1")
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T1", "U9")
    assert await links.principal("T1", "U1") is None
    assert [link["external_id"] for link in await links.links("alice")] == ["U9"]


@pytest.mark.asyncio
async def test_an_account_relinked_by_another_principal_moves_to_them(links):
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T1", "U1")
    code, _ = await links.issue_code("bob")
    await links.redeem(code, "T1", "U1")
    assert await links.principal("T1", "U1") == "bob"
    assert await links.links("alice") == []


@pytest.mark.asyncio
async def test_a_lookup_without_the_workspace_finds_only_a_single_link(links):
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T1", "U1")
    assert await links.principal(None, "U1") == "alice"
    assert await links.slack_user("alice", None) == "U1"
    assert await links.slack_user("alice", "T2") is None


@pytest.mark.asyncio
async def test_unlink_by_principal_or_by_account(links):
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T1", "U1")
    assert await links.unlink(team_id="T1", user_id="U1") == 1
    assert await links.principal("T1", "U1") is None
    assert await links.unlink(principal_id="alice") == 0


# -- link and unlink in Slack --


@pytest.mark.asyncio
async def test_link_in_a_direct_message_links_the_sender_and_runs_nothing(links):
    ctx = _linked_ctx(links)
    code, _ = await links.issue_code("alice")
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(text=f"link {code}", user="U123", team_id="T123"), client, ctx)
    assert not run_event.called
    assert await links.principal("T123", "U123") == "alice"
    assert "`alice`" in client.chat_postMessage.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_a_bad_code_is_answered_and_links_nothing(links):
    ctx = _linked_ctx(links)
    client = make_async_client_mock()
    await handle_message(make_event_body(text="link ABCDE-FGHJK"), client, ctx)
    assert "not valid or has expired" in client.chat_postMessage.call_args.kwargs["text"]
    assert await links.principal("T123", "U123") is None


@pytest.mark.asyncio
async def test_a_code_posted_in_a_channel_is_voided(links):
    ctx = _linked_ctx(links)
    code, _ = await links.issue_code("alice")
    client = make_async_client_mock()
    body = make_event_body(text=f"<@{BOT_USER_ID}> link {code}", channel_type="channel", event_type="app_mention")
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(body, client, ctx)
    assert not run_event.called
    assert "direct message" in client.chat_postEphemeral.call_args.kwargs["text"]
    # Others in the channel saw it, so nobody can use it now
    assert await links.redeem(code, "T123", "U_OTHER") is None
    assert await links.principal("T123", "U123") is None


@pytest.mark.asyncio
async def test_unlink_in_a_direct_message(links):
    ctx = _linked_ctx(links)
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T123", "U123")
    client = make_async_client_mock()
    await handle_message(make_event_body(text="unlink"), client, ctx)
    assert client.chat_postMessage.call_args.kwargs["text"].startswith("Unlinked")
    assert await links.principal("T123", "U123") is None


@pytest.mark.asyncio
async def test_link_commands_reach_the_agent_when_linking_is_off():
    ctx = make_ctx()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(text="link ABCDE-FGHJK"), make_async_client_mock(), ctx)
    assert run_event.called


# -- who a message runs as --


@pytest.mark.asyncio
async def test_an_unlinked_sender_is_told_how_to_link(links):
    ctx = _linked_ctx(links)
    client = make_async_client_mock()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _NOT_LINKED_MESSAGE + _LINK_HOW


@pytest.mark.asyncio
async def test_a_linked_sender_runs_as_their_principal(links):
    ctx = _linked_ctx(links)
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T123", "U123")
    authority = object()
    with (
        patch(_AUTHORIZE, AsyncMock(return_value=authority)) as authorize,
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(), make_async_client_mock(), ctx)
    event_context = run_event.call_args.args[0]
    assert (event_context.user_id, event_context.authority) == ("alice", authority)
    # The principal's own roles and disabled flag decide
    assert authorize.await_args.args[1] == "alice"


@pytest.mark.asyncio
async def test_a_linked_but_refused_principal_does_not_run(links):
    ctx = _linked_ctx(links)
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T123", "U123")
    client = make_async_client_mock()
    with (
        patch(_AUTHORIZE, AsyncMock(side_effect=PermissionError("User is disabled"))),
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == "Not run: User is disabled"


@pytest.mark.asyncio
async def test_users_map_comes_before_a_link(links):
    ctx = _linked_ctx(links, users={"U123": "service-bot"})
    code, _ = await links.issue_code("alice")
    await links.redeem(code, "T123", "U123")
    with (
        patch(_AUTHORIZE, AsyncMock(return_value=None)),
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
    ):
        await handle_message(make_event_body(), make_async_client_mock(), ctx)
    assert run_event.call_args.args[0].user_id == "service-bot"


@pytest.mark.asyncio
async def test_only_the_same_principal_may_act_on_a_linked_run(links):
    ctx = _linked_ctx(links)
    for principal, user in (("alice", "U1"), ("bob", "U2"), ("alice", "U3")):
        code, _ = await links.issue_code(principal)
        await links.redeem(code, "T1" if user != "U3" else "T2", user)
    run = make_event_context(owner="U1", user_id="alice", team_id="T1")
    assert await can_act(ctx, "U1", run)
    assert not await can_act(ctx, "U2", run)
    # Alice's account in another workspace is the same person
    assert await can_act(ctx, "U3", make_event_context(owner="U1", user_id="alice", team_id="T2"))


# -- AgentOS --


def _os(db, **slack_overrides):
    pytest.importorskip("slack_bolt")
    from agno.models.base import Model  # noqa: F401
    from agno.os import AgentOS, Authorization
    from agno.os.interfaces.slack import Slack
    from agno.os.manager import OSManager
    from tests.unit.os.test_manager import OfflineModel

    os = AgentOS(
        id="slack-links",
        db=db,
        telemetry=False,
        authorization=Authorization(verification_keys=[JWT_KEY], algorithm="HS256", audience="slack-links"),
        manager=OSManager(model=OfflineModel()),
    )
    settings = {"team": os.manager, "token": "xoxb-test", "signing_secret": "slack-secret", "link_accounts": True}
    settings.update(slack_overrides)
    os.interfaces.append(Slack(**settings))
    return os


def _token(sub: str) -> str:
    import jwt

    claims = {"sub": sub, "aud": "slack-links", "exp": int(time.time()) + 300}
    return jwt.encode(claims, JWT_KEY, algorithm="HS256")


def test_super_agent_starts_under_authorization_with_link_accounts(tmp_path):
    from fastapi.testclient import TestClient

    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    app = _os(db).get_app()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_token('alice')}"}

    assert client.post("/identity-links/slack/codes").status_code == 401
    created = client.post("/identity-links/slack/codes", headers=headers)
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    assert f"link {code}" in created.json()["instructions"]

    # The code links the Slack account it is redeemed from to the token's principal
    assert db.redeem_identity_link_code("slack", _code_hash(code), "T1", "U1", int(time.time())) == "alice"
    listed = client.get("/identity-links/slack", headers=headers).json()["links"]
    assert [(link["team_id"], link["slack_user_id"]) for link in listed] == [("T1", "U1")]
    # Another person sees only their own links
    assert client.get("/identity-links/slack", headers={"Authorization": f"Bearer {_token('bob')}"}).json() == {
        "links": []
    }
    assert client.delete("/identity-links/slack", headers=headers).json() == {"unlinked": 1}
    assert db.get_identity_link("slack", "T1", "U1") is None


def test_link_accounts_needs_authorization(tmp_path):
    pytest.importorskip("slack_bolt")
    from agno.agent import Agent
    from agno.os import AgentOS
    from agno.os.interfaces.slack import Slack

    os = AgentOS(id="slack-links", db=SqliteDb(db_file=str(tmp_path / "os.db")), telemetry=False)
    os.interfaces.append(
        Slack(agent=Agent(id="a"), token="xoxb-test", signing_secret="slack-secret", link_accounts=True)
    )
    with pytest.raises(ValueError, match="needs AgentOS authorization"):
        os.get_app()


def test_super_agent_without_users_or_link_accounts_still_refuses_to_start(tmp_path):
    os = _os(SqliteDb(db_file=str(tmp_path / "os.db")), link_accounts=False)
    with pytest.raises(ValueError, match="link_accounts=True"):
        os.get_app()


def _code_hash(code: str) -> str:
    from agno.os.interfaces.slack.links import _hash

    return _hash(code)
