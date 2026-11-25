"""Roles as objects, the default role on the user directory, and the roles API that is on with authorization.

One AgentOS per test on a temporary SQLite file, called through the real app with signed tokens.
"""

import logging
import time
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.auth import aprovision_user_with_default_role, provision_user_with_default_role
from agno.os.authz import PLATFORM, READ, RUN, Authorization, Role, ScopeAuthorizationProvider, UserDirectory
from agno.os.authz._composite import CompositeAuthorizationProvider
from agno.os.authz._role_store import RoleChangeRefused
from agno.os.authz._scope_policy import scope_to_resource_action
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.config import AuthorizationConfig
from agno.os.scopes import get_default_scope_mappings
from agno.registry._reserved import MANAGER_RESOURCES

SECRET = "user-roles-secret-at-least-256-bits-long-xxxxxxxxxxxx"
OS_ID = "user-roles-os"


def _auth(sub, scopes=None):
    payload = {"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600}
    if scopes is not None:
        payload["scopes"] = scopes
    return {"Authorization": "Bearer " + jwt.encode(payload, SECRET, algorithm="HS256")}


def _admin():
    """A token as os.agno.com sends for an administrator: the access is in its scopes."""
    return _auth("root@example.com", ["agent_os:admin"])


def _db(tmp_path, name="os.db"):
    return SqliteDb(db_file=str(tmp_path / name))


def _verified(**kwargs):
    return Authorization(verification_keys=[SECRET], algorithm="HS256", **kwargs)


def _roles():
    return Role("member", scopes=READ + RUN), Role("platform", scopes=READ + RUN + PLATFORM)


def _os(db, authorization, **kwargs):
    return AgentOS(
        id=OS_ID,
        db=db,
        agents=[Agent(id="research", name="Research")],
        authorization=authorization,
        telemetry=False,
        **kwargs,
    )


@pytest.fixture
def agno_logs():
    """Every line the agno logger writes during the test, as (level, message)."""
    lines = []

    class _Capture(logging.Handler):
        def emit(self, record):
            lines.append((record.levelno, record.getMessage()))

    logger = logging.getLogger("agno")
    handler = _Capture()
    logger.addHandler(handler)
    yield lines
    logger.removeHandler(handler)


def _about_roles(lines):
    """The lines an operator sees (info and above) that speak of roles or the roles API."""
    return [
        message
        for level, message in lines
        if level >= logging.INFO and ("role" in message.lower() or "authz" in message.lower())
    ]


# ----------------------------------------------------------------- the Role object and the scope lists


def test_a_role_keeps_its_own_copy_of_the_scope_lists():
    member = Role("member", scopes=READ + RUN, name="Member", description="Runs the agents")
    assert member.id == "member" and member.scopes == READ + RUN
    assert (member.name, member.description) == ("Member", "Runs the agents")
    shared = Role("shared", scopes=READ)
    shared.scopes.append("knowledge:read")
    assert "knowledge:read" not in READ


@pytest.mark.parametrize("role_id", ["", None])
def test_a_role_needs_an_id(role_id):
    with pytest.raises(ValueError, match="non-empty id"):
        Role(role_id, scopes=READ)


def test_a_role_refuses_one_string_as_its_scopes():
    with pytest.raises(TypeError, match="list of scopes"):
        Role("member", scopes="agents:read")


def test_the_lists_hold_the_agreed_scopes():
    assert READ == ["agents:read", "teams:read", "workflows:read", "sessions:read"]
    assert RUN == ["agents:run", "teams:run", "workflows:run", "sessions:write"]
    for component_id, resource in MANAGER_RESOURCES.items():
        family = resource.split("/")[0]
        assert f"{family}:{component_id}:read" in PLATFORM and f"{family}:{component_id}:run" in PLATFORM
    for resource in ("products", "projects", "tasks", "sources", "routines", "schedules", "components"):
        assert {f"{resource}:read", f"{resource}:write", f"{resource}:delete"} <= set(PLATFORM)
    for scope in ("company:read", "company:write", "wiki:read", "wiki:write", "decisions:read", "decisions:write"):
        assert scope in PLATFORM
    assert "registry:read" in PLATFORM and "config:read" in PLATFORM
    everything = READ + RUN + PLATFORM
    assert "agent_os:admin" not in everything and "sessions:delete" not in everything
    assert len(set(everything)) == len(everything)


def test_every_listed_scope_is_one_the_os_enforces_and_a_role_can_hold():
    enforced = {scope for required in get_default_scope_mappings(company=True).values() for scope in required}
    built_ins = {component_id for component_id in MANAGER_RESOURCES}
    for scope in READ + RUN + PLATFORM:
        scope_to_resource_action(scope)  # raises on a scope the role store would refuse
        parts = scope.split(":")
        if len(parts) == 3:
            assert parts[1] in built_ins, scope
            scope = f"{parts[0]}:{parts[2]}"
        assert scope in enforced, scope


# ----------------------------------------------------------------- Authorization(roles=[...])


@pytest.mark.parametrize("own_db", [True, False])
def test_roles_argument_defines_the_roles(tmp_path, own_db):
    db = _db(tmp_path)
    member, platform = _roles()
    member.name, member.description = "Member", "Runs the agents"
    authz = _verified(db=db if own_db else None, roles=[member, platform])
    _os(db, authz)
    assert authz.list_roles() == ["member", "platform"]
    assert authz.get_role_scopes("member") == sorted(READ + RUN)
    assert set(authz.get_role_scopes("platform")) == set(READ + RUN + PLATFORM)
    record = authz.get_role("member")
    assert (record["name"], record["description"], record["is_default"]) == ("Member", "Runs the agents", False)


def test_roles_argument_refuses_a_duplicate_and_a_non_role():
    member, _ = _roles()
    with pytest.raises(ValueError, match="'member' twice"):
        _verified(roles=[member, Role("member", scopes=READ)])
    with pytest.raises(TypeError, match="takes Role objects"):
        _verified(roles=["member"])


def test_define_role_and_its_default_flag_work_as_before(tmp_path):
    db = _db(tmp_path)
    member, _ = _roles()
    authz = _verified(db=db, roles=[member])
    assert authz.define_role("viewer", ["agents:read"], default=True) is authz
    assert authz.list_roles() == ["member", "viewer"] and authz.default_role() == "viewer"
    # The last default=True wins, as it always has
    authz.define_role("guest", ["agents:read"], default=True)
    assert authz.default_role() == "guest"


def test_a_restart_does_not_overwrite_a_role_edited_through_the_api(tmp_path):
    member, _ = _roles()
    client = TestClient(_os(_db(tmp_path), _verified(roles=[member])).get_app())
    edited = ["agents:read", "knowledge:read"]
    assert client.put("/authz/roles/member/scopes", json={"scopes": edited}, headers=_admin()).status_code == 200

    restarted = _verified(roles=[Role("member", scopes=READ + RUN)])
    _os(_db(tmp_path), restarted)
    assert restarted.get_role_scopes("member") == edited


# ----------------------------------------------------------------- UserDirectory(default_role=...)


@pytest.mark.parametrize("as_object", [True, False])
def test_a_new_user_gets_the_directory_default_role(tmp_path, as_object):
    member, platform = _roles()
    authz = _verified(roles=[member, platform])
    directory = UserDirectory(default_role=member if as_object else "member")
    assert directory.default_role == "member"
    client = TestClient(_os(_db(tmp_path), authz, user_directory=directory).get_app())

    # No scopes on the token: the role alone decides
    assert client.get("/agents/research", headers=_auth("alice@example.com")).status_code == 200
    assert authz.roles_of("alice@example.com") == ["member"] and authz.default_role() == "member"
    # member has no platform access
    assert client.get("/config", headers=_auth("alice@example.com")).status_code == 403


def test_a_new_user_gets_no_role_without_a_default(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("agno.os.auth.log_warning", lambda message: warnings.append(message))
    member, platform = _roles()
    authz = _verified(roles=[member, platform])
    agent_os = _os(_db(tmp_path), authz, user_directory=True)
    client = TestClient(agent_os.get_app())

    assert client.get("/agents/research", headers=_auth("alice@example.com")).status_code == 403
    assert agent_os.user_directory.get("alice@example.com") is not None
    assert authz.roles_of("alice@example.com") == [] and authz.default_role() is None
    # A user with no role is a setup that works, so nothing is logged about it
    assert warnings == []


def test_the_default_role_also_decides_for_a_user_added_before_it(tmp_path):
    member, platform = _roles()
    earlier = _os(_db(tmp_path), _verified(roles=[member, platform]), user_directory=True)
    earlier.user_directory.upsert("old@example.com")

    authz = _verified(roles=[member, platform])
    client = TestClient(_os(_db(tmp_path), authz, user_directory=UserDirectory(default_role=member)).get_app())
    assert client.get("/agents/research", headers=_auth("old@example.com")).status_code == 200
    # Decided under the default at request time; nothing is stored for them
    assert authz.roles_of("old@example.com") == []


def test_two_different_defaults_fail_at_startup(tmp_path):
    member, platform = _roles()
    authz = _verified(roles=[member, platform])
    authz.define_role("viewer", ["agents:read"], default=True)
    with pytest.raises(ValueError, match="define_role\\('viewer', default=True\\).*default_role='member'"):
        _os(_db(tmp_path), authz, user_directory=UserDirectory(default_role=member))


def test_the_same_default_in_both_places_is_accepted(tmp_path):
    authz = _verified()
    authz.define_role("member", READ + RUN, default=True)
    _os(_db(tmp_path), authz, user_directory=UserDirectory(default_role="member"))
    assert authz.default_role() == "member"


def test_a_default_role_that_is_not_defined_fails_at_startup(tmp_path):
    member, _ = _roles()
    with pytest.raises(ValueError, match="default_role='support'\\) is not a defined role"):
        _os(_db(tmp_path), _verified(roles=[member]), user_directory=UserDirectory(default_role="support"))


def test_a_default_role_can_be_one_created_through_the_api(tmp_path):
    client = TestClient(_os(_db(tmp_path), _verified(), user_directory=True).get_app())
    assert client.post("/authz/roles", json={"slug": "support"}, headers=_admin()).status_code == 201

    authz = _verified()
    _os(_db(tmp_path), authz, user_directory=UserDirectory(default_role="support"))
    assert authz.default_role() == "support"


def test_a_role_that_grants_admin_cannot_be_the_default(tmp_path):
    admin = Role("admin", scopes=["agent_os:admin"])
    with pytest.raises(RoleChangeRefused, match="cannot be the default role"):
        _os(_db(tmp_path), _verified(roles=[admin]), user_directory=UserDirectory(default_role=admin))


def test_the_default_role_is_ignored_with_authorization_off(tmp_path, agno_logs):
    agent_os = _os(_db(tmp_path), False, user_directory=UserDirectory(default_role="member"))
    client = TestClient(agent_os.get_app())
    # No line is written about the setting, and nothing is checked
    assert _about_roles(agno_logs) == []
    assert client.get("/agents/research").status_code == 200
    assert client.get("/authz/roles").status_code == 404


@pytest.mark.parametrize("setup", ["database", "override"])
def test_a_default_role_with_no_role_store_fails_at_startup(tmp_path, setup):
    directory = UserDirectory(db=_db(tmp_path, "users.db"), default_role="member")
    if setup == "database":
        db, authz = InMemoryDb(), _verified()
    else:
        db, authz = _db(tmp_path), _verified(authorization_provider=ScopeAuthorizationProvider())
    with pytest.raises(ValueError, match="has no role store"):
        _os(db, authz, user_directory=directory)


def test_user_directory_takes_a_role_or_an_id_only():
    with pytest.raises(TypeError, match="takes a Role or a role id"):
        UserDirectory(default_role=["member"])
    with pytest.raises(ValueError, match="needs a role id"):
        UserDirectory(default_role="")
    assert UserDirectory().default_role is None


# ----------------------------------------------------------------- the roles API is on with authorization


@pytest.mark.parametrize("switch", [True, False])
def test_an_admin_creates_and_assigns_a_role_with_none_in_code(tmp_path, switch):
    if switch:
        config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        agent_os = _os(_db(tmp_path), True, authorization_config=config, user_directory=True)
    else:
        agent_os = _os(_db(tmp_path), _verified(), user_directory=True)
    client = TestClient(agent_os.get_app())
    alice = _auth("alice@example.com")

    # The store starts empty, and a user is added with no role
    assert client.get("/authz/roles", headers=_admin()).json()["data"] == []
    assert client.get("/agents/research", headers=alice).status_code == 403
    assert client.get("/users/alice@example.com", headers=_admin()).json()["role_slug"] is None

    assert client.post("/authz/roles", json={"slug": "member"}, headers=_admin()).status_code == 201
    assert client.put("/authz/roles/member/scopes", json={"scopes": READ + RUN}, headers=_admin()).status_code == 200
    assigned = client.post("/authz/subjects/alice@example.com/roles", json={"role": "member"}, headers=_admin())
    assert assigned.json() == {"subject": "alice@example.com", "role": "member"}

    assert client.get("/agents/research", headers=alice).status_code == 200
    assert client.get("/users/alice@example.com", headers=_admin()).json()["role_slug"] == "member"


def test_roles_from_the_start_and_a_new_user_still_gets_none(tmp_path):
    member, platform = _roles()
    client = TestClient(_os(_db(tmp_path), _verified(roles=[member, platform]), user_directory=True).get_app())
    listed = [role["slug"] for role in client.get("/authz/roles", headers=_admin()).json()["data"]]
    assert listed == ["member", "platform"]
    assert client.get("/agents/research", headers=_auth("alice@example.com")).status_code == 403
    assert client.get("/users/alice@example.com", headers=_admin()).json()["role_slug"] is None


def test_the_full_override_gets_no_role_store(tmp_path):
    agent_os = _os(_db(tmp_path), _verified(authorization_provider=ScopeAuthorizationProvider()))
    client = TestClient(agent_os.get_app())
    assert client.app.state.role_store is None
    assert client.get("/authz/roles", headers=_admin()).status_code == 404
    assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 200


@pytest.mark.parametrize("database", ["in_memory", None])
def test_a_database_that_cannot_hold_roles_leaves_token_scopes_to_decide(database, agno_logs):
    db = InMemoryDb() if database else None
    client = TestClient(_os(db, _verified()).get_app())
    # The setup works, so starting it writes nothing about roles
    assert _about_roles(agno_logs) == []
    assert client.app.state.role_store is None
    assert client.get("/authz/roles", headers=_admin()).status_code == 404
    assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 200
    assert client.get("/config", headers=_auth("op@example.com", ["agents:read"])).status_code == 403


class _UnreachableDb(SqliteDb):
    """A database that can hold roles and cannot be read, counting each attempt."""

    reads = 0

    def _get_table(self, *args, **kwargs):
        self.reads += 1
        raise ConnectionError("database is unreachable")


@pytest.mark.parametrize("switch", [True, False])
def test_an_unreachable_database_does_not_stop_an_os_with_no_role_in_code(tmp_path, switch):
    db = _UnreachableDb(db_file=str(tmp_path / "down.db"))
    if switch:
        config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        agent_os = _os(db, True, authorization_config=config, auto_provision_dbs=False)
    else:
        agent_os = _os(db, _verified(), auto_provision_dbs=False)
    app = agent_os.get_app()
    # Building the OS asks the database nothing, and the role store is there for when it is back
    assert db.reads == 0 and app.state.role_store is not None

    with TestClient(app) as client:  # startup runs
        assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 200
        # The role plane cannot answer, so a request the token's scopes do not allow is refused
        assert client.get("/config", headers=_auth("op@example.com", ["agents:read"])).status_code == 403


def test_a_role_in_code_needs_the_database_at_startup(tmp_path):
    member, _ = _roles()
    with pytest.raises(ConnectionError):
        _os(_UnreachableDb(db_file=str(tmp_path / "down.db")), _verified(roles=[member]))


class _UnreadableAtStartup(SqliteDb):
    """A database that holds the roles while AgentOS is built and cannot be read when it starts."""

    def get_authz_policies_for_resources(self, *args, **kwargs):
        raise ConnectionError("database is unreachable")


def test_a_role_in_code_still_fails_startup_when_its_database_cannot_be_read(tmp_path):
    # Only an OS with no role in code starts without its role tables: with roles declared, the
    # startup check on stored policies must be able to read them
    member, _ = _roles()
    app = _os(_UnreadableAtStartup(db_file=str(tmp_path / "os.db")), _verified(roles=[member])).get_app()
    with pytest.raises(ConnectionError):
        with TestClient(app):
            pass


def test_roles_in_code_and_a_default_role_apply_at_startup_on_an_async_database(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    member, platform = _roles()
    agent_os = _os(
        AsyncSqliteDb(db_file=str(tmp_path / "os.db")),
        _verified(roles=[member, platform], trust_token_scopes=True),
        user_directory=UserDirectory(default_role=member),
    )
    with TestClient(agent_os.get_app()) as client:
        roles = {r["slug"]: r for r in client.get("/authz/roles", headers=_admin()).json()["data"]}
        assert roles["member"]["is_default"] is True
        assert {s["raw"] for s in roles["platform"]["scopes"]} == set(READ + RUN + PLATFORM)
        # A new user's first request makes them a member: they can use the agents, not the config
        assert client.get("/agents/research", headers=_auth("dana")).status_code == 200
        assert client.get("/config", headers=_auth("dana")).status_code == 403


def test_a_default_role_that_is_not_defined_stops_startup_on_an_async_database(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    agent_os = _os(
        AsyncSqliteDb(db_file=str(tmp_path / "os.db")),
        _verified(),
        user_directory=UserDirectory(default_role="ghost"),
    )
    with pytest.raises(ValueError, match="is not a defined role"):
        with TestClient(agent_os.get_app()):
            pass


def test_two_default_roles_fail_while_agentos_is_built_on_an_async_database(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    member, platform = _roles()
    authz = _verified(roles=[member]).define_role("platform", platform.scopes, default=True)
    with pytest.raises(ValueError, match="Two default roles are set"):
        _os(AsyncSqliteDb(db_file=str(tmp_path / "os.db")), authz, user_directory=UserDirectory(default_role=member))


def test_a_role_defined_after_agentos_is_built_needs_a_synchronous_database(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    member, _ = _roles()
    authz = _verified(roles=[member])
    _os(AsyncSqliteDb(db_file=str(tmp_path / "os.db")), authz)
    with pytest.raises(ValueError, match="need a synchronous database"):
        authz.define_role("support", READ)


@pytest.fixture
def authz_warnings(monkeypatch):
    """Warnings from the Authorization module. Patched at the call site, since agno's log helpers
    write to whichever agno logger is current and a handler on one of them misses the rest."""
    import agno.os.authz.authorization as authorization_module

    messages = []
    monkeypatch.setattr(authorization_module, "log_warning", messages.append)
    return messages


def _token_scope_warnings(messages):
    return [message for message in messages if "trust_token_scopes unset" in message]


def test_roles_in_code_with_trust_token_scopes_unset_warn_at_startup(tmp_path, authz_warnings):
    member, _ = _roles()
    _os(_db(tmp_path), _verified(roles=[member]))
    assert len(_token_scope_warnings(authz_warnings)) == 1


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(lambda m: _verified(roles=[m], trust_token_scopes=True), id="trust-true"),
        pytest.param(lambda m: _verified(roles=[m], trust_token_scopes=False), id="trust-false"),
        pytest.param(lambda m: _verified(), id="no-role-in-code"),
        pytest.param(lambda m: True, id="bare-switch"),
    ],
)
def test_no_token_scope_warning_when_the_choice_is_explicit_or_no_role_is_in_code(
    tmp_path, authz_warnings, monkeypatch, authorization
):
    monkeypatch.setenv("JWT_VERIFICATION_KEY", SECRET)
    member, _ = _roles()
    _os(_db(tmp_path), authorization(member))
    assert _token_scope_warnings(authz_warnings) == []


def test_a_role_in_code_still_needs_a_database_that_can_hold_it():
    member, _ = _roles()
    with pytest.raises(RuntimeError, match="does not support authorization storage"):
        _os(InMemoryDb(), _verified(roles=[member]))


def test_authorization_does_not_turn_the_user_directory_on(tmp_path):
    member, platform = _roles()
    agent_os = _os(_db(tmp_path), _verified(roles=[member, platform]))
    client = TestClient(agent_os.get_app())
    assert agent_os.user_directory is None and client.app.state.user_store is None
    assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 200
    assert client.get("/users", headers=_admin()).status_code == 404


def test_with_authorization_off_nothing_is_checked(tmp_path):
    agent_os = _os(_db(tmp_path), False, user_directory=True)
    client = TestClient(agent_os.get_app())
    assert client.get("/agents/research").status_code == 200
    assert client.app.state.role_store is None


# ----------------------------------------------------------------- token scopes count beside roles


def test_token_scopes_count_beside_roles_by_default(tmp_path):
    member, platform = _roles()
    authz = _verified(roles=[member, platform])
    assert authz.trust_token_scopes is True
    client = TestClient(_os(_db(tmp_path), authz).get_app())
    # A token with scopes passes on its scopes, with roles defined
    assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 200
    assert client.get("/agents/research", headers=_auth("op@example.com", ["agents:read"])).status_code == 200
    assert client.get("/authz/roles", headers=_admin()).status_code == 200
    # A token with neither a scope nor a role is refused
    assert client.get("/config", headers=_auth("nobody@example.com")).status_code == 403


def test_a_refusal_names_the_role_when_scopes_and_roles_both_decide(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr("agno.os.middleware.jwt.log_warning", lambda message: lines.append(message))
    member, platform = _roles()
    authz = _verified(roles=[member, platform])
    authz.assign("alice@example.com", "member")
    client = TestClient(_os(_db(tmp_path), authz).get_app())

    assert client.get("/config", headers=_auth("alice@example.com", ["agents:read"])).status_code == 403
    assert lines[-1] == (
        "Insufficient scopes for GET /config. Required: ['config:read'], User has: ['agents:read']. "
        "The subject holds role(s) ['member'], which do not authorize GET /config."
    )
    assert client.get("/config", headers=_auth("nobody@example.com")).status_code == 403
    assert lines[-1].endswith("User has: []. The subject holds no role in the role store.")

    # With no role store there is no role to name
    scope_only = TestClient(_os(InMemoryDb(), _verified()).get_app())
    assert scope_only.get("/config", headers=_auth("op@example.com", ["agents:read"])).status_code == 403
    assert lines[-1] == "Insufficient scopes for GET /config. Required: ['config:read'], User has: ['agents:read']"


def test_trust_token_scopes_false_leaves_the_role_store_to_decide(tmp_path):
    member, platform = _roles()
    authz = _verified(roles=[member, platform], trust_token_scopes=False)
    authz.assign("carol@example.com", "platform")
    assert authz.trust_token_scopes is False
    client = TestClient(_os(_db(tmp_path), authz).get_app())
    assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 403
    assert client.get("/authz/roles", headers=_admin()).status_code == 403
    assert client.get("/config", headers=_auth("carol@example.com")).status_code == 200


def test_trust_token_scopes_false_with_no_role_in_code_changes_nothing(tmp_path):
    # A store deciding alone would start empty and refuse everyone, so none is built
    authz = _verified(trust_token_scopes=False)
    client = TestClient(_os(_db(tmp_path), authz).get_app())
    assert authz.uses_roles is False and client.app.state.role_store is None
    assert client.get("/config", headers=_auth("op@example.com", ["config:read"])).status_code == 200
    assert client.get("/authz/roles", headers=_admin()).status_code == 404


@pytest.mark.parametrize("trust, guarded", [(None, True), (False, True), (True, False)])
def test_the_last_admin_guard_turns_off_only_when_trust_is_passed(tmp_path, trust, guarded):
    kwargs = {} if trust is None else {"trust_token_scopes": trust}
    authz = _verified(db=_db(tmp_path), roles=[Role("admin", scopes=["agent_os:admin"])], **kwargs)
    authz.assign("root@example.com", "admin")
    if guarded:
        with pytest.raises(RoleChangeRefused, match="would leave no subject"):
            authz.unassign("root@example.com", "admin")
        assert authz.roles_of("root@example.com") == ["admin"]
    else:
        authz.unassign("root@example.com", "admin")
        assert authz.roles_of("root@example.com") == []


@pytest.mark.parametrize("trust, regranted", [(None, True), (True, False)])
def test_seed_regrants_after_a_lockout_unless_admins_are_on_tokens(tmp_path, trust, regranted):
    kwargs = {} if trust is None else {"trust_token_scopes": trust}
    first = _verified(db=_db(tmp_path), **kwargs)
    first.define_role("admin", ["agent_os:admin"]).define_role("member", READ)
    first.seed(admin="root@example.com")
    # A lockout: the only admin was moved to another role behind the store's back
    first._store()._engine.replace_subject_roles("root@example.com", "member")

    second = _verified(db=_db(tmp_path), **kwargs)
    second.define_role("admin", ["agent_os:admin"]).define_role("member", READ)
    second.seed(admin="root@example.com")
    assert second.roles_of("root@example.com") == (["admin"] if regranted else ["member"])


# ----------------------------------------------------------------- a role counts at the gates that read token scopes
# Scheduling a target, minting a service account token, the job queue and the approval bypass each
# measure the caller themselves. With token scopes trusted, a role must still count beside them.


def _gated(tmp_path):
    authz = _verified(
        roles=[
            Role("admin", scopes=["agent_os:admin"]),
            Role("runner", scopes=READ + RUN + ["schedules:write", "service_accounts:write", "approvals:write"]),
            Role("viewer", scopes=READ + ["schedules:write", "service_accounts:write"]),
        ]
    )
    for subject, role in (("root", "admin"), ("alice", "runner"), ("vic", "viewer")):
        authz.assign(subject, role)
    return authz, TestClient(_os(_db(tmp_path), authz).get_app())


def _schedule(name, endpoint="/agents/research/runs", method="POST"):
    return {"name": name, "cron_expr": "0 9 * * *", "endpoint": endpoint, "method": method, "payload": {}}


def test_a_role_alone_schedules_a_target_it_may_run(tmp_path):
    _, client = _gated(tmp_path)
    # No scopes on these tokens: the stored role decides
    assert client.post("/schedules", json=_schedule("by-role"), headers=_auth("alice")).status_code == 201
    refused = client.post("/schedules", json=_schedule("no-run"), headers=_auth("vic"))
    assert refused.status_code == 403 and "agents:run" in refused.json()["detail"]
    # A token that carries the scopes still schedules, with no role
    scoped = _auth("op", ["schedules:write", "agents:run"])
    assert client.post("/schedules", json=_schedule("by-token"), headers=scoped).status_code == 201
    assert (
        client.post("/schedules", json=_schedule("neither"), headers=_auth("op", ["schedules:write"])).status_code
        == 403
    )


def test_an_endpoint_that_is_not_a_run_still_needs_an_admin_token(tmp_path):
    _, client = _gated(tmp_path)
    body = _schedule("config", endpoint="/config", method="GET")
    assert client.post("/schedules", json=body, headers=_admin()).status_code == 201
    refused = client.post("/schedules", json={**body, "name": "config-2"}, headers=_auth("alice"))
    assert refused.status_code == 403 and "Only admins" in refused.json()["detail"]


def test_a_role_alone_mints_a_token_for_scopes_it_holds(tmp_path):
    _, client = _gated(tmp_path)

    def mint(name, scopes, headers):
        body = {"name": name, "scopes": [{"scope": scope, "effect": "allow"} for scope in scopes]}
        return client.post("/service-accounts", json=body, headers=headers)

    assert mint("reader", ["agents:read"], _auth("vic")).status_code == 201
    refused = mint("runner", ["agents:read", "agents:run"], _auth("vic"))
    assert refused.status_code == 403 and refused.json()["detail"].endswith("you do not hold: agents:run")
    # The token's own scopes and the role add up
    assert mint("both", ["agents:read", "agents:run"], _auth("vic", ["agents:run"])).status_code == 201
    # A token alone still mints what it carries, and no more
    scoped = _auth("op", ["service_accounts:write", "agents:read"])
    assert mint("by-token", ["agents:read"], scoped).status_code == 201
    assert mint("too-much", ["agents:run"], scoped).status_code == 403


def _caller(client, user_id, scopes):
    """A request as the auth middleware leaves it, for the gates that are called as functions."""
    state = SimpleNamespace(user_id=user_id, scopes=scopes, admin_scope=None, claims={}, service_account_name=None)
    return SimpleNamespace(state=state, app=client.app)


@pytest.mark.asyncio
async def test_an_admin_by_role_passes_the_job_queue_gate(tmp_path):
    from fastapi import HTTPException

    from agno.os.routers.job_queue.router import _require_queue_admin

    _, client = _gated(tmp_path)
    await _require_queue_admin(_caller(client, "root", []))  # by role
    await _require_queue_admin(_caller(client, "op", ["agent_os:admin"]))  # by token
    for user_id, scopes in (("alice", []), ("op", ["agents:read"]), ("sa:bot", ["agents:read"])):
        with pytest.raises(HTTPException) as refused:
            await _require_queue_admin(_caller(client, user_id, scopes))
        assert refused.value.status_code == 403


def test_an_approver_by_role_is_an_approval_admin(tmp_path):
    from agno.os.auth import _caller_is_approval_admin

    _, client = _gated(tmp_path)

    def caller(user_id, scopes):
        return _caller(client, user_id, scopes)

    assert _caller_is_approval_admin(caller("alice", []), []) is True  # by role
    assert _caller_is_approval_admin(caller("vic", []), []) is False
    assert _caller_is_approval_admin(caller("op", ["approvals:write"]), ["approvals:write"]) is True  # by token
    # A service account is measured by its own scopes alone
    assert _caller_is_approval_admin(caller("sa:bot", ["agents:read"]), ["agents:read"]) is False


@pytest.mark.asyncio
async def test_a_scope_the_gates_refuse_is_not_granted_by_asking_the_provider(tmp_path):
    from fastapi import HTTPException

    from agno.os.auth import _acaller_is_approval_admin, _caller_is_approval_admin
    from agno.os.routers.job_queue.router import _require_queue_admin

    # "*:*" opens no route and is not the admin scope. The gates measure a token's scopes by their
    # own rule first, so the scopes must not be handed back to the provider, whose scope plane
    # matches more loosely
    _, client = _gated(tmp_path)
    junk = ["service_accounts:write", "*:*"]
    assert client.get("/authz/roles", headers=_auth("mallory", junk)).status_code == 403
    with pytest.raises(HTTPException) as refused:
        await _require_queue_admin(_caller(client, "mallory", junk))
    assert refused.value.status_code == 403
    assert _caller_is_approval_admin(_caller(client, "mallory", junk), junk) is False
    assert await _acaller_is_approval_admin(_caller(client, "mallory", junk), junk) is False
    minted = client.post(
        "/service-accounts",
        json={
            "name": "root-bot",
            "scopes": [{"scope": "agent_os:admin", "effect": "allow"}],
            "allow_privileged_scopes": True,
        },
        headers=_auth("mallory", junk),
    )
    assert minted.status_code == 403, minted.text


@pytest.mark.asyncio
async def test_the_gates_ask_a_role_store_on_an_async_database(tmp_path, agno_logs):
    from httpx import ASGITransport, AsyncClient

    from agno.db.sqlite import AsyncSqliteDb
    from agno.os.auth import _acaller_is_approval_admin, run_continuation_blocked_reason
    from agno.os.routers.job_queue.router import _require_queue_admin

    # The gates run in async code, so a role store on an async database must be awaited: called
    # synchronously it cannot answer, and a person who holds the access by role is refused
    authz = _verified()
    app = _os(AsyncSqliteDb(db_file=str(tmp_path / "os.db")), authz).get_app()
    await authz.aset_role_scopes("admin", ["agent_os:admin"])
    await authz.aset_role_scopes("runner", READ + RUN + ["service_accounts:write", "approvals:write"])
    await authz.aset_role("root", "admin")
    await authz.aset_role("alice", "runner")
    client = SimpleNamespace(app=app)

    await _require_queue_admin(_caller(client, "root", []))
    assert await _acaller_is_approval_admin(_caller(client, "alice", []), []) is True

    # The continue gate: a run waiting on an admin approval is continued only by an approval admin
    async def pending(**kwargs):
        return [{"id": "approval-1"}], 1

    waiting = SimpleNamespace(get_approvals=pending)
    for user_id, blocked in (("alice", False), ("root", False), ("nobody", True)):
        reason = await run_continuation_blocked_reason(
            waiting, "run-1", authorization_enabled=True, user_scopes=[], request=_caller(client, user_id, [])
        )
        assert (reason is not None) is blocked, user_id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        minted = await http.post(
            "/service-accounts",
            json={"name": "reader", "scopes": [{"scope": "agents:read", "effect": "allow"}]},
            headers=_auth("alice"),
        )
    assert minted.status_code == 201, minted.text
    assert not [message for _, message in agno_logs if "treating as abstain" in message]


class _AllowsEverything(AuthorizationProvider):
    """A custom plane that says yes to every caller it is asked about."""

    def check(self, ctx):
        return True

    def accessible_resource_ids(self, ctx):
        return {"*"}


def test_a_service_account_is_measured_by_its_own_scopes_alone(tmp_path):
    from agno.os.auth import _caller_is_approval_admin, planes_beside_token_scopes

    # Two planes: token scopes, and a custom one that allows everything
    planes = [ScopeAuthorizationProvider(), _AllowsEverything()]
    client = TestClient(_os(_db(tmp_path), _verified(authorization_provider=planes)).get_app())
    person = _caller(client, "alice", [])
    service_account = _caller(client, "sa:bot", ["agents:read"])
    assert planes_beside_token_scopes(person) is True
    assert _caller_is_approval_admin(person, []) is True
    # The other plane is not asked about a service account, and a role cannot be given to one
    assert planes_beside_token_scopes(service_account) is False
    assert _caller_is_approval_admin(service_account, ["agents:read"]) is False
    (tmp_path / "roles").mkdir()
    authz, _ = _gated(tmp_path / "roles")
    with pytest.raises(ValueError, match="reserved server principal"):
        authz.assign("sa:bot", "admin")


# ----------------------------------------------------------------- the template setup, end to end


def test_an_admin_moves_a_user_to_platform_and_it_applies_on_the_next_request(tmp_path):
    member, platform = _roles()
    authz = _verified(roles=[member, platform])
    client = TestClient(_os(_db(tmp_path), authz, user_directory=UserDirectory(default_role=member)).get_app())
    alice = _auth("alice@example.com")

    assert client.get("/agents/research", headers=alice).status_code == 200
    assert client.get("/config", headers=alice).status_code == 403

    moved = client.post("/authz/subjects/alice@example.com/roles", json={"role": "platform"}, headers=_admin())
    assert moved.json() == {"subject": "alice@example.com", "role": "platform"}
    # The same token, on the next request
    assert client.get("/config", headers=alice).status_code == 200
    assert authz.roles_of("alice@example.com") == ["platform"]

    # The off switch refuses the user everywhere, and a token with scopes too
    assert client.patch("/users/alice@example.com", json={"disabled": True}, headers=_admin()).status_code == 200
    assert client.get("/agents/research", headers=alice).status_code == 403
    scoped = _auth("alice@example.com", ["agents:read"])
    assert client.get("/agents/research", headers=scoped).json()["detail"] == "User is disabled"


# ----------------------------------------------------------------- provisioning, sync and async


async def _provision(use_async, users, roles, subject):
    if use_async:
        return await aprovision_user_with_default_role(users, roles, subject, {"email": subject})
    return provision_user_with_default_role(users, roles, subject, {"email": subject})


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_provisioning_without_a_default_role_grants_nothing_and_logs_nothing(tmp_path, monkeypatch, use_async):
    warnings = []
    monkeypatch.setattr("agno.os.auth.log_warning", lambda message: warnings.append(message))
    db = _db(tmp_path)
    roles = _verified(db=db, roles=list(_roles()))
    users = UserDirectory(db=db)

    row = await _provision(use_async, users, roles, "alice@example.com")
    assert row["id"] == "alice@example.com" and row["email"] == "alice@example.com"
    assert roles.roles_of("alice@example.com") == [] and warnings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_provisioning_grants_the_default_role_on_first_creation_only(tmp_path, use_async):
    db = _db(tmp_path)
    roles = _verified(db=db, roles=list(_roles()))
    roles._apply_directory_default("member")
    users = UserDirectory(db=db)

    await _provision(use_async, users, roles, "alice@example.com")
    assert roles.roles_of("alice@example.com") == ["member"]
    # An admin's later change is not undone by the next request
    roles.set_role("alice@example.com", "platform")
    await _provision(use_async, users, roles, "alice@example.com")
    assert roles.roles_of("alice@example.com") == ["platform"]


# ----------------------------------------------------------------- a listing does not read the role store for a token caller


class _CountingPlane(AuthorizationProvider):
    """A second plane that records each time it is asked to filter a listing."""

    def __init__(self, visible=()):
        self.visible = set(visible)
        self.asked = 0

    def check(self, ctx):
        return False

    def accessible_resource_ids(self, ctx):
        return set(self.visible)

    def filter_accessible(self, ctx, resources):
        self.asked += 1
        return [resource for resource in resources if resource.id in self.visible]


async def _filter(use_async, provider, ctx, resources):
    if use_async:
        return await provider.afilter_accessible(ctx, resources)
    return provider.filter_accessible(ctx, resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_a_plane_that_shows_everything_ends_the_listing_early(use_async):
    resources = [SimpleNamespace(id="research"), SimpleNamespace(id="support")]
    second = _CountingPlane(visible={"support"})
    provider = CompositeAuthorizationProvider([ScopeAuthorizationProvider(), second])

    everything = AuthorizationContext(scopes=["agents:read"], resource_type="agents", action="read")
    assert await _filter(use_async, provider, everything, resources) == resources
    assert second.asked == 0

    # A caller the first plane shows only part of still gets the union
    one = AuthorizationContext(scopes=["agents:research:read"], resource_type="agents", action="read")
    assert await _filter(use_async, provider, one, resources) == resources
    assert second.asked == 1
    nothing = AuthorizationContext(scopes=[], resource_type="agents", action="read")
    assert await _filter(use_async, provider, nothing, resources) == [resources[1]]
