import json
import time
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("slack_bolt", reason="slack_bolt not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.os.authz import Authorization
from agno.os.authz._role_store import RoleStore
from agno.os.interfaces.slack import Slack, security
from agno.os.interfaces.slack.context import event_context_from_run
from agno.os.interfaces.slack.handlers import _NOT_LINKED_MESSAGE, handle_message
from agno.os.interfaces.slack.security import (
    can_act,
    resolve_principal_authorization,
    resolve_signing_secret,
    resolve_token,
)
from agno.os.middleware.jwt import JWTMiddleware

from .conftest import (
    BOT_ID,
    BOT_USER_ID,
    SIGNING_SECRET,
    TOKEN,
    build_app,
    make_agent_mock,
    make_async_client_mock,
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

    @pytest.mark.asyncio
    async def test_can_act_directory_user_compared_as_principal(self, tmp_path, async_client_mock):
        ctx, _ = _super_agent_slack(tmp_path)
        event_context = make_event_context(owner="U_OWNER", user_id="alice@example.com", team_id="T123")
        async_client_mock.users_info = AsyncMock(return_value=_member())
        assert await can_act(ctx, "U_ALT", event_context, client=async_client_mock) is True
        async_client_mock.users_info = AsyncMock(return_value=_member(email="bob@example.com"))
        assert await can_act(ctx, "U_BOB", event_context, client=async_client_mock) is False

    @pytest.mark.parametrize("run_workspace, allowed", [("T123", True), (None, False)])
    @pytest.mark.asyncio
    async def test_can_act_on_a_recovered_run_uses_the_runs_workspace(
        self, tmp_path, async_client_mock, run_workspace, allowed
    ):
        from .test_slack_handlers import _run

        # After a restart, an org-installed app's button click names no workspace
        ctx, _ = _super_agent_slack(tmp_path)
        run = _run(
            "alice@example.com",
            session_id=f"{ctx.entity_id}:C1:100.1",
            metadata={"slack_team_id": run_workspace} if run_workspace else None,
        )
        event_context = await event_context_from_run(ctx, run, owner="U_OWNER", client=async_client_mock, team_id=None)
        async_client_mock.users_info = AsyncMock(return_value=_member())
        assert await can_act(ctx, "U_ALT", event_context, client=async_client_mock) is allowed
        # The owner written on the card needs no lookup
        assert await can_act(ctx, "U_OWNER", event_context, client=async_client_mock) is True


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


def _member(email="Alice@Example.com", team_id="T123", **fields):
    return {"ok": True, "user": {"id": "U123", "team_id": team_id, "profile": {"email": email}, **fields}}


def _super_agent_slack(tmp_path, users=None, default_role=False):
    """A Slack interface serving Super Agent under authorization, with a user directory and role grants."""
    auth = Authorization(verification_keys=[JWT_KEY], algorithm="HS256")
    auth.define_role("asker", ["teams:run", "tasks:read"]).assign("alice@example.com", "asker")
    if default_role:
        auth.define_role("member", ["teams:run"], default=True)
    agent_os = AgentOS(
        id="slack-security",
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        authorization=auth,
        user_directory=True,
        # Never called: the run itself is not started
        manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna", api_key="test")),
        telemetry=False,
    )
    slack = Slack(
        team=agent_os.manager, token=TOKEN, signing_secret=SIGNING_SECRET, resolve_user_identity=True, users=users
    )
    agent_os.interfaces.append(slack)
    app = agent_os.get_app()
    directory = agent_os.user_directory
    # A directory id is the identity provider's subject; a Slack sender is the user whose id is their email
    directory.upsert("alice@example.com")
    directory.upsert("bob@example.com")
    # The router binds the request's app, as for a signed event
    return slack.ctx.bind(app), directory


def _agent_slack(
    tmp_path, authorization, authorize_senders=False, users=None, saved_role=False, default_role=False, apps=None
):
    """A Slack interface serving an Agent, under authorization unless it is None, with a user directory."""
    if authorization == "roles-claim":
        auth = Authorization(verification_keys=[JWT_KEY], algorithm="HS256", roles_claim="role")
    else:
        auth = Authorization(
            verification_keys=[JWT_KEY], algorithm="HS256", trust_token_scopes=authorization == "trusted-scopes"
        )
    auth.define_role("asker", ["agents:run"])
    if saved_role:
        auth.assign("alice@example.com", "asker")
    if default_role:
        auth.define_role("member", ["agents:run"], default=True)
    # Each apps= principal holds the run role
    for principal in (apps or {}).values():
        auth.assign(principal, "asker")
    agent = Agent(id="agent-1")
    agent_os = AgentOS(
        id="slack-security",
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        agents=[agent],
        authorization=auth if authorization else None,
        user_directory=True,
        telemetry=False,
    )
    slack = Slack(
        agent=agent,
        token=TOKEN,
        signing_secret=SIGNING_SECRET,
        resolve_user_identity=True,
        authorize_senders=authorize_senders,
        users=users,
        apps=apps,
        respond_to_other_apps=apps is not None,
    )
    agent_os.interfaces.append(slack)
    app = agent_os.get_app()
    agent_os.user_directory.upsert("alice@example.com")
    ctx = slack.ctx.bind(app)
    # The bot's own ids, which auth.test sets at the first request; without them another app is never answered
    ctx.bot_id, ctx.bot_user_id = BOT_ID, BOT_USER_ID
    return ctx


async def _handle(ctx, member, user="U123", **event_fields):
    client = make_async_client_mock()
    if isinstance(member, Exception):
        client.users_info = AsyncMock(side_effect=member)
    else:
        client.users_info = AsyncMock(return_value=member)
    client.bots_info = AsyncMock(return_value={"ok": True, "bot": {"name": "Deploy hook"}})
    with patch("agno.os.interfaces.slack.handlers.executor.run_event", new_callable=AsyncMock) as run_event:
        await handle_message(make_event_body(user=user, **event_fields), client, ctx)
    event_context = run_event.call_args.args[0] if run_event.called else None
    ephemeral = client.chat_postEphemeral.call_args.kwargs["text"] if client.chat_postEphemeral.called else None
    return event_context, ephemeral


class TestDirectoryPrincipal:
    @pytest.mark.asyncio
    async def test_sender_runs_as_their_directory_user_with_its_roles(self, tmp_path):
        ctx, _ = _super_agent_slack(tmp_path)
        event_context, ephemeral = await _handle(ctx, _member())
        # The run's user is the directory id, not the email as Slack spells it
        assert (event_context.user_id, event_context.owner, ephemeral) == ("alice@example.com", "U123", None)
        await event_context.authority.arequire("teams", "run", ctx.entity_id)

    @pytest.mark.parametrize(
        "member",
        [
            _member(email=None),
            # The Kelvin sign case-folds to "k"
            _member(email="\u212aate@example.com"),
            _member(email="carol@example.com"),
            # A Slack Connect member from another organization, a deleted account, a bot
            _member(team_id="T_OTHER"),
            _member(team_id="T_OTHER", enterprise_user={"teams": ["T_OTHER", "T_X"]}),
            _member(is_stranger=True),
            _member(deleted=True),
            _member(is_bot=True),
            RuntimeError("users.info failed"),
        ],
        ids=[
            "no-email",
            "non-ascii-email",
            "unknown-email",
            "other-workspace",
            "other-enterprise",
            "stranger",
            "deleted",
            "bot",
            "lookup-failed",
        ],
    )
    @pytest.mark.asyncio
    async def test_unresolved_sender_is_refused(self, tmp_path, member):
        ctx, _ = _super_agent_slack(tmp_path)
        event_context, ephemeral = await _handle(ctx, member)
        assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)

    @pytest.mark.asyncio
    async def test_enterprise_grid_member_of_the_event_workspace_resolves(self, tmp_path):
        # An Enterprise Grid member's home team differs from the workspace the message was sent in
        ctx, _ = _super_agent_slack(tmp_path)
        member = _member(team_id="T_HOME", enterprise_user={"teams": ["T_HOME", "T123"]})
        event_context, ephemeral = await _handle(ctx, member)
        assert (event_context.user_id, ephemeral) == ("alice@example.com", None)

    @pytest.mark.asyncio
    async def test_sender_with_no_workspace_is_refused_before_slack_is_asked(self, tmp_path):
        ctx, _ = _super_agent_slack(tmp_path)
        client = make_async_client_mock()
        client.users_info = AsyncMock(return_value=_member())
        assert await security.directory_principal(ctx, client, "U123", "T123") == "alice@example.com"
        client.users_info.reset_mock()
        # The workspace check cannot run, so the member is not resolved
        assert await security.directory_principal(ctx, client, "U456", None) is None
        client.users_info.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_email_column_is_never_matched(self, tmp_path):
        ctx, directory = _super_agent_slack(tmp_path, default_role=True)
        directory.remove("alice@example.com")
        # A first sign-in copies the token's email claim onto the row, and nothing verifies that claim
        directory.provision_from_claims("mallory-sub", {"sub": "mallory-sub", "email": "alice@example.com"})
        event_context, ephemeral = await _handle(ctx, _member())
        assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)
        # Once the member signs in they are themselves: the other row neither takes their identity nor blocks it
        directory.provision_from_claims("alice@example.com", {"sub": "alice@example.com"})
        event_context, ephemeral = await _handle(ctx, _member())
        assert (event_context.user_id, ephemeral) == ("alice@example.com", None)

    @pytest.mark.asyncio
    async def test_sender_is_the_directory_user_whose_id_is_the_email(self, tmp_path):
        # os.agno.com tokens carry the email as sub and no email claim, so the row's id is the email
        ctx, directory = _super_agent_slack(tmp_path, default_role=True)
        directory.remove("alice@example.com")
        directory.provision_from_claims("Alice@Example.com", {"sub": "Alice@Example.com"})
        event_context, ephemeral = await _handle(ctx, _member())
        # The default role authorizes the onboarded directory user with no role of their own
        assert (event_context.user_id, ephemeral) == ("Alice@Example.com", None)

    @pytest.mark.parametrize("member_id", ["alice@example.com", "ALICE@example.com"])
    @pytest.mark.asyncio
    async def test_id_differing_only_in_case_is_found_among_ids_containing_the_email(self, tmp_path, member_id):
        ctx, directory = _super_agent_slack(tmp_path, default_role=True)
        directory.remove("alice@example.com")
        directory.upsert(member_id)
        directory.upsert("0alice@example.com")
        event_context, ephemeral = await _handle(ctx, _member())
        assert (event_context.user_id, ephemeral) == (member_id, None)

    @pytest.mark.parametrize(
        "email, store_match",
        [
            # Postgres lower() folds the Kelvin sign to "k"; SQLite's does not
            ("kate@example.com", "\u212aate@example.com"),
            # A collation that ignores trailing spaces
            ("alice@example.com", "alice@example.com "),
        ],
        ids=["non-ascii-id", "trailing-space-id"],
    )
    @pytest.mark.asyncio
    async def test_id_a_store_matches_that_is_not_the_email_is_never_counted(
        self, tmp_path, monkeypatch, email, store_match
    ):
        ctx, directory = _super_agent_slack(tmp_path, default_role=True)
        directory.remove("alice@example.com")
        lookup = AsyncMock(return_value=[store_match])
        monkeypatch.setattr(directory, "aids_matching", lookup)
        event_context, ephemeral = await _handle(ctx, _member(email=email))
        assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)
        # Beside the member's own id it neither takes their identity nor blocks it
        directory.upsert(email)
        lookup.return_value = [store_match, email]
        event_context, ephemeral = await _handle(ctx, _member(email=email))
        assert (event_context.user_id, ephemeral) == (email, None)

    @pytest.mark.asyncio
    async def test_reserved_principal_rows_are_never_a_slack_member(self, tmp_path):
        ctx, directory = _super_agent_slack(tmp_path, default_role=True)
        directory.upsert("sa:deploy@example.com")
        event_context, ephemeral = await _handle(ctx, _member(email="sa:deploy@example.com"))
        assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)

    @pytest.mark.parametrize(
        "directory_ids, slack_email",
        [
            # Two other cases of the email; a substring of another id is not a match
            (["ALICE@example.com", "alice@EXAMPLE.com", "malice@example.com"], "Alice@Example.com"),
            # An id spelled as the Slack email does not win over another case
            (["alice@example.com", "ALICE@example.com"], "alice@example.com"),
            (["alice@example.com", "ALICE@example.com"], "ALICE@example.com"),
            (["alice@example.com", "ALICE@example.com"], "Alice@Example.com"),
            # A first sign-in whose subject is the member's Slack email in another case
            (["Alice@Example.com", "alice@example.com"], "alice@example.com"),
        ],
        ids=["other-cases", "lowercase-email", "uppercase-email", "mixed-case-email", "later-sign-in"],
    )
    @pytest.mark.asyncio
    async def test_ids_differing_only_in_case_are_refused(self, tmp_path, directory_ids, slack_email):
        ctx, directory = _super_agent_slack(tmp_path, default_role=True)
        directory.remove("alice@example.com")
        for user_id in directory_ids:
            directory.provision_from_claims(user_id, {"sub": user_id})
        event_context, ephemeral = await _handle(ctx, _member(email=slack_email))
        assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)

    @pytest.mark.parametrize(
        "member, warning",
        [
            # Per member: the email matches two directory ids that differ only in case
            (
                _member(email="carol@example.com"),
                "Slack user U123 matches 2 directory ids differing only in case; none is used",
            ),
            # Per interface: Slack returned no email
            (
                _member(email=None),
                "Slack returned no email for a member; without the users:read.email scope Slack returns none, "
                "so the directory lookup refuses every sender",
            ),
        ],
        ids=["case-twins", "no-email"],
    )
    @pytest.mark.asyncio
    async def test_directory_warning_is_logged_once(self, tmp_path, monkeypatch, member, warning):
        ctx, directory = _super_agent_slack(tmp_path)
        for user_id in ("carol@example.com", "Carol@example.com"):
            directory.provision_from_claims(user_id, {"sub": user_id})
        warnings: List[str] = []
        monkeypatch.setattr(security, "log_warning", warnings.append)
        for _ in range(2):
            event_context, ephemeral = await _handle(ctx, member)
            assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)
        assert [message for message in warnings if message.startswith("Slack")] == [warning]

    @pytest.mark.asyncio
    async def test_disabled_or_roleless_directory_user_is_refused(self, tmp_path):
        ctx, directory = _super_agent_slack(tmp_path)
        # bob is in the directory but holds no role
        event_context, ephemeral = await _handle(ctx, _member(email="bob@example.com"), user="U_BOB")
        assert (event_context, ephemeral) == (None, "Not run: Permission required: teams:superagent:run")
        directory.set_disabled("alice@example.com", True)
        event_context, ephemeral = await _handle(ctx, _member())
        assert (event_context, ephemeral) == (None, "Not run: User is disabled")

    @pytest.mark.asyncio
    async def test_users_allowlist_is_not_widened_by_the_directory(self, tmp_path):
        ctx, _ = _super_agent_slack(tmp_path, users={"U_OTHER": "alice@example.com"})
        event_context, ephemeral = await _handle(ctx, _member())
        assert (event_context, ephemeral) == (None, _NOT_LINKED_MESSAGE)


class TestAgentSendersAreNotChecked:
    @pytest.mark.parametrize("authorization", ["roles", "roles-claim", "trusted-scopes"])
    @pytest.mark.parametrize(
        "email",
        [
            # A directory user with no role
            "Alice@Example.com",
            # A member with no directory user
            "carol@example.com",
        ],
    )
    @pytest.mark.asyncio
    async def test_agent_under_authorization_answers_every_member_as_their_slack_email(
        self, tmp_path, authorization, email
    ):
        # Without authorize_senders, resolve_user_identity only names an Agent's run user; only users= checks senders
        ctx = _agent_slack(tmp_path, authorization)
        event_context, ephemeral = await _handle(ctx, _member(email=email))
        assert (event_context.user_id, event_context.authority, ephemeral) == (email, None, None)


class TestAuthorizeSenders:
    @pytest.mark.parametrize(
        "authorization, settings, email, expected",
        [
            # The run's user is the directory id, not the email as Slack spells it
            ("roles", {"saved_role": True}, "Alice@Example.com", ("alice@example.com", None)),
            # The default role authorizes the onboarded directory user with no role of their own
            ("roles", {"default_role": True}, "Alice@Example.com", ("alice@example.com", None)),
            # A Slack request carries no role claim, so the saved role decides
            ("roles-claim", {"saved_role": True}, "Alice@Example.com", ("alice@example.com", None)),
            ("trusted-scopes", {"saved_role": True}, "Alice@Example.com", ("alice@example.com", None)),
            # A directory user with no role
            ("roles", {}, "Alice@Example.com", (None, "Not run: Permission required: agents:agent-1:run")),
            # A member with no directory user
            ("roles", {"saved_role": True}, "carol@example.com", (None, _NOT_LINKED_MESSAGE)),
            # users= is an allowlist the directory does not widen
            (
                "roles",
                {"saved_role": True, "users": {"U_OTHER": "alice@example.com"}},
                "Alice@Example.com",
                (None, _NOT_LINKED_MESSAGE),
            ),
            # Without authorization the flag checks no one
            (None, {}, "carol@example.com", ("carol@example.com", None)),
        ],
        ids=[
            "saved-role",
            "default-role",
            "roles-claim",
            "trusted-scopes",
            "no-role",
            "unknown-email",
            "users",
            "authorization-off",
        ],
    )
    @pytest.mark.asyncio
    async def test_agent_checks_each_sender_as_super_agent_does(
        self, tmp_path, authorization, settings, email, expected
    ):
        ctx = _agent_slack(tmp_path, authorization, authorize_senders=True, **settings)
        event_context, ephemeral = await _handle(ctx, _member(email=email))
        assert (event_context.user_id if event_context else None, ephemeral) == expected

    @pytest.mark.parametrize(
        "authorization, settings, warned, error",
        [
            # Without users= or resolve_user_identity, no sender has a principal
            (
                "scopes",
                {"authorize_senders": True},
                False,
                "Slack serving 'agent-1' under authorization requires Slack identity mapping",
            ),
            # Token scopes alone: the API starts, and a warning says no Slack sender can be authorized
            ("scopes", {"authorize_senders": True, "resolve_user_identity": True}, True, None),
            ("scopes", {"users": {"U1": "alice"}}, True, None),
            # The middleware on a base_app checks token scopes though AgentOS(authorization=...) is unset
            ("base-app", {"users": {"U1": "alice"}}, True, None),
            # A provider the base_app seeds before get_app() decides each Slack sender
            ("base-app-provider", {"users": {"U1": "alice"}}, False, None),
            # A Slack request carries no role claim, so a saved role can authorize a Slack sender
            ("roles-claim", {"users": {"U1": "alice"}}, False, None),
            # A bot whose senders are not checked starts with no warning
            ("scopes", {}, False, None),
        ],
        ids=[
            "no-identity-mapping",
            "authorize-senders",
            "users",
            "base-app",
            "base-app-provider",
            "roles-claim",
            "unchecked",
        ],
    )
    def test_agent_startup_warns_when_no_slack_sender_can_be_authorized(
        self, tmp_path, monkeypatch, authorization, settings, warned, error
    ):
        agent = Agent(id="agent-1")
        db = SqliteDb(db_file=str(tmp_path / "os.db"))
        auth = None
        base_app = None
        if authorization.startswith("base-app"):
            base_app = FastAPI()
            base_app.add_middleware(JWTMiddleware, verification_keys=[JWT_KEY], algorithm="HS256", authorization=True)
            if authorization == "base-app-provider":
                base_app.state.authorization_provider = RoleStore(db=db).provider
        else:
            roles_claim = "role" if authorization == "roles-claim" else None
            auth = Authorization(verification_keys=[JWT_KEY], algorithm="HS256", roles_claim=roles_claim)
        agent_os = AgentOS(
            id="slack-security",
            db=db,
            agents=[agent],
            authorization=auth,
            base_app=base_app,
            user_directory=True,
            telemetry=False,
            interfaces=[Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, **settings)],
        )
        if error is not None:
            with pytest.raises(ValueError, match=error):
                agent_os.get_app()
            return
        warnings: List[str] = []
        monkeypatch.setattr("agno.os.app.log_warning", warnings.append)
        agent_os.get_app()
        warning = (
            "Slack serving 'agent-1' under authorization requires managed roles: Slack requests carry no token, "
            "so every Slack sender is refused."
        )
        # Logged once at startup
        assert [message for message in warnings if message.startswith("Slack serving")] == ([warning] if warned else [])


class TestApps:
    @pytest.mark.parametrize(
        "sender, member, settings, expected",
        [
            # A bot user's post names its app id
            (
                {"user": "U_APP", "bot_id": "B_APP", "app_id": "A_APP"},
                _member(is_bot=True),
                {"authorize_senders": True},
                "deploy-bot",
            ),
            # An incoming webhook names no app id, so it is mapped by its bot id
            (
                {"user": "", "bot_id": "B_HOOK", "subtype": "bot_message"},
                _member(is_bot=True),
                {"authorize_senders": True},
                "deploy-bot",
            ),
            # An app apps= does not map is skipped without an ephemeral
            (
                {"user": "U_APP", "bot_id": "B_APP", "app_id": "A_OTHER"},
                _member(is_bot=True),
                {"authorize_senders": True},
                None,
            ),
            # users= is for people, so an app it names is skipped too
            (
                {"user": "U_APP", "bot_id": "B_APP", "app_id": "A_OTHER"},
                _member(is_bot=True),
                {"authorize_senders": True, "users": {"U_APP": "deploy-bot"}},
                None,
            ),
            # A person posting through an app's user token carries the app's ids; users.info says no bot
            ({"bot_id": "B_APP", "app_id": "A_APP"}, _member(), {"authorize_senders": True}, "alice@example.com"),
            # apps= is its own list, so an Agent that checks no sender still answers only the apps it maps
            ({"user": "U_APP", "bot_id": "B_APP", "app_id": "A_APP"}, _member(is_bot=True), {}, "deploy-bot"),
            ({"user": "U_APP", "bot_id": "B_APP", "app_id": "A_OTHER"}, _member(is_bot=True), {}, None),
        ],
        ids=[
            "bot-user",
            "webhook",
            "unmapped",
            "only-in-users",
            "user-token",
            "unchecked-mapped",
            "unchecked-unmapped",
        ],
    )
    @pytest.mark.asyncio
    async def test_only_another_app_runs_as_its_apps_principal(self, tmp_path, sender, member, settings, expected):
        apps = {"A_APP": "deploy-bot", "B_HOOK": "deploy-bot"}
        ctx = _agent_slack(tmp_path, "roles", saved_role=True, apps=apps, **settings)
        event_context, ephemeral = await _handle(ctx, member, **sender)
        assert (event_context.user_id if event_context else None, ephemeral) == (expected, None)
        if event_context is not None:
            await event_context.authority.arequire("agents", "run", ctx.entity_id)

    @pytest.mark.asyncio
    async def test_refused_app_gets_no_ephemeral(self, tmp_path):
        ctx = _agent_slack(tmp_path, "roles", authorize_senders=True, apps={"B_HOOK": "deploy-bot"})
        directory = ctx.app.state.user_store
        directory.upsert("deploy-bot")
        directory.set_disabled("deploy-bot", True)
        event_context, ephemeral = await _handle(
            ctx, _member(is_bot=True), user="", bot_id="B_HOOK", subtype="bot_message"
        )
        assert (event_context, ephemeral) == (None, None)

    @pytest.mark.parametrize(
        "settings, warned",
        [
            ({"respond_to_other_apps": True}, True),
            ({"respond_to_other_apps": True, "apps": {"A_APP": "deploy-bot"}}, False),
            # users= is for people, so it answers no app either
            ({"respond_to_other_apps": True, "users": {"U_APP": "deploy-bot"}}, True),
            ({}, False),
        ],
        ids=["no-apps", "apps", "users", "other-apps-off"],
    )
    def test_agent_startup_warns_when_no_other_app_can_be_answered(self, tmp_path, monkeypatch, settings, warned):
        agent = Agent(id="agent-1")
        agent_os = AgentOS(
            id="slack-security",
            db=SqliteDb(db_file=str(tmp_path / "os.db")),
            agents=[agent],
            authorization=Authorization(verification_keys=[JWT_KEY], algorithm="HS256"),
            user_directory=True,
            telemetry=False,
            interfaces=[
                Slack(
                    agent=agent,
                    token=TOKEN,
                    signing_secret=SIGNING_SECRET,
                    resolve_user_identity=True,
                    authorize_senders=True,
                    **settings,
                )
            ],
        )
        warnings: List[str] = []
        monkeypatch.setattr("agno.os.app.log_warning", warnings.append)
        agent_os.get_app()
        warning = (
            "Slack serving 'agent-1' answers no other app: pass Slack(apps={app_id: principal_id}) to "
            "run another app's messages as an AgentOS principal."
        )
        # Logged once at startup
        assert [message for message in warnings if "answers no other app" in message] == ([warning] if warned else [])

    @pytest.mark.parametrize(
        "authorization, settings, warning",
        [
            (
                True,
                {"apps": {"A_APP": "deploy-bot"}, "authorize_senders": True, "resolve_user_identity": True},
                "Slack serving 'agent-1' sets apps= but respond_to_other_apps is off, so no other app's message "
                "reaches it: pass Slack(respond_to_other_apps=True) to answer the apps it maps.",
            ),
            (
                False,
                {"authorize_senders": True, "resolve_user_identity": True},
                "Slack serving 'agent-1' sets authorize_senders=True without authorization, so its senders are not "
                "checked. To check them, set AgentOS(authorization=True) and configure JWT_VERIFICATION_KEY or "
                "JWT_JWKS_FILE.",
            ),
            # With users= set, users= checks senders without authorization
            (False, {"authorize_senders": True, "resolve_user_identity": True, "users": {"U1": "alice"}}, None),
            (
                True,
                {
                    "apps": {"A_APP": "deploy-bot"},
                    "authorize_senders": True,
                    "resolve_user_identity": True,
                    "respond_to_other_apps": True,
                },
                None,
            ),
        ],
        ids=["apps-other-apps-off", "authorization-off", "authorization-off-with-users", "used"],
    )
    def test_agent_startup_warns_when_a_slack_setting_does_nothing(
        self, tmp_path, monkeypatch, authorization, settings, warning
    ):
        agent = Agent(id="agent-1")
        agent_os = AgentOS(
            id="slack-security",
            db=SqliteDb(db_file=str(tmp_path / "os.db")),
            agents=[agent],
            authorization=Authorization(verification_keys=[JWT_KEY], algorithm="HS256") if authorization else None,
            user_directory=True,
            telemetry=False,
            interfaces=[Slack(agent=agent, token=TOKEN, signing_secret=SIGNING_SECRET, **settings)],
        )
        warnings: List[str] = []
        monkeypatch.setattr("agno.os.app.log_warning", warnings.append)
        agent_os.get_app()
        # Logged once at startup
        assert [message for message in warnings if message.startswith("Slack serving 'agent-1' sets")] == (
            [warning] if warning else []
        )
