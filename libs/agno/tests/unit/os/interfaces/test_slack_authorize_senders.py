"""A Slack sender as a user in the user directory: ``Slack(authorize_senders=True)``.

Real Slack message events are handled against a real AgentOS, so the user directory, the role
store and the checks are the ones a deployment runs. Only Slack's Web API is a fake.
"""

import itertools
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock

import jwt
import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, OSManager
from agno.os.authz import PLATFORM, READ, RUN, Authorization, Role, UserDirectory
from agno.os.authz.run_context import restore_authorization
from agno.os.interfaces.slack import Slack, security
from agno.os.interfaces.slack.handlers import handle_message
from agno.os.interfaces.slack.helpers import resolve_slack_user

from .conftest import BOT_USER_ID, make_async_client_mock, make_event_body

SECRET = "slack-directory-users-secret-at-least-256-bits-long"
OS_ID = "slack-directory-users-os"
WORKSPACE = "T123"
ANSWER = "the answer"


def _member(member_id: str, email: Optional[str], confirmed: bool = True, **fields: Any) -> Dict[str, Any]:
    return {
        "id": member_id,
        "team_id": WORKSPACE,
        "name": member_id.lower(),
        "is_email_confirmed": confirmed,
        "profile": {"email": email, "real_name": member_id.title()},
        **fields,
    }


ALICE = _member("U_ALICE", "alice@example.com")
BOB = _member("U_BOB", "bob@example.com")
UNCONFIRMED = _member("U_NEW", "ceo@example.com", confirmed=False)
GUEST = _member("U_GUEST", "guest@partner.com", is_restricted=True)
EXTERNAL = _member("U_EXT", "ext@other.com", team_id="T_OTHER")
GRID_MEMBER = _member("U_GRID", "grid@example.com", team_id="T_HOME", enterprise_user={"teams": [WORKSPACE]})
APP_USER = _member("U_APP", None, is_bot=True)
MEMBERS = {m["id"]: m for m in (ALICE, BOB, UNCONFIRMED, GUEST, EXTERNAL, GRID_MEMBER, APP_USER)}


class _FixtureModel(Model):
    def __init__(self):
        super().__init__(id="fixture", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(role="assistant", content=ANSWER, response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke()

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def member_role() -> Role:
    return Role("member", scopes=READ + RUN)


def platform_role() -> Role:
    return Role("platform", scopes=READ + RUN + PLATFORM)


def _token(sub: str, scopes: Optional[List[str]] = None) -> Dict[str, str]:
    payload: Dict[str, Any] = {"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600}
    if scopes is not None:
        payload["scopes"] = scopes
    return {"Authorization": "Bearer " + jwt.encode(payload, SECRET, algorithm="HS256")}


ADMIN = _token("root@example.com", ["agent_os:admin"])
_message_number = itertools.count(1)


class _System:
    """One AgentOS with an agent on Slack, or Super Agent on Slack, and Slack's Web API as a fake."""

    def __init__(
        self,
        tmp_path,
        *,
        roles: Optional[List[Role]] = None,
        authorization: bool = True,
        user_directory: Any = None,
        super_agent: bool = False,
        **slack: Any,
    ):
        self.db = SqliteDb(db_file=str(tmp_path / "os.db"))
        self.authz = Authorization(verification_keys=[SECRET], algorithm="HS256", audience=OS_ID, roles=roles)
        self.directory = user_directory if isinstance(user_directory, UserDirectory) else None
        helper = Agent(id="helper", name="Helper", model=_FixtureModel(), db=self.db)
        self.os = AgentOS(
            id=OS_ID,
            db=self.db,
            agents=[helper],
            authorization=self.authz if authorization else False,
            user_directory=user_directory,
            manager=OSManager(model=_FixtureModel()) if super_agent else None,
            telemetry=False,
        )
        settings = {"token": "xoxb-test", "signing_secret": "slack-secret", "streaming": False, **slack}
        settings.setdefault("authorize_senders", True)
        settings.setdefault("resolve_user_identity", True)
        if super_agent:
            self.interface = Slack(team=self.os.manager, **settings)
        else:
            self.interface = Slack(agent=helper, **settings)
        self.os.interfaces.append(self.interface)
        self.app = self.os.get_app()
        self.ctx = self.interface.ctx.bind(self.app)
        # The bot knows its own id, as after Slack's auth.test: without it another app's message is never read
        self.ctx.bot_user_id = BOT_USER_ID
        self.web = TestClient(self.app)
        self.users_info = AsyncMock(side_effect=self._users_info)
        self.last_event_context: Any = None

    async def _users_info(self, user: str) -> Dict[str, Any]:
        return {"ok": True, "user": MEMBERS[user]}

    async def send(self, member: Optional[Dict[str, Any]], **event_fields: Any) -> Tuple[List[str], List[str]]:
        """Handle one Slack message. Returns the answers posted and the private replies to the sender."""
        client = make_async_client_mock()
        client.users_info = self.users_info
        number = next(_message_number)
        body = make_event_body(
            user=member["id"] if member else "",
            ts=f"17000{number:05d}.000100",
            event_id=f"Ev{number}",
            team_id=WORKSPACE,
            **event_fields,
        )
        await handle_message(body, client, self.ctx)
        answers = [call.kwargs.get("text") for call in client.chat_postMessage.call_args_list]
        private = [call.kwargs.get("text") for call in client.chat_postEphemeral.call_args_list]
        return answers, private

    def user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.web.get(f"/users/{user_id}", headers=ADMIN).json() if self.has_user(user_id) else None

    def has_user(self, user_id: str) -> bool:
        return self.web.get(f"/users/{user_id}", headers=ADMIN).status_code == 200

    def give_role(self, user_id: str, role: str) -> None:
        """An admin gives a user a role through the API, as the UI does."""
        response = self.web.post(f"/authz/subjects/{user_id}/roles", json={"role": role}, headers=ADMIN)
        assert response.status_code == 200, response.text


RAN = ([ANSWER], [])
NO_ACCESS = ([], [security._NO_ACCESS_MESSAGE.format(name="Helper")])
NO_PLATFORM_ACCESS = ([], [security._PLATFORM_ACCESS_MESSAGE])
DISABLED = ([], [security._DISABLED_MESSAGE])
OUTSIDER = ([], [security._OUTSIDER_MESSAGE])


# ----------------------------------------------------------------- the first message creates the user


@pytest.mark.asyncio
async def test_first_message_creates_the_user_by_email_with_the_default_role(tmp_path):
    # The settings the templates use: two roles, and member as the role a new user gets
    system = _System(
        tmp_path, roles=[member_role(), platform_role()], user_directory=UserDirectory(default_role="member")
    )
    assert not system.has_user("alice@example.com")
    assert await system.send(ALICE) == RAN
    user = system.user("alice@example.com")
    assert user["email"] == "alice@example.com" and not user["disabled"]
    assert system.authz.roles_of("alice@example.com") == ["member"]
    # One person is one user: nothing is kept under the Slack member id
    assert not system.has_user("U_ALICE")


@pytest.mark.asyncio
async def test_first_message_creates_the_user_with_no_role_without_a_default(tmp_path):
    system = _System(tmp_path, roles=[member_role(), platform_role()], user_directory=True)
    assert await system.send(ALICE) == NO_ACCESS
    assert system.has_user("alice@example.com")
    assert system.authz.roles_of("alice@example.com") == []
    # An admin gives the role, and the next message runs
    system.give_role("alice@example.com", "member")
    assert await system.send(ALICE) == RAN


@pytest.mark.asyncio
async def test_the_same_person_on_the_web_and_in_slack_is_one_user(tmp_path):
    system = _System(
        tmp_path, roles=[member_role(), platform_role()], user_directory=UserDirectory(default_role="member")
    )
    # Signed in on the web first: the token's sub is the email
    assert system.web.get("/agents/helper", headers=_token("alice@example.com")).status_code == 200
    created = system.user("alice@example.com")
    assert await system.send(ALICE) == RAN
    assert system.user("alice@example.com")["created_at"] == created["created_at"]
    assert system.web.get("/users", headers=ADMIN).json()["meta"]["total_count"] == 2  # alice and the admin
    # A change made to that one user applies in both places
    system.web.patch("/users/alice@example.com", json={"disabled": True}, headers=ADMIN).raise_for_status()
    assert await system.send(ALICE) == DISABLED
    assert system.web.get("/agents/helper", headers=_token("alice@example.com")).status_code == 403


# ----------------------------------------------------------------- Super Agent needs platform access


@pytest.mark.asyncio
async def test_super_agent_refuses_a_member_and_runs_after_platform_is_given(tmp_path):
    system = _System(
        tmp_path,
        roles=[member_role(), platform_role()],
        user_directory=UserDirectory(default_role="member"),
        super_agent=True,
    )
    assert await system.send(ALICE) == NO_PLATFORM_ACCESS
    assert system.authz.roles_of("alice@example.com") == ["member"]
    system.give_role("alice@example.com", "platform")
    assert await system.send(ALICE) == RAN
    # Moved back, the next message is refused again: the role is read on every message
    system.give_role("alice@example.com", "member")
    assert await system.send(ALICE) == NO_PLATFORM_ACCESS


@pytest.mark.asyncio
async def test_super_agent_refuses_a_sender_with_no_role(tmp_path):
    system = _System(tmp_path, roles=[member_role(), platform_role()], user_directory=True, super_agent=True)
    assert await system.send(ALICE) == NO_PLATFORM_ACCESS
    assert system.authz.roles_of("alice@example.com") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("super_agent", [False, True])
async def test_disabling_the_user_stops_their_next_message(tmp_path, super_agent):
    system = _System(
        tmp_path,
        roles=[member_role(), platform_role()],
        user_directory=UserDirectory(default_role="platform"),
        super_agent=super_agent,
    )
    assert await system.send(ALICE) == RAN
    system.web.patch("/users/alice@example.com", json={"disabled": True}, headers=ADMIN).raise_for_status()
    assert await system.send(ALICE) == DISABLED
    system.web.patch("/users/alice@example.com", json={"disabled": False}, headers=ADMIN).raise_for_status()
    assert await system.send(ALICE) == RAN


# ----------------------------------------------------------------- how the settings combine


@pytest.mark.asyncio
async def test_authorization_without_a_user_directory(tmp_path):
    # No user records are kept. A sender is refused unless Slack has a default role, which every sender then gets
    system = _System(tmp_path)
    assert await system.send(ALICE) == NO_ACCESS
    assert system.app.state.user_store is None

    system = _System(
        tmp_path / "with-default", roles=[Role("slack", scopes=["agents:helper:run"])], default_role="slack"
    )
    assert await system.send(ALICE) == RAN
    assert await system.send(BOB) == RAN
    assert system.app.state.user_store is None and system.authz.roles_of("alice@example.com") == []


@pytest.mark.asyncio
async def test_authorization_with_a_user_directory_and_no_roles_in_code(tmp_path):
    # Users are added with no role, and refused until an admin makes a role in the UI and gives it to them
    system = _System(tmp_path, user_directory=True)
    assert await system.send(ALICE) == NO_ACCESS
    assert system.has_user("alice@example.com")
    system.web.post("/authz/roles", json={"slug": "helpers", "name": "Helpers"}, headers=ADMIN).raise_for_status()
    system.web.put(
        "/authz/roles/helpers/scopes", json={"scopes": ["agents:helper:run"]}, headers=ADMIN
    ).raise_for_status()
    system.give_role("alice@example.com", "helpers")
    assert await system.send(ALICE) == RAN
    # Bob was given nothing
    assert await system.send(BOB) == NO_ACCESS


@pytest.mark.asyncio
async def test_slack_default_role_is_the_role_of_a_sender_who_holds_none(tmp_path):
    viewer = Role("viewer", scopes=["agents:read"])
    system = _System(tmp_path, roles=[member_role(), viewer], user_directory=True, default_role="member")
    # Alice holds no role, so the Slack default role decides, and she is not given it in the directory
    assert await system.send(ALICE) == RAN
    assert system.authz.roles_of("alice@example.com") == []
    # Bob holds a role of his own, so that role decides
    system.give_role("bob@example.com", "viewer")
    assert await system.send(BOB) == NO_ACCESS


@pytest.mark.asyncio
async def test_authorization_off_checks_nothing_and_lists_who_showed_up(tmp_path):
    system = _System(tmp_path, authorization=False, user_directory=True)
    assert await system.send(ALICE) == RAN
    assert system.app.state.user_store.get("alice@example.com")["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_without_authorize_senders_nothing_changes(tmp_path):
    # As on main: an agent's sender is not checked and no user is created
    system = _System(
        tmp_path,
        roles=[member_role()],
        user_directory=UserDirectory(default_role="member"),
        authorize_senders=False,
    )
    assert await system.send(ALICE) == RAN
    assert not system.has_user("alice@example.com")


# ----------------------------------------------------------------- who the sender is


@pytest.mark.asyncio
async def test_an_unconfirmed_email_is_never_the_user_id(tmp_path):
    system = _System(tmp_path, roles=[member_role()], user_directory=UserDirectory(default_role="member"))
    # An admin role waits for the address the sender typed into their Slack profile
    system.authz.set_role_scopes("admin", ["agent_os:admin"])
    system.authz.assign("ceo@example.com", "admin")
    assert await system.send(UNCONFIRMED) == RAN
    assert not system.has_user("ceo@example.com")
    user = system.user("U_NEW")
    assert user["email"] is None
    assert system.authz.roles_of("U_NEW") == ["member"]


@pytest.mark.asyncio
async def test_an_unconfirmed_email_is_not_used_without_authorize_senders_either():
    client = make_async_client_mock()
    client.users_info = AsyncMock(return_value={"ok": True, "user": UNCONFIRMED})
    assert (await resolve_slack_user(client, "U_NEW"))[0] == "U_NEW"
    client.users_info = AsyncMock(return_value={"ok": True, "user": ALICE})
    assert (await resolve_slack_user(client, "U_ALICE"))[0] == "alice@example.com"


@pytest.mark.asyncio
async def test_without_resolve_user_identity_the_user_is_the_slack_member_id(tmp_path):
    system = _System(
        tmp_path,
        roles=[member_role()],
        user_directory=UserDirectory(default_role="member"),
        resolve_user_identity=False,
    )
    assert await system.send(ALICE) == RAN
    user = system.user("U_ALICE")
    # The confirmed email labels the user; it is not their id
    assert user["email"] == "alice@example.com"
    assert not system.has_user("alice@example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("outsider", [GUEST, EXTERNAL], ids=["guest", "another-organization"])
async def test_a_guest_or_external_sender_starts_disabled_until_an_admin_enables_them(tmp_path, outsider):
    system = _System(tmp_path, roles=[member_role()], user_directory=UserDirectory(default_role="member"))
    user_id = outsider["profile"]["email"]
    assert await system.send(outsider) == OUTSIDER
    assert system.user(user_id)["disabled"] is True
    assert system.authz.roles_of(user_id) == []
    assert await system.send(outsider) == OUTSIDER
    # Enabled by an admin, they are a user like any other
    system.web.patch(f"/users/{user_id}", json={"disabled": False}, headers=ADMIN).raise_for_status()
    assert await system.send(outsider) == RAN


@pytest.mark.asyncio
async def test_a_guest_is_refused_where_no_directory_can_hold_them(tmp_path):
    system = _System(tmp_path, roles=[Role("slack", scopes=["agents:helper:run"])], default_role="slack")
    assert await system.send(ALICE) == RAN
    assert await system.send(GUEST) == OUTSIDER


@pytest.mark.asyncio
async def test_an_enterprise_grid_member_of_this_workspace_is_a_member(tmp_path):
    system = _System(tmp_path, roles=[member_role()], user_directory=UserDirectory(default_role="member"))
    assert await system.send(GRID_MEMBER) == RAN


@pytest.mark.asyncio
@pytest.mark.parametrize("app_user", [None, APP_USER], ids=["bot-id-only", "bot-user"])
async def test_another_app_is_not_run(tmp_path, app_user):
    settings: Dict[str, Any] = {"roles": [member_role()], "user_directory": UserDirectory(default_role="member")}
    # Without authorize_senders the app's message is answered, as on main
    unchecked = _System(tmp_path / "unchecked", respond_to_other_apps=True, authorize_senders=False, **settings)
    assert await unchecked.send(app_user, bot_id="B_OTHER") == RAN

    settings["user_directory"] = UserDirectory(default_role="member")
    system = _System(tmp_path / "checked", respond_to_other_apps=True, **settings)
    assert await system.send(app_user, bot_id="B_OTHER") == ([], [])
    assert system.web.get("/users", headers=ADMIN).json()["meta"]["total_count"] == 1  # the admin


@pytest.mark.asyncio
async def test_a_sender_slack_cannot_identify_is_not_run(tmp_path):
    system = _System(tmp_path, roles=[member_role()], user_directory=UserDirectory(default_role="member"))
    system.users_info.side_effect = RuntimeError("missing_scope")
    assert await system.send(ALICE) == ([], [security._SLACK_UNAVAILABLE_MESSAGE])
    assert not system.has_user("alice@example.com") and not system.has_user("U_ALICE")


@pytest.mark.asyncio
async def test_users_mapping_still_names_the_senders_it_lists(tmp_path):
    system = _System(
        tmp_path,
        roles=[member_role()],
        user_directory=UserDirectory(default_role="member"),
        users={"U_ALICE": "alice-on-the-web"},
    )
    system.authz.assign("alice-on-the-web", "member")
    assert await system.send(ALICE) == RAN
    assert not system.has_user("alice@example.com")
    # A sender the mapping leaves out is their own user
    assert await system.send(BOB) == RAN
    assert system.authz.roles_of("bob@example.com") == ["member"]


# ----------------------------------------------------------------- work that outlives the message


@pytest.mark.asyncio
async def test_authority_saved_with_a_run_reads_the_senders_role_when_it_is_used(tmp_path):
    # A Task started from the message runs later from the queue, on the authority saved with it
    system = _System(
        tmp_path,
        roles=[member_role(), platform_role()],
        user_directory=UserDirectory(default_role="platform"),
        super_agent=True,
    )
    captured: List[Any] = []
    original = security.authorize_run

    async def capture(ctx, event_context, *args, **kwargs):
        allowed = await original(ctx, event_context, *args, **kwargs)
        captured.append(event_context.authority)
        return allowed

    security.authorize_run = capture
    try:
        assert await system.send(ALICE) == RAN
    finally:
        security.authorize_run = original
    saved = captured[0].snapshot()
    assert saved["context"]["principal_id"] == "alice@example.com" and not saved["context"].get("roles")

    await restore_authorization(system.app, saved).arequire("teams", "run", "superagent")
    system.give_role("alice@example.com", "member")
    with pytest.raises(PermissionError):
        await restore_authorization(system.app, saved).arequire("teams", "run", "superagent")
