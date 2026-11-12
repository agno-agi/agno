import json
import time
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("slack_bolt", reason="slack_bolt not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.interfaces.slack import Slack
from agno.os.interfaces.slack.security import (
    can_act,
    resolve_principal_authorization,
    resolve_signing_secret,
    resolve_token,
)
from agno.os.middleware.jwt import JWTMiddleware

from .conftest import (
    SIGNING_SECRET,
    TOKEN,
    build_app,
    make_agent_mock,
    make_ctx,
    make_event_body,
    make_event_context,
    sign,
)

JWT_KEY = "slack-security-jwt-verification-key-at-least-32-chars"


class TestCredentials:
    def test_resolve_signing_secret_explicit_env_and_empty(self, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "env-secret")
        assert resolve_signing_secret("explicit") == "explicit"
        assert resolve_signing_secret(None) == "env-secret"
        with pytest.raises(ValueError, match="signing secret"):
            resolve_signing_secret("")

    def test_resolve_token_explicit_env_and_missing(self, monkeypatch):
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-env")
        assert resolve_token("xoxb-explicit") == "xoxb-explicit"
        assert resolve_token(None) == "xoxb-env"
        monkeypatch.delenv("SLACK_TOKEN")
        with pytest.raises(ValueError, match="SLACK_TOKEN"):
            resolve_token(None)

    def test_resolve_token_empty_is_not_replaced_by_the_env(self, monkeypatch):
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-env")
        with pytest.raises(ValueError, match="bot token"):
            resolve_token("")

    @pytest.mark.parametrize("signing_secret", [None, ""])
    def test_slack_raises_without_a_signing_secret(self, monkeypatch, signing_secret):
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
        with pytest.raises(ValueError, match="signing secret"):
            Slack(agent=make_agent_mock(), token=TOKEN, signing_secret=signing_secret)

    def test_slack_reads_the_secret_at_construction_not_import(self, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "set-after-import")
        slack = Slack(agent=make_agent_mock(), token=TOKEN)
        assert slack.ctx.signing_secret == "set-after-import"


def _post(client: TestClient, body: bytes, timestamp: str, signature: str):
    return client.post(
        "/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )


class TestVerifySlackSignature:
    @pytest.mark.usefixtures("auth_test_mock")
    def test_stale_wrong_and_non_utf8_signatures_are_403(self):
        body = json.dumps(make_event_body()).encode()
        now = str(int(time.time()))
        stale = str(int(time.time()) - 60 * 6)
        with TestClient(build_app(make_agent_mock())) as client:
            assert _post(client, body, stale, sign(body, stale)).status_code == 403
            assert _post(client, body, now, sign(body, now, "wrong-secret")).status_code == 403
            assert _post(client, b'{"type": "\xff"}', now, "v0=abc").status_code == 403


class TestCanAct:
    @pytest.mark.asyncio
    async def test_can_act_owner_only_by_default(self):
        ctx = make_ctx()
        assert await can_act(ctx, "U_OWNER", make_event_context(owner="U_OWNER", user_id="U_OWNER")) is True
        assert await can_act(ctx, "U_OTHER", make_event_context(owner="U_OWNER", user_id="U_OWNER")) is False
        assert await can_act(ctx, "", make_event_context(owner="")) is False

    @pytest.mark.asyncio
    async def test_can_act_approver(self):
        ctx = make_ctx(approvers=["U_ADMIN"])
        assert await can_act(ctx, "U_ADMIN", make_event_context(owner="U_OWNER", user_id="U_OWNER")) is True
        assert await can_act(ctx, "U_OTHER", make_event_context(owner="U_OWNER", user_id="U_OWNER")) is False

    @pytest.mark.asyncio
    async def test_can_act_mapped_user_compared_as_principal(self):
        ctx = make_ctx(users={"U_OWNER": "alice", "U_ALT": "alice", "U_BOB": "bob"})
        event_context = make_event_context(user_id="alice", owner="")
        assert await can_act(ctx, "U_ALT", event_context) is True
        assert await can_act(ctx, "U_BOB", event_context) is False
        assert await can_act(ctx, "U_UNMAPPED", event_context) is False

    @pytest.mark.asyncio
    async def test_can_act_same_derived_identity_after_restart(self, async_client_mock):
        # With resolve_user_identity the run's user is an email and the event context has no owner
        ctx = make_ctx(resolve_user_identity=True)
        event_context = make_event_context(owner="", user_id="test@example.com")
        assert await can_act(ctx, "U123", event_context, client=async_client_mock) is True
        async_client_mock.users_info = AsyncMock(
            return_value={"user": {"id": "U9", "profile": {"email": "someone@example.com"}}}
        )
        assert await can_act(ctx, "U9", event_context, client=async_client_mock) is False


class TestResolvePrincipalAuthorization:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("authorization", [False, True])
    async def test_mapped_user_is_authorized_only_under_agentos_authorization(self, authorization):
        agent_os = AgentOS(
            id="slack-security",
            agents=[Agent(id="agent-1")],
            telemetry=False,
            authorization=Authorization(verification_keys=[JWT_KEY], algorithm="HS256") if authorization else None,
        )
        app = agent_os.get_app()
        if authorization:
            # Slack requests carry no token, so a principal without a role is refused
            with pytest.raises(PermissionError):
                await resolve_principal_authorization(app, "alice", "agents", "agent-1")
        else:
            assert await resolve_principal_authorization(app, "alice", "agents", "agent-1") is None

    @pytest.mark.asyncio
    async def test_mapped_user_is_authorized_under_base_app_jwt_middleware(self):
        base_app = FastAPI()
        base_app.add_middleware(JWTMiddleware, verification_keys=[JWT_KEY], algorithm="HS256", authorization=True)
        agent = Agent(id="agent-1")
        agent_os = AgentOS(
            id="slack-security",
            agents=[agent],
            telemetry=False,
            base_app=base_app,
            interfaces=[Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, users={"U1": "alice"})],
        )
        app = agent_os.get_app()
        # A principal without a role is refused, as the middleware refuses it over HTTP
        with pytest.raises(PermissionError):
            await resolve_principal_authorization(app, "alice", "agents", "agent-1")

    @pytest.mark.asyncio
    async def test_mapped_user_is_authorized_under_jwt_middleware_added_after_get_app(self):
        agent = Agent(id="agent-1")
        agent_os = AgentOS(
            id="slack-security",
            agents=[agent],
            telemetry=False,
            interfaces=[Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, users={"U1": "alice"})],
        )
        app = agent_os.get_app()
        # The documented pattern adds the middleware after get_app(), so the app flag is unset
        app.add_middleware(JWTMiddleware, verification_keys=[JWT_KEY], algorithm="HS256", authorization=True)
        with pytest.raises(PermissionError):
            await resolve_principal_authorization(app, "alice", "agents", "agent-1")

    @pytest.mark.asyncio
    async def test_disabled_user_is_refused_with_authorization_off(self):
        app = FastAPI()
        # The user directory applies without authorization, as the HTTP middleware applies it
        app.state.user_store = AsyncMock()
        app.state.user_store.ais_disabled = AsyncMock(return_value=True)
        with pytest.raises(PermissionError, match="User is disabled"):
            await resolve_principal_authorization(app, "alice", "agents", "agent-1")
