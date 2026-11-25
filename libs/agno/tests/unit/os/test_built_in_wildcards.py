"""A wildcard or type-wide grant never reaches a built-in component.

Super Agent, Platform Builder and Mini Agent are granted by their own scope or by the admin scope.
The rule is the same for scopes on a token and for scopes on a managed role.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.company.manager import CompanyManager
from agno.company.scheduler import CompanyScheduleExecutor
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.auth import INTERNAL_SERVICE_SCOPES
from agno.os.authz import PLATFORM, READ, RUN, Authorization, Role, ScopeAuthorizationProvider
from agno.os.authz._composite import CompositeAuthorizationProvider
from agno.os.authz._scope_policy import resource_matches, scope_to_resource_action
from agno.os.authz.provider import AuthorizationContext
from agno.os.scopes import (
    _built_in_resources,
    accessible_ids_cover,
    built_in_ids,
    get_accessible_resource_ids,
    has_required_scopes,
    is_built_in,
)
from agno.registry._reserved import BUILDER_ID, MANAGER_RESOURCES, MANAGER_TEAM_ID, MINI_AGENT_ID
from agno.run.authorization import AUTHORIZATION_KEY, RunAuthorization
from agno.team import Team

SECRET = "built-in-wildcards-secret-at-least-256-bits-long-xx"
OS_ID = "built-in-wildcards-os"
BUILT_INS = [tuple(resource.split("/")) for resource in MANAGER_RESOURCES.values()]
MEMBER = READ + RUN
PLATFORM_USER = READ + RUN + PLATFORM


class _FixtureModel(Model):
    def __init__(self):
        super().__init__(id="fixture", provider="test")

    def invoke(self, messages, **kwargs):
        return ModelResponse(role="assistant", content="answer", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def _auth(sub, scopes=None):
    payload = {"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600}
    if scopes is not None:
        payload["scopes"] = scopes
    return {"Authorization": "Bearer " + jwt.encode(payload, SECRET, algorithm="HS256")}


class _System:
    """An AgentOS that serves Super Agent, Mini Agent, one agent and one team of its own."""

    def __init__(self, tmp_path, **authorization):
        self.db = SqliteDb(db_file=str(tmp_path / "os.db"))
        self.authz = Authorization(
            verification_keys=[SECRET],
            algorithm="HS256",
            roles=[
                Role("member", scopes=MEMBER),
                Role("platform", scopes=PLATFORM_USER),
                Role("admin", scopes=["agent_os:admin"]),
            ],
            **authorization,
        )
        for subject in ("member", "platform", "admin"):
            self.authz.assign(f"{subject}@example.com", subject)
        research = Agent(id="research", name="Research", model=_FixtureModel())
        self.os = AgentOS(
            id=OS_ID,
            db=self.db,
            agents=[research],
            teams=[Team(id="support", name="Support", members=[research], model=_FixtureModel())],
            manager=OSManager(model=_FixtureModel(), access_docs=False),
            company=CompanyConfig(model=_FixtureModel()),
            authorization=self.authz,
            telemetry=False,
        )
        self.app = self.os.get_app()
        self.client = TestClient(self.app)

    def caller(self, who, by):
        """Headers for a member, a platform user or an admin, holding their access by role or by token."""
        if by == "role":
            return _auth(f"{who}@example.com")
        scopes = {"member": MEMBER, "platform": PLATFORM_USER, "admin": ["agent_os:admin"]}[who]
        return _auth(f"token-{who}@example.com", scopes)

    def run(self, path, headers):
        return self.client.post(path, headers=headers, data={"message": "hi", "stream": "false"})

    def listed(self, path, headers):
        return [item["id"] for item in self.client.get(path, headers=headers).json()]


@pytest.fixture
def system(tmp_path):
    return _System(tmp_path)


# ----------------------------------------------------------------- the two matchers


def test_the_built_ins_are_read_from_the_one_list():
    assert _built_in_resources() == frozenset(MANAGER_RESOURCES.values())
    assert {("teams", MANAGER_TEAM_ID), ("agents", BUILDER_ID), ("agents", MINI_AGENT_ID)} == set(BUILT_INS)
    assert built_in_ids("agents") == {BUILDER_ID, MINI_AGENT_ID} and built_in_ids("workflows") == set()
    assert is_built_in("teams", MANAGER_TEAM_ID) and not is_built_in("agents", MANAGER_TEAM_ID)
    assert not is_built_in("teams", "support") and not is_built_in("teams", None)


@pytest.mark.parametrize("resource_type, resource_id", BUILT_INS)
def test_a_wildcard_policy_row_does_not_match_a_built_in(resource_type, resource_id):
    built_in = f"{resource_type}/{resource_id}"
    assert resource_matches(f"{resource_type}/*", built_in) is False
    # Its own row and the admin wildcard do
    assert resource_matches(built_in, built_in) is True
    assert resource_matches("*", built_in) is True
    # Everything else of the type still matches, and so does the collection itself
    assert resource_matches(f"{resource_type}/*", f"{resource_type}/research") is True
    assert resource_matches(f"{resource_type}/*", f"{resource_type}/*") is True
    # A deny keeps the plain match: a deny on every team still covers Super Agent
    assert resource_matches(f"{resource_type}/*", built_in, grant=False) is True


@pytest.mark.parametrize("action", ["read", "run", "write", "delete"])
@pytest.mark.parametrize("resource_type, resource_id", BUILT_INS)
def test_a_wildcard_token_scope_does_not_match_a_built_in(resource_type, resource_id, action):
    def allowed(scopes, target=resource_id):
        return has_required_scopes(
            scopes, [f"{resource_type}:{action}"], resource_type=resource_type, resource_id=target
        )

    assert allowed([f"{resource_type}:{action}"]) is False
    assert allowed([f"{resource_type}:*:{action}"]) is False
    assert allowed([f"{resource_type}:{resource_id}:{action}"]) is True
    assert allowed(["agent_os:admin"]) is True
    # Both wildcard forms still reach every other component, and the collection
    assert allowed([f"{resource_type}:{action}"], target="research") is True
    assert allowed([f"{resource_type}:*:{action}"], target="research") is True
    assert has_required_scopes([f"{resource_type}:{action}"], [f"{resource_type}:{action}"]) is True


# ----------------------------------------------------------------- the accessible ids, for lists


def test_accessible_ids_from_token_scopes_leave_the_built_ins_out_unless_named():
    assert get_accessible_resource_ids(["teams:read"], "teams") == {"*"}
    assert get_accessible_resource_ids(["teams:*:read"], "teams") == {"*"}
    assert get_accessible_resource_ids(["teams:read", "teams:superagent:read"], "teams") == {"*", "superagent"}
    assert get_accessible_resource_ids(["agent_os:admin"], "teams") == {"*", "superagent"}
    assert get_accessible_resource_ids(["agent_os:admin"], "agents") == {"*", BUILDER_ID, MINI_AGENT_ID}
    assert get_accessible_resource_ids(["agent_os:admin"], "workflows") == {"*"}
    assert get_accessible_resource_ids(["teams:superagent:run"], "teams", action="read") == set()

    assert accessible_ids_cover("teams", "support", {"*"}) is True
    assert accessible_ids_cover("teams", "superagent", {"*"}) is False
    assert accessible_ids_cover("teams", "superagent", {"*", "superagent"}) is True
    assert accessible_ids_cover("teams", "support", {"superagent"}) is False
    assert accessible_ids_cover("agents", "superagent", {"*"}) is True  # an agent of that id is not built in


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_accessible_ids_from_a_role_leave_the_built_ins_out_unless_named(system, use_async):
    engine = system.authz._store()._engine

    async def ids(role, resource_type, action="read"):
        if use_async:
            return await engine.aaccessible_resource_ids(resource_type, action, roles=[role])
        return engine.accessible_resource_ids(resource_type, action, roles=[role])

    assert await ids("member", "teams") == {"*"}
    assert await ids("platform", "teams") == {"*", "superagent"}
    assert await ids("platform", "agents") == {"*", BUILDER_ID, MINI_AGENT_ID}
    assert await ids("admin", "teams") == {"*", "superagent"}
    assert await ids("admin", "workflows") == {"*"}


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_two_planes_add_up_to_a_named_built_in(use_async):
    class _NamesSuperAgent(ScopeAuthorizationProvider):
        def accessible_resource_ids(self, ctx):
            return {"superagent"}

    provider = CompositeAuthorizationProvider([ScopeAuthorizationProvider(), _NamesSuperAgent()])
    ctx = AuthorizationContext(scopes=["teams:read"], resource_type="teams", action="read")
    got = await provider.aaccessible_resource_ids(ctx) if use_async else provider.accessible_resource_ids(ctx)
    # The wildcard from one plane does not swallow the built-in the other names
    assert got == {"*", "superagent"}

    teams = [SimpleNamespace(id="support"), SimpleNamespace(id="superagent")]
    scope_plane = ScopeAuthorizationProvider()
    kept = await scope_plane.afilter_accessible(ctx, teams) if use_async else scope_plane.filter_accessible(ctx, teams)
    assert [team.id for team in kept] == ["support"]


# ----------------------------------------------------------------- over the API, by token and by role


@pytest.mark.parametrize("by", ["token", "role"])
def test_a_member_is_refused_the_built_ins_and_does_not_see_them(system, by):
    member = system.caller("member", by)
    assert system.run("/teams/superagent/runs", member).status_code == 403
    assert system.client.get("/teams/superagent", headers=member).status_code == 403
    assert system.client.get("/agents/miniagent", headers=member).status_code == 403
    assert system.run("/agents/miniagent/runs", member).status_code == 403
    assert system.listed("/teams", member) == ["support"]
    assert system.listed("/agents", member) == ["research"]
    # Everything that is not built in is theirs as before
    assert system.run("/teams/support/runs", member).status_code == 200
    assert system.run("/agents/research/runs", member).status_code == 200
    assert system.client.get("/teams/support", headers=member).status_code == 200


@pytest.mark.parametrize("by", ["token", "role"])
@pytest.mark.parametrize("who", ["platform", "admin"])
def test_a_platform_user_and_an_admin_run_super_agent_and_see_it(system, who, by):
    caller = system.caller(who, by)
    assert system.run("/teams/superagent/runs", caller).status_code == 200
    assert system.client.get("/teams/superagent", headers=caller).status_code == 200
    assert system.listed("/teams", caller) == ["support", "superagent"]
    assert system.run("/teams/support/runs", caller).status_code == 200


@pytest.mark.parametrize("scope", ["teams:run", "teams:*:run"])
def test_a_token_with_a_plain_teams_run_is_refused_super_agent(system, scope):
    assert system.run("/teams/superagent/runs", _auth("op@example.com", [scope])).status_code == 403
    assert system.run("/teams/support/runs", _auth("op@example.com", [scope])).status_code == 200
    named = _auth("op@example.com", ["teams:superagent:run"])
    assert system.run("/teams/superagent/runs", named).status_code == 200


def test_a_deny_on_every_team_still_covers_super_agent(system):
    system.authz.set_role_scopes(
        "restricted", ["teams:superagent:run", {"scope": "teams:*:run", "effect": "deny"}], actor="test"
    )
    system.authz.set_role("restricted@example.com", "restricted")
    assert system.run("/teams/superagent/runs", _auth("restricted@example.com")).status_code == 403


def test_a_service_account_needs_the_built_in_by_name(system):
    admin = _auth("root@example.com", ["agent_os:admin"])

    def mint(name, scopes):
        body = {"name": name, "scopes": [{"scope": scope, "effect": "allow"} for scope in scopes]}
        response = system.client.post("/service-accounts", json=body, headers=admin)
        assert response.status_code == 201, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    plain = mint("plain", ["teams:run", "teams:read"])
    assert system.run("/teams/superagent/runs", plain).status_code == 403
    assert system.run("/teams/support/runs", plain).status_code == 200
    assert system.listed("/teams", plain) == ["support"]
    named = mint("named", ["teams:superagent:run", "teams:superagent:read"])
    assert system.run("/teams/superagent/runs", named).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_a_run_authority_needs_the_built_in_by_name(system, use_async):
    provider = system.client.app.state.authorization_provider

    async def require(authority, resource, resource_id):
        if use_async:
            await authority.arequire(resource, "run", resource_id)
        else:
            authority.require(resource, "run", resource_id)

    member = RunAuthorization(provider, AuthorizationContext(principal_id="member@example.com"))
    platform = RunAuthorization(provider, AuthorizationContext(principal_id="platform@example.com"))
    await require(member, "teams", "support")
    await require(platform, "teams", "superagent")
    await require(platform, "agents", "miniagent")
    for resource, resource_id in (("teams", "superagent"), ("agents", "miniagent"), ("agents", "platform-builder")):
        with pytest.raises(PermissionError, match=f"{resource}:{resource_id}:run"):
            await require(member, resource, resource_id)


# ----------------------------------------------------------------- the scheduler and Routines


class _Routines:
    """Routines on Mini Agent, saved through the API and fired by the real scheduler."""

    def __init__(self, system):
        self.system = system
        self.product = CompanyManager(system.db).create(name="Docs")

    def save(self, name, headers):
        body = {"product_id": self.product["id"], "name": name, "cron_expr": "0 9 * * 1", "instructions": "Review."}
        return self.system.client.post("/company/routines", json=body, headers=headers)

    async def fire(self, routine_id):
        system = self.system
        async with AsyncClient(transport=ASGITransport(app=system.app), base_url="http://test") as client:
            executor = CompanyScheduleExecutor(
                company_db=system.db,
                schedule_db=system.db,
                base_url="http://test",
                internal_service_token=system.os._internal_service_token,
                poll_interval=0.01,
                timeout=10,
            )
            executor._client = client
            result = await executor.execute(system.db.get_schedule(routine_id), system.db, release_schedule=False)
        return "fired" if result["status"] == "success" else (result.get("error") or result["status"])


ROUTINE_SCOPES = ["routines:write", "schedules:write", "products:read", "wiki:read"]


def test_the_scheduler_keeps_its_plain_scopes():
    # Its route check names no component, so the rule does not reach it
    assert "agents:run" in INTERNAL_SERVICE_SCOPES and "teams:run" in INTERNAL_SERVICE_SCOPES
    assert not any(scope.count(":") == 2 for scope in INTERNAL_SERVICE_SCOPES)


@pytest.mark.asyncio
@pytest.mark.parametrize("by", ["token", "role"])
async def test_a_routine_still_runs_on_mini_agent_from_the_scheduler(system, by):
    routines = _Routines(system)
    saved = routines.save("weekly", system.caller("platform", by))
    assert saved.status_code == 201, saved.text
    assert saved.json()["endpoint"] == f"/agents/{MINI_AGENT_ID}/runs"
    assert await routines.fire(saved.json()["id"]) == "fired"


def test_saving_or_editing_a_routine_needs_mini_agent_by_name(system):
    routines = _Routines(system)
    plain = _auth("op@example.com", ROUTINE_SCOPES + ["agents:run", "agents:read"])
    refused = routines.save("weekly", plain)
    assert refused.status_code == 403 and "agents:run" in refused.json()["detail"]

    named = _auth("op@example.com", ROUTINE_SCOPES + ["agents:miniagent:run", "agents:miniagent:read"])
    saved = routines.save("weekly", named)
    assert saved.status_code == 201, saved.text
    # An edit that saves the editor's authority asks the same question
    path = f"/company/routines/{saved.json()['id']}"
    assert system.client.patch(path, json={"instructions": "Review again."}, headers=plain).status_code == 403
    assert system.client.patch(path, json={"instructions": "Review again."}, headers=named).status_code == 200


@pytest.mark.asyncio
async def test_a_routine_saved_with_plain_scopes_keeps_firing(system):
    # As a Routine saved before built-ins needed their own scope is stored: the scopes its
    # author's token carried then, with no built-in named
    routines = _Routines(system)
    saved = routines.save("weekly", system.caller("platform", "token"))
    assert saved.status_code == 201, saved.text
    row = system.db.get_schedule(saved.json()["id"])
    earlier = {**row["payload"][AUTHORIZATION_KEY]}
    earlier["context"] = {**earlier["context"], "scopes": ROUTINE_SCOPES + ["agents:run", "agents:read"]}
    system.db.update_schedule(row["id"], payload={**row["payload"], AUTHORIZATION_KEY: earlier})
    assert await routines.fire(row["id"]) == "fired"

    # Scopes that never covered agents do not fire it
    earlier["context"] = {**earlier["context"], "scopes": ROUTINE_SCOPES}
    system.db.update_schedule(row["id"], payload={**row["payload"], AUTHORIZATION_KEY: earlier})
    assert "Insufficient permissions for scheduled target" in await routines.fire(row["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_only_saved_authority_reaches_mini_agent_on_plain_scopes(system, use_async):
    provider = system.client.app.state.authorization_provider

    def authority(scopes, saved):
        return RunAuthorization(
            provider, AuthorizationContext(principal_id="op@example.com", scopes=scopes), saved=saved
        )

    async def allowed(who, resource, resource_id, action="run"):
        ctx = AuthorizationContext(
            principal_id=who.context.principal_id,
            scopes=who.context.scopes,
            resource_type=resource,
            resource_id=resource_id,
            action=action,
        )
        if use_async:
            return await who.aauthorizes_route(ctx, [f"{resource}:{action}"])
        return who.authorizes_route(ctx, [f"{resource}:{action}"])

    plain = ["agents:run", "agents:read", "teams:run"]
    assert await allowed(authority(plain, saved=False), "agents", MINI_AGENT_ID) is False
    assert await allowed(authority(plain, saved=True), "agents", MINI_AGENT_ID) is True
    assert await allowed(authority(plain, saved=True), "agents", MINI_AGENT_ID, action="read") is True
    assert await allowed(authority(["agents:*:run"], saved=True), "agents", MINI_AGENT_ID) is True
    # Mini Agent only: the other built-ins stay closed to saved authority too
    assert await allowed(authority(plain, saved=True), "teams", MANAGER_TEAM_ID) is False
    assert await allowed(authority(plain, saved=True), "agents", BUILDER_ID) is False
    # A scope for one other agent is not a scope for every agent, and run is not read
    assert await allowed(authority(["agents:research:run"], saved=True), "agents", MINI_AGENT_ID) is False
    assert await allowed(authority(["agents:run"], saved=True), "agents", MINI_AGENT_ID, action="read") is False


def test_saved_scopes_do_not_count_where_the_role_store_decides_alone(tmp_path):
    system = _System(tmp_path, trust_token_scopes=False)
    provider = system.client.app.state.authorization_provider
    plain = AuthorizationContext(
        principal_id="op@example.com",
        scopes=["agents:run"],
        resource_type="agents",
        resource_id=MINI_AGENT_ID,
        action="run",
    )
    assert RunAuthorization(provider, plain, saved=True).authorizes_route(plain, ["agents:run"]) is False


# ----------------------------------------------------------------- what "saved" means, and its limits


def test_a_live_callers_authority_is_not_saved_by_passing_through_the_queue(system):
    from agno.os.authz.run_context import restore_authorization
    from agno.run.authorization import AUTHORIZATION_KEY, authorization_scope, stamp_authorization

    provider = system.client.app.state.authorization_provider
    plain = AuthorizationContext(principal_id="op@example.com", scopes=["agents:run", "teams:superagent:run"])

    def through_the_queue(authority):
        """Stamp the authority on a job as the queue does, then restore it as the worker does."""
        with authorization_scope(lambda: authority):
            job = stamp_authorization({}, include_trusted=True)
        return restore_authorization(system.app, job[AUTHORIZATION_KEY])

    # A run sent with background=true is its caller's own request: it must name Mini Agent
    live = through_the_queue(RunAuthorization(provider, plain))
    assert live.saved is False
    with pytest.raises(PermissionError):
        live.require("agents", "run", MINI_AGENT_ID)
    # An authority loaded from a schedule stays saved when its run is queued
    queued = through_the_queue(RunAuthorization(provider, plain, saved=True))
    assert queued.saved is True
    queued.require("agents", "run", MINI_AGENT_ID)
    # Stored with a schedule, a Routine or an acceptance: the loader says so, whatever the snapshot holds
    stored = RunAuthorization(provider, plain).snapshot()
    assert "saved" not in stored
    assert restore_authorization(system.app, stored).saved is False
    assert restore_authorization(system.app, stored, saved=True).saved is True


@pytest.mark.parametrize("action, reached", [("run", True), ("read", True), ("write", False), ("delete", False)])
def test_saved_plain_scopes_run_and_read_mini_agent_and_nothing_more(system, action, reached):
    provider = system.client.app.state.authorization_provider
    ctx = AuthorizationContext(
        principal_id="op@example.com",
        scopes=[f"agents:{action}"],
        resource_type="agents",
        resource_id=MINI_AGENT_ID,
        action=action,
    )
    assert RunAuthorization(provider, ctx, saved=True).authorizes_route(ctx, [f"agents:{action}"]) is reached


@pytest.mark.parametrize(
    "endpoint", ["/agents/mini%61gent/runs", "/agents/./miniagent/runs", "/agents/miniagent/runs/"]
)
def test_an_encoded_or_padded_endpoint_names_the_same_built_in(system, endpoint):
    from agno.run.authorization import require_schedule_target

    plain = _auth("op@example.com", ["agents:run", "agents:read", "schedules:write"])
    named = _auth("op@example.com", ["agents:run", f"agents:{MINI_AGENT_ID}:run", "schedules:write"])
    body = {"name": "encoded", "cron_expr": "0 9 * * *", "endpoint": endpoint, "payload": {"message": "tick"}}
    assert system.client.post("/schedules", json=body, headers=plain).status_code == 403
    assert system.client.post("/schedules", json=body, headers=named).status_code != 403
    # The same check for a schedule made by a tool
    provider = system.client.app.state.authorization_provider
    from agno.run.authorization import authorization_scope

    authority = RunAuthorization(provider, AuthorizationContext(principal_id="op@example.com", scopes=["agents:run"]))
    with authorization_scope(lambda: authority), pytest.raises(PermissionError):
        require_schedule_target(endpoint)


@pytest.mark.parametrize(
    "held, required, allowed",
    [
        # A route with no id in its path, mapped to one component's scope
        ("teams:run", "teams:superagent:run", False),
        ("teams:*:run", "teams:superagent:run", False),
        ("teams:superagent:run", "teams:superagent:run", True),
        ("agent_os:admin", "teams:superagent:run", True),
        ("teams:run", "teams:support:run", True),
        ("teams:*:run", "teams:support:run", True),
        ("teams:support:run", "teams:support:run", True),
        ("teams:other:run", "teams:support:run", False),
    ],
)
def test_a_required_scope_that_names_a_component_is_read_the_same_by_both_matchers(held, required, allowed):
    from agno.os.scopes import has_required_scopes

    assert has_required_scopes([held], [required], admin_scope="agent_os:admin") is allowed
    # The role matcher, asked about the component the required scope names
    resource, action = scope_to_resource_action(required)
    if held == "agent_os:admin":
        return
    held_resource, held_action = scope_to_resource_action(held)
    assert (held_action == action and resource_matches(held_resource, resource)) is allowed


@pytest.mark.parametrize("by", ["role", "token"])
def test_agui_serving_super_agent_asks_for_it_by_name(tmp_path, by):
    from agno.os.interfaces.agui import AGUI

    system = _System(tmp_path)
    interface = AGUI(team=system.os.manager, prefix="/sa")
    assert interface.get_scope_mappings() == {"POST /sa/agui": [f"teams:{MANAGER_TEAM_ID}:run"]}
    system.os.interfaces.append(interface)
    client = TestClient(system.os.get_app())

    def run(who):
        # Each caller has a thread of their own
        body = {"threadId": f"thread-{who}", "runId": "r1", "state": {}, "messages": [], "tools": [], "context": []}
        return client.post("/sa/agui", json={**body, "forwardedProps": {}}, headers=system.caller(who, by))

    # A member can run every team they built, and not Super Agent through this door either
    assert run("member").status_code == 403
    assert run("platform").status_code == 200
    assert run("admin").status_code == 200


def test_agui_serving_a_team_you_built_keeps_the_type_wide_scope():
    from agno.os.interfaces.agui import AGUI

    team = Team(id="support", name="Support", members=[], model=_FixtureModel())
    assert AGUI(team=team).get_scope_mappings() == {"POST /agui": ["teams:run"]}
