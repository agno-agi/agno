import json
import time
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("slack_bolt", reason="slack_bolt not installed")

from fastapi.testclient import TestClient

from agno.os.interfaces.slack import Slack
from agno.os.interfaces.slack.security import can_act, resolve_signing_secret, resolve_token

from .conftest import TOKEN, build_app, make_agent_mock, make_ctx, make_event_body, make_event_context, sign


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
