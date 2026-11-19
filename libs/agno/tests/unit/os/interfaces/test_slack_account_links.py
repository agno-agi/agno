import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.os.interfaces.slack import links as links_module
from agno.os.interfaces.slack.handlers import handle_message
from agno.os.interfaces.slack.hitl import _OTHER_ACCOUNT_MESSAGE, _decider_context
from agno.os.interfaces.slack.ids import ACTION_LINK_ACCOUNT
from agno.os.interfaces.slack.links import MemberLink, PlatformLinks, PlatformUnavailable
from agno.os.interfaces.slack.security import (
    _EMAIL_HIDDEN,
    _LINKING_UNAVAILABLE,
    _OWNER_NOT_LINKED,
    authorize_linked,
    can_act,
    linking_enabled,
)

from .conftest import make_async_client_mock, make_ctx, make_event_body, make_event_context

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
JWT_KEY = "slack-account-links-jwt-verification-key-32-chars"
EMAIL = "kaus@agno.com"


def _token(sub: str = EMAIL, scopes=("teams:run", "tasks:read"), key: str = JWT_KEY, ttl: int = 900, **claims) -> str:
    payload = {"sub": sub, "scopes": list(scopes), "exp": int(time.time()) + ttl, **claims}
    return jwt.encode(payload, key, algorithm="HS256")


def _linked(token: str = "") -> MemberLink:
    return MemberLink(status="linked", token=token or _token(), email=EMAIL, expires_at=time.time() + 900)


def _not_linked() -> MemberLink:
    return MemberLink(status="not_linked", link_url="https://os.agno.com/connect/slack?session=abc")


def _app(authorization: bool = True):
    from agno.agent import Agent
    from agno.os import AgentOS
    from agno.os.middleware.jwt import JWTMiddleware

    app = AgentOS(id="slack-links", agents=[Agent(id="agent-1")], telemetry=False).get_app()
    if authorization:
        app.add_middleware(JWTMiddleware, verification_keys=[JWT_KEY], algorithm="HS256", authorization=True)
    return app


def _ctx(link: MemberLink = None, app=None, **overrides):
    """A Super Agent Slack context with account linking, whose platform answers link."""
    ctx = make_ctx(**overrides).bind(app if app is not None else _app())
    ctx.company = AsyncMock()
    ctx.company.agent_os = Mock(manager=ctx.entity)
    ctx.links = Mock(spec=PlatformLinks)
    ctx.links.resolve_slack_member = AsyncMock(return_value=link or _linked())
    return ctx


def _client():
    client = make_async_client_mock()
    client.auth_test = AsyncMock(return_value={"ok": True, "team_id": "T123", "team": "Agno"})
    return client


# ==================== Platform client ====================


def _platform(monkeypatch, handler) -> PlatformLinks:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        links_module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    return PlatformLinks("service-token", "http://platform.test/api/v1/")


@pytest.mark.asyncio
async def test_platform_links_caches_a_linked_member_until_shortly_before_the_token_expires(monkeypatch):
    calls = []
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "linked", "token": "t", "email": EMAIL, "expires_at": expires})

    platform = _platform(monkeypatch, handler)
    first = await platform.resolve_slack_member("T1", "U1", member_email="kaus@agno.com", member_name="kaus")
    second = await platform.resolve_slack_member("T1", "U1")
    assert first is second and (first.status, first.email) == ("linked", EMAIL)
    assert len(calls) == 1
    assert str(calls[0].url) == "http://platform.test/api/v1/identity-links/slack/resolve"
    assert calls[0].headers["authorization"] == "Bearer service-token"
    # Only what is known is sent
    assert calls[0].read() == b'{"team_id":"T1","member_id":"U1","member_name":"kaus","member_email":"kaus@agno.com"}'
    platform.forget("T1", "U1")
    await platform.resolve_slack_member("T1", "U1")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_platform_links_asks_again_for_an_unlinked_member(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "not_linked", "link_url": "https://os.agno.com/connect/slack"})

    platform = _platform(monkeypatch, handler)
    await platform.resolve_slack_member("T1", "U1")
    link = await platform.resolve_slack_member("T1", "U1")
    # A member who just linked is resolved again on their next message
    assert len(calls) == 2 and link.link_url == "https://os.agno.com/connect/slack"


@pytest.mark.parametrize("status", [401, 500])
@pytest.mark.asyncio
async def test_platform_links_refused_or_failing_is_unavailable(monkeypatch, status):
    platform = _platform(monkeypatch, lambda request: httpx.Response(status, json={}))
    with pytest.raises(PlatformUnavailable):
        await platform.resolve_slack_member("T1", "U1")


@pytest.mark.asyncio
async def test_platform_links_unreachable_is_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(PlatformUnavailable):
        await _platform(monkeypatch, handler).resolve_slack_member("T1", "U1")


def test_platform_links_from_env(monkeypatch):
    monkeypatch.delenv("AGNO_OS_SERVICE_TOKEN", raising=False)
    assert PlatformLinks.from_env() is None
    monkeypatch.setenv("AGNO_OS_SERVICE_TOKEN", "svc")
    monkeypatch.setenv("AGNO_PLATFORM_API_URL", "http://localhost:7090/api/v1")
    platform = PlatformLinks.from_env()
    assert platform is not None and platform.api_url == "http://localhost:7090/api/v1"


# ==================== When linking applies ====================


def test_linking_needs_super_agent_a_service_token_and_jwt_verification():
    assert linking_enabled(_ctx())
    no_company = _ctx()
    no_company.company = None
    assert not linking_enabled(no_company)
    no_token = _ctx()
    no_token.links = None
    assert not linking_enabled(no_token)


def test_linking_needs_the_agentos_own_manager_team():
    from agno.os.interfaces.slack.company import CompanyBridge

    # A company set by hand on an interface serving anything other than the AgentOS's manager
    ctx = _ctx()
    agent_os = Mock(manager=ctx.entity)
    ctx.company = CompanyBridge(agent_os, deliver=False)
    assert linking_enabled(ctx)
    agent_os.manager = Mock()
    assert not linking_enabled(ctx)
    agent_os.manager = None
    assert not linking_enabled(ctx)


def test_linking_without_jwt_verification_warns_once():
    ctx = _ctx(app=_app(authorization=False))
    with patch("agno.os.interfaces.slack.security.log_warning") as warn:
        assert not linking_enabled(ctx)
        assert not linking_enabled(ctx)
    warn.assert_called_once()


# ==================== A message ====================


@pytest.mark.asyncio
async def test_a_linked_member_runs_as_their_agno_account_with_its_scopes():
    ctx = _ctx()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), _client(), ctx)
    ctx.links.resolve_slack_member.assert_awaited_once_with(
        "T123", "U123", team_name="Agno", member_name="Test User", member_email="test@example.com"
    )
    event_context = run_event.call_args.args[0]
    assert event_context.user_id == EMAIL
    assert event_context.authority.context.principal_id == EMAIL
    assert event_context.authority.context.scopes == ["teams:run", "tasks:read"]
    # The platform decides access; the local principal check is not used
    ctx.company.authorize.assert_not_called()


@pytest.mark.asyncio
async def test_an_unlinked_member_gets_a_link_button_and_nothing_runs():
    ctx = _ctx(_not_linked())
    client = _client()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    kwargs = client.chat_postEphemeral.call_args.kwargs
    assert kwargs["user"] == "U123" and "Link your Agno account" in kwargs["text"]
    # A top-level message has no thread to show an ephemeral in, so the prompt goes beside it
    assert kwargs["thread_ts"] is None
    button = kwargs["blocks"][1]["elements"][0]
    assert (button["action_id"], button["url"]) == (
        ACTION_LINK_ACCOUNT,
        "https://os.agno.com/connect/slack?session=abc",
    )
    assert ctx.runs.find_run("anything") is None


@pytest.mark.asyncio
async def test_a_member_whose_account_lost_access_is_told_why():
    link = MemberLink(
        status="no_access", link_url="https://os.agno.com/connect/slack?session=x", reason="Not a member."
    )
    ctx = _ctx(link)
    client = _client()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert "Not a member." in client.chat_postEphemeral.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_a_refusal_linking_cannot_fix_gets_the_reason_without_a_button():
    link = MemberLink(status="no_access", reason="This AgentOS's organization needs an active subscription.")
    ctx = _ctx(link)
    client = _client()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    kwargs = client.chat_postEphemeral.call_args.kwargs
    assert kwargs["text"] == "Not run: This AgentOS's organization needs an active subscription."
    assert kwargs.get("blocks") is None


@pytest.mark.asyncio
async def test_a_member_whose_slack_email_is_hidden_is_told_why_instead_of_a_link_that_would_fail():
    ctx = _ctx(_not_linked())
    client = _client()
    client.users_info.return_value = {"ok": True, "user": {"id": "U123", "profile": {"display_name": "Test User"}}}
    with (
        patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event,
        patch("agno.os.interfaces.slack.security.log_warning") as warn,
    ):
        await handle_message(make_event_body(), client, ctx)
        await handle_message(make_event_body(ts="1700000000.000200", event_id="Ev2"), client, ctx)
    assert not run_event.called
    kwargs = client.chat_postEphemeral.call_args.kwargs
    assert kwargs["text"] == f"Not run: {_EMAIL_HIDDEN}" and kwargs.get("blocks") is None
    warn.assert_called_once()


@pytest.mark.asyncio
async def test_a_linked_run_records_that_it_is_acted_for_through_slack():
    from agno.os.authz.run_context import restore_authorization
    from agno.os.interfaces.slack.executor import _run_kwargs

    act = {"sub": "os:os-1", "via": "slack", "external_tenant": "T123", "external_id": "U123"}
    ctx = _ctx(_linked(_token(act=act)))
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), _client(), ctx)
    event_context = run_event.call_args.args[0]
    assert _run_kwargs(event_context, ctx, ([], [], [], []))["metadata"]["act"] == act
    # A queued Task restores the authority with the act claim, so its run is marked too
    restored = restore_authorization(ctx.app, event_context.authority.snapshot())
    assert restored.context.claims["act"] == act


@pytest.mark.asyncio
async def test_a_run_without_an_act_claim_is_not_marked():
    from agno.os.interfaces.slack.executor import _run_kwargs

    ctx = _ctx()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), _client(), ctx)
    metadata = _run_kwargs(run_event.call_args.args[0], ctx, ([], [], [], []))["metadata"] or {}
    assert "act" not in metadata


@pytest.mark.parametrize(
    "token, message",
    [
        (lambda: _token(key="another-key-that-is-also-at-least-32-characters"), "did not verify"),
        (lambda: _token(ttl=-10), "did not verify"),
        (lambda: _token(sub="sa:robot"), "Invalid token subject"),
        (lambda: _token(scopes=["agents:run"]), "Permission required"),
    ],
    ids=["wrong-key", "expired", "reserved-subject", "no-teams-run"],
)
@pytest.mark.asyncio
async def test_a_token_that_does_not_grant_the_run_is_refused(token, message):
    ctx = _ctx(_linked(token()))
    client = _client()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert message in client.chat_postEphemeral.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_a_token_that_does_not_verify_is_not_reused():
    ctx = _ctx(_linked(_token(key="another-key-that-is-also-at-least-32-characters")))
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock):
        await handle_message(make_event_body(), _client(), ctx)
    ctx.links.forget.assert_called_once_with("T123", "U123")


@pytest.mark.asyncio
async def test_an_unavailable_platform_refuses_the_message():
    ctx = _ctx()
    ctx.links.resolve_slack_member.side_effect = PlatformUnavailable("down")
    client = _client()
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    assert not run_event.called
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _LINKING_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_member_users_maps_keeps_the_mapping():
    ctx = _ctx(users={"U123": "alice"})
    authority = object()
    ctx.company.authorize = AsyncMock(return_value=authority)
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), _client(), ctx)
    ctx.links.resolve_slack_member.assert_not_called()
    assert (run_event.call_args.args[0].user_id, run_event.call_args.args[0].authority) == ("alice", authority)


@pytest.mark.asyncio
async def test_without_jwt_verification_super_agent_keeps_the_no_roles_principal():
    ctx = _ctx(app=_app(authorization=False))
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), _client(), ctx)
    ctx.links.resolve_slack_member.assert_not_called()
    assert run_event.called


# ==================== Someone other than the member ====================


@pytest.mark.asyncio
async def test_only_the_member_gets_the_link_button():
    ctx = _ctx(_not_linked())
    client = _client()
    event_context = make_event_context(owner="U123", user_id=EMAIL)
    assert not await authorize_linked(ctx, event_context, client, "U_APPROVER", "100.1")
    kwargs = client.chat_postEphemeral.call_args.kwargs
    # A link session links the Slack account to whoever confirms it, so no one else is sent one
    assert kwargs["user"] == "U_APPROVER" and kwargs["text"] == _OWNER_NOT_LINKED and "blocks" not in kwargs


@pytest.mark.asyncio
async def test_another_slack_account_linked_to_the_same_agno_account_can_act():
    ctx = _ctx()
    assert await can_act(ctx, "U_OTHER", make_event_context(owner="U123", user_id=EMAIL), _client())
    ctx.links.resolve_slack_member.return_value = _not_linked()
    assert not await can_act(ctx, "U_OTHER", make_event_context(owner="U123", user_id=EMAIL), _client())


@pytest.mark.asyncio
async def test_a_decision_rechecks_the_owners_account():
    ctx = _ctx()
    client = _client()
    event_context = make_event_context(owner="U123", user_id=EMAIL)
    ctx.runs.register(event_context)
    kwargs = dict(
        run_id="run-1", channel="C1", thread_ts="100.1", user="U123", owner="U123", card_ts="1", awaiting_ts=None
    )
    assert await _decider_context(client, ctx, card_blocks=[], **kwargs) is event_context
    assert event_context.authority.context.principal_id == EMAIL
    # Relinked to another account: the run is not decided for the account that started it
    ctx.links.resolve_slack_member.return_value = _linked(_token(sub="other@agno.com"))
    assert await _decider_context(client, ctx, card_blocks=[], **kwargs) is None
    assert client.chat_postEphemeral.call_args.kwargs["text"] == _OTHER_ACCOUNT_MESSAGE


# ==================== Task results ====================


@pytest.mark.asyncio
async def test_a_task_result_goes_to_the_author_of_the_starting_message_by_their_linked_account():
    from agno.os.interfaces.slack.company import TaskDelivery

    ctx = _ctx()
    delivery = TaskDelivery(ctx)
    client = _client()
    client.conversations_replies = AsyncMock(return_value={"messages": [{"ts": "100.2", "user": "U123"}]})
    author, authority = await delivery._linked_author(ctx.app, client, "C1", "100.1", "100.2")
    assert author == EMAIL and authority.context.scopes == ["teams:run", "tasks:read"]
    ctx.links.resolve_slack_member.return_value = _not_linked()
    assert await delivery._linked_author(ctx.app, client, "C1", "100.1", "100.2") == (None, None)
    # A message from a bot names no member
    client.conversations_replies.return_value = {"messages": [{"ts": "100.3", "bot_id": "B1"}]}
    assert await delivery._linked_author(ctx.app, client, "C1", "100.1", "100.3") == (None, None)


def test_link_prompt_blocks_carry_the_url():
    from agno.os.interfaces.slack.builders import build_link_prompt

    blocks = build_link_prompt("Link it", "https://os.agno.com/connect/slack?session=s")
    assert blocks[0]["text"]["text"] == "Link it"
    assert blocks[1]["elements"][0]["url"] == "https://os.agno.com/connect/slack?session=s"
