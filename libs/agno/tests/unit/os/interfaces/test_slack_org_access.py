"""An os.agno.com token marks its user an org user and saves their role and scopes, which Slack then runs with."""

import time
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, UserDirectory
from agno.os.authz import Authorization
from agno.os.authz.user_directory import END_USER, ORG_ACCESS_KEY, ORG_USER, user_type_of
from agno.os.interfaces.slack import security
from agno.os.interfaces.slack.company import CompanyBridge, TaskDelivery
from agno.os.interfaces.slack.handlers import handle_message

from .conftest import make_async_client_mock, make_ctx, make_event_body

_EXECUTOR = "agno.os.interfaces.slack.handlers.executor"
SECRET = "slack-org-access-secret-at-least-32-bytes"
OS_ID = "slack-org-access"
ORG_ID = "org-1"
EMAIL = "test@example.com"
DENIED = security._PERMISSION_MESSAGE.format(scope="agents:agent-1:run")


def _app(tmp_path, roles=None, trust_token_scopes: bool = False, **directory_kwargs):
    """An AgentOS app under authorization with a user directory, and managed roles only when roles is given."""
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", trust_token_scopes=trust_token_scopes)
    for name, scopes in (roles or {}).items():
        auth.define_role(name, scopes)
    agent_os = AgentOS(
        id=OS_ID,
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        agents=[Agent(id="agent-1")],
        authorization=auth,
        user_directory=UserDirectory(**directory_kwargs) if directory_kwargs else True,
        telemetry=False,
    )
    return agent_os.get_app()


def _open_os(app, scopes=("agents:read", "agents:run"), role: str = "member", platform: bool = True, sub=EMAIL) -> int:
    """One web request with a token for sub, shaped like os.agno.com's when platform is True; returns its status."""
    claims = {"sub": sub, "aud": OS_ID, "scopes": list(scopes), "exp": int(time.time()) + 600}
    if platform:
        claims.update({"org_id": ORG_ID, "os_id": OS_ID, "role": role, "denies": ["agents:secret:run"]})
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    return TestClient(app).get("/agents", headers={"Authorization": f"Bearer {token}"}).status_code


def _slack_member(email_confirmed: bool = True) -> dict:
    return {
        "ok": True,
        "user": {
            "id": "U123",
            "team_id": "T123",
            "is_email_confirmed": email_confirmed,
            "profile": {"email": EMAIL, "display_name": "Test User"},
        },
    }


async def _send(app, ctx=None, resolve_user_identity: bool = True):
    """One Slack message from U123, whose confirmed email is EMAIL, to an authorize_senders interface."""
    ctx = (ctx or make_ctx(authorize_senders=True, resolve_user_identity=resolve_user_identity)).bind(app)
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_slack_member())
    with patch(f"{_EXECUTOR}.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(), client, ctx)
    text = client.chat_postEphemeral.call_args.kwargs["text"] if client.chat_postEphemeral.called else None
    return run_event, text


async def _user(app):
    return await app.state.user_store.aget(EMAIL)


# ==================== Recording org users ====================


@pytest.mark.asyncio
async def test_an_os_agno_com_token_marks_its_user_an_org_user_with_their_access(tmp_path):
    app = _app(tmp_path)
    assert _open_os(app, role="admin") == 200
    user = await _user(app)
    assert user_type_of(user) == ORG_USER
    saved = user["metadata"][ORG_ACCESS_KEY]
    assert saved["role"] == "admin"
    assert saved["scopes"] == ["agents:read", "agents:run"]
    assert saved["denies"] == ["agents:secret:run"]
    assert saved["org_id"] == ORG_ID
    assert abs(saved["at"] - time.time()) < 5


@pytest.mark.asyncio
async def test_any_other_token_leaves_its_user_an_end_user(tmp_path):
    app = _app(tmp_path)
    assert _open_os(app, platform=False) == 200
    user = await _user(app)
    assert user_type_of(user) == END_USER
    assert ORG_ACCESS_KEY not in (user.get("metadata") or {})
    assert app.state.user_store.org_access(user) is None


@pytest.mark.asyncio
async def test_unchanged_access_is_not_written_again_within_the_hour(tmp_path):
    app = _app(tmp_path)
    store = app.state.user_store
    _open_os(app)
    with patch.object(store, "_awrite", wraps=store._awrite) as write:
        _open_os(app)
        _open_os(app, scopes=("agents:run", "agents:read"))
    write.assert_not_called()


@pytest.mark.asyncio
async def test_a_role_change_on_os_agno_com_replaces_the_saved_access_and_is_audited(tmp_path):
    app = _app(tmp_path)
    store = app.state.user_store
    _open_os(app)
    with patch.object(store, "_aemit", new_callable=AsyncMock) as emit:
        _open_os(app, scopes=("agents:read",), role="viewer")
    emit.assert_awaited_once_with(
        "user.org_access",
        EMAIL,
        ["role:member", "agents:read", "agents:run"],
        ["role:viewer", "agents:read"],
        "system:os.agno.com",
    )
    assert (await _user(app))["metadata"][ORG_ACCESS_KEY]["role"] == "viewer"


@pytest.mark.asyncio
async def test_a_profile_edit_keeps_the_user_an_org_user_and_their_other_metadata(tmp_path):
    app = _app(tmp_path)
    store = app.state.user_store
    _open_os(app)
    user = await _user(app)
    await store.aupsert(EMAIL, name="Renamed", metadata={**user["metadata"], "team": "support"})
    user = await _user(app)
    assert user_type_of(user) == ORG_USER
    assert user["metadata"]["team"] == "support"
    assert store.org_scopes(user) == ["agents:read", "agents:run", "!agents:secret:run"]


def test_an_os_agno_com_token_fills_the_email_it_lacks_but_not_a_name(tmp_path):
    # The platform's token names its user in sub (their email); its username is the email too, so it is no name
    store = UserDirectory()
    claims = {"org_id": ORG_ID, "os_id": OS_ID, "role": "member", "username": EMAIL}
    store.upsert(EMAIL)
    store.remember_org_access(EMAIL, claims, ["agents:run"])
    user = store.get(EMAIL)
    assert user["email"] == EMAIL and user["name"] is None


def test_an_email_an_admin_set_is_kept(tmp_path):
    store = UserDirectory()
    store.upsert(EMAIL, email="other@example.com")
    store.remember_org_access(EMAIL, {"org_id": ORG_ID, "os_id": OS_ID}, ["agents:run"])
    assert store.get(EMAIL)["email"] == "other@example.com"


@pytest.mark.asyncio
async def test_a_user_recorded_before_the_profile_fill_gets_it_on_their_next_request(tmp_path):
    app = _app(tmp_path)
    store = app.state.user_store
    await store.aupsert(EMAIL)
    user = await _user(app)
    # Recorded as an org user, with no email, as before the fill existed
    await store._awrite(
        {
            **user,
            "user_type": ORG_USER,
            "metadata": {
                ORG_ACCESS_KEY: {
                    "role": "member",
                    "scopes": ["agents:read", "agents:run"],
                    "denies": ["agents:secret:run"],
                    "org_id": ORG_ID,
                    "at": int(time.time()),
                }
            },
        }
    )
    _open_os(app)
    assert (await _user(app))["email"] == EMAIL


def test_the_sync_twin_records_and_skips_unknown_users():
    store = UserDirectory()
    claims = {"org_id": ORG_ID, "os_id": OS_ID, "role": "member"}
    store.remember_org_access("nobody@example.com", claims, ["agents:run"])
    assert store.get("nobody@example.com") is None
    store.upsert(EMAIL)
    assert user_type_of(store.get(EMAIL)) == END_USER
    store.remember_org_access(EMAIL, claims, ["agents:run", "agents:run"])
    assert user_type_of(store.get(EMAIL)) == ORG_USER
    assert store.org_scopes(store.get(EMAIL)) == ["agents:run"]


@pytest.mark.asyncio
async def test_with_max_age_none_nothing_is_recorded(tmp_path):
    app = _app(tmp_path, org_access_max_age=None)
    _open_os(app)
    user = await _user(app)
    assert user_type_of(user) == END_USER


@pytest.mark.asyncio
async def test_the_users_api_shows_the_type_and_the_org_access(tmp_path):
    app = _app(tmp_path)
    _open_os(app, role="admin", scopes=("agent_os:admin",))
    token = jwt.encode(
        {
            "sub": EMAIL,
            "aud": OS_ID,
            "scopes": ["agent_os:admin"],
            "org_id": ORG_ID,
            "os_id": OS_ID,
            "role": "admin",
            "exp": int(time.time()) + 600,
        },
        SECRET,
        algorithm="HS256",
    )
    body = TestClient(app).get(f"/users/{EMAIL}", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["user_type"] == ORG_USER
    assert body["org_access"]["role"] == "admin"
    assert body["org_access"]["scopes"] == ["agent_os:admin"]
    assert body["org_access"]["org_id"] == ORG_ID


# ==================== Slack ====================


@pytest.mark.asyncio
async def test_an_org_user_runs_in_slack_with_their_os_agno_com_scopes(tmp_path):
    app = _app(tmp_path)
    _open_os(app)
    run_event, text = await _send(app)
    assert text is None and run_event.called
    event_context = run_event.call_args.args[0]
    assert event_context.user_id == EMAIL
    assert sorted(event_context.authority.context.scopes) == ["!agents:secret:run", "agents:read", "agents:run"]


@pytest.mark.asyncio
async def test_someone_who_never_opened_the_os_is_told_how_to_get_access(tmp_path):
    app = _app(tmp_path)
    run_event, text = await _send(app)
    assert not run_event.called and text == security._NO_ORG_ACCESS_MESSAGE


@pytest.mark.asyncio
async def test_a_slack_id_user_gets_the_plain_permission_refusal(tmp_path):
    # Without resolve_user_identity the user is slack:{workspace}:{member}, who never signs in on os.agno.com
    app = _app(tmp_path)
    run_event, text = await _send(app, resolve_user_identity=False)
    assert not run_event.called and text == DENIED


@pytest.mark.asyncio
async def test_an_org_user_without_the_run_scope_is_refused_and_told_how_a_change_applies(tmp_path):
    app = _app(tmp_path)
    _open_os(app, scopes=("agents:read",))
    run_event, text = await _send(app)
    assert not run_event.called and text == DENIED + security._ACCESS_CHANGED_HINT


@pytest.mark.asyncio
async def test_a_per_os_deny_from_os_agno_com_applies_in_slack(tmp_path):
    # _open_os sends denies=["agents:secret:run"]; a deny on this agent overrides the broad agents:run allow
    app = _app(tmp_path)
    token = jwt.encode(
        {
            "sub": EMAIL,
            "aud": OS_ID,
            "scopes": ["agents:read", "agents:run"],
            "denies": ["agents:agent-1:run"],
            "org_id": ORG_ID,
            "os_id": OS_ID,
            "role": "member",
            "exp": int(time.time()) + 600,
        },
        SECRET,
        algorithm="HS256",
    )
    TestClient(app).get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert (await _user(app))["metadata"][ORG_ACCESS_KEY]["denies"] == ["agents:agent-1:run"]
    assert (await _user(app))["metadata"][ORG_ACCESS_KEY]["scopes"] == ["agents:read", "agents:run"]
    run_event, text = await _send(app)
    assert not run_event.called and text == DENIED + security._ACCESS_CHANGED_HINT


def test_a_token_deny_refuses_the_route_over_http(tmp_path):
    app = _app(tmp_path)

    def get(denies):
        claims = {"sub": EMAIL, "aud": OS_ID, "scopes": ["agents:read"], "exp": int(time.time()) + 600}
        if denies is not None:
            claims["denies"] = denies
        token = jwt.encode(claims, SECRET, algorithm="HS256")
        return TestClient(app).get("/agents/agent-1", headers={"Authorization": f"Bearer {token}"}).status_code

    assert get(None) == 200
    assert get(["agents:agent-1:read"]) == 403
    assert get(["agents:other:read"]) == 200


@pytest.mark.asyncio
async def test_expired_org_access_no_longer_counts(tmp_path):
    app = _app(tmp_path, org_access_max_age=3600)
    _open_os(app)
    store = app.state.user_store
    user = await _user(app)
    user["metadata"][ORG_ACCESS_KEY]["at"] -= 3601
    await store.aupsert(EMAIL, metadata=user["metadata"])
    run_event, text = await _send(app)
    assert not run_event.called and text == security._NO_ORG_ACCESS_MESSAGE


@pytest.mark.asyncio
async def test_a_disabled_org_user_is_refused(tmp_path):
    app = _app(tmp_path)
    _open_os(app)
    await app.state.user_store.aset_disabled(EMAIL, True)
    run_event, text = await _send(app)
    assert not run_event.called and text == security._DISABLED_MESSAGE


# ==================== Super Agent ====================


def _super_agent_ctx():
    """A Slack context serving Super Agent (company set) with authorize_senders."""
    ctx = make_ctx(authorize_senders=True, resolve_user_identity=True)
    return replace(ctx, company=CompanyBridge(Mock()))


@pytest.mark.asyncio
async def test_super_agent_runs_an_org_user_as_their_email_with_their_scopes(tmp_path):
    app = _app(tmp_path)
    _open_os(app, scopes=("teams:read", "teams:run"))
    run_event, text = await _send(app, ctx=_super_agent_ctx())
    assert text is None and run_event.called
    event_context = run_event.call_args.args[0]
    assert event_context.user_id == EMAIL
    assert sorted(event_context.authority.context.scopes) == ["!agents:secret:run", "teams:read", "teams:run"]


@pytest.mark.asyncio
async def test_super_agent_refuses_someone_with_no_os_agno_com_access(tmp_path):
    app = _app(tmp_path)
    run_event, text = await _send(app, ctx=_super_agent_ctx())
    assert not run_event.called and text == security._NO_ORG_ACCESS_MESSAGE


@pytest.mark.asyncio
async def test_task_results_go_to_the_author_as_the_same_directory_user(tmp_path):
    # Under authorize_senders the author of the message that started a Task is derived as the run's user was
    ctx = _super_agent_ctx()
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value=_slack_member())
    client.conversations_replies = AsyncMock(return_value={"messages": [{"ts": "1.1", "user": "U123"}]})
    assert await TaskDelivery(ctx)._message_author(client, "C1", "1.0", "1.1") == EMAIL

    client.users_info = AsyncMock(return_value=_slack_member(email_confirmed=False))
    other = _super_agent_ctx()
    assert await TaskDelivery(other)._message_author(client, "C1", "1.0", "1.1") == "slack:T123:U123"


def test_no_managed_roles_warns_only_when_org_access_is_off(tmp_path):
    from agno.os.interfaces.slack import Slack

    def warnings(**directory_kwargs):
        agent = Agent(id="agent-1")
        agent_os = AgentOS(
            id=OS_ID,
            db=SqliteDb(db_file=str(tmp_path / "warn.db")),
            agents=[agent],
            authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
            user_directory=UserDirectory(**directory_kwargs) if directory_kwargs else True,
            interfaces=[Slack(agent=agent, token="xoxb-test", signing_secret="secret", authorize_senders=True)],
            telemetry=False,
        )
        with patch("agno.os.app.log_warning") as warn:
            agent_os.get_app()
        return [call.args[0] for call in warn.call_args_list if "no managed roles" in call.args[0]]

    assert warnings() == []
    assert len(warnings(org_access_max_age=None)) == 1
