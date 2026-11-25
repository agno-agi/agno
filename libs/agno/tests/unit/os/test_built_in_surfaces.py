"""Every way to start or read a built-in component asks for it by name.

A wildcard or a type-wide grant does not reach Super Agent, Platform Builder or Mini Agent. Each
test takes one way in: a caller holding only the type-wide grants is refused, and a caller who
also holds the built-in's own scope is let through. The scopes are held on a token, through a
managed role, or by a service account, wherever those take different paths.
"""

import itertools
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.company.scheduler import CompanyScheduleExecutor
from agno.os.authz import Authorization
from agno.registry._reserved import BUILDER_ID, MANAGER_RESOURCES, MANAGER_TEAM_ID, MINI_AGENT_ID
from agno.run.authorization import AUTHORIZATION_KEY

from .test_built_in_wildcards import ROUTINE_SCOPES, _auth, _FixtureModel, _Routines, _System

# The type-wide grants, in both spellings. None of them names a built-in.
PLAIN = [
    "agents:read",
    "agents:run",
    "teams:read",
    "teams:run",
    "agents:*:read",
    "agents:*:run",
    "teams:*:read",
    "teams:*:run",
]
# Each built-in by name, to read and to run
NAMED = [
    f"{resource.split('/')[0]}:{component_id}:{action}"
    for component_id, resource in MANAGER_RESOURCES.items()
    for action in ("read", "run")
]
PLANES = ["token", "role", "service_account"]
SCHEDULES = ["schedules:read", "schedules:write"]


class _Surfaces(_System):
    """The AgentOS of the wildcard tests, with callers who hold any list of scopes."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self._names = itertools.count(1)

    def _subject(self, by, scopes, name=None):
        """A subject and the scopes on its token. Through a managed role the token carries none."""
        name = name or f"caller{next(self._names)}"
        subject = f"{name}@example.com"
        if by == "role":
            self.authz.set_role_scopes(name, scopes, actor="test")
            self.authz.set_role(subject, name)
            return subject, []
        return subject, list(scopes)

    def holding(self, by, scopes, name=None):
        """Headers for a caller holding these scopes on a token, through a role or as a service account."""
        if by == "service_account":
            body = {
                "name": name or f"caller{next(self._names)}",
                "scopes": [{"scope": scope, "effect": "allow"} for scope in scopes],
                "allow_privileged_scopes": True,
            }
            admin = _auth("root@example.com", ["agent_os:admin"])
            response = self.client.post("/service-accounts", json=body, headers=admin)
            assert response.status_code == 201, response.text
            return {"Authorization": f"Bearer {response.json()['token']}"}
        return _auth(*self._subject(by, scopes, name))

    def mcp_request(self, by, scopes):
        """What an MCP tool call sees of a caller holding these scopes."""
        subject, token_scopes = self._subject(by, scopes)
        if by == "service_account":
            subject = "sa:caller"
        state = SimpleNamespace(
            authenticated=True,
            authorization_enabled=True,
            user_id=subject,
            claims={"sub": subject},
            scopes=token_scopes,
            admin_scope="agent_os:admin",
        )
        if by == "service_account":
            state.service_account_name = "caller"
        return SimpleNamespace(app=self.app, scope={}, headers={}, state=state)

    def serve(self, interface):
        """Add an interface, and build the app again so it is served."""
        self.os.interfaces.append(interface)
        self.app = self.os.get_app()
        self.client = TestClient(self.app)
        return self.app

    def schedule(self, headers, endpoint, name="nightly"):
        body = {"name": name, "cron_expr": "0 9 * * 1", "endpoint": endpoint, "payload": {"message": "hi"}}
        return self.client.post("/schedules", json=body, headers=headers)

    def save_scopes(self, schedule_id, scopes):
        """Store a schedule's authority as it is saved for an author whose token carried these scopes."""
        row = self.db.get_schedule(schedule_id)
        saved = {**row["payload"][AUTHORIZATION_KEY]}
        saved["context"] = {**saved["context"], "scopes": list(scopes)}
        self.db.update_schedule(schedule_id, payload={**row["payload"], AUTHORIZATION_KEY: saved})

    def scheduler(self, client):
        """The scheduler of this AgentOS: it calls the schedule's endpoint with the internal service token."""
        executor = CompanyScheduleExecutor(
            company_db=self.db,
            schedule_db=self.db,
            base_url="http://test",
            internal_service_token=self.os._internal_service_token,
            poll_interval=0.01,
            timeout=10,
        )
        executor._client = client
        return executor

    async def fire(self, schedule_id, **stored):
        """Fire one schedule as the scheduler does, with any stored fields replaced. The run record it writes."""
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as client:
            executor = self.scheduler(client)
            row = {**self.db.get_schedule(schedule_id), **stored}
            return await executor.execute(row, self.db, release_schedule=False)


@pytest.fixture
def system(tmp_path):
    return _Surfaces(tmp_path)


def _let_through(response):
    """The request passed authorization: whatever the route answered, it was not a refusal."""
    return response.status_code not in (401, 403)


# ----------------------------------------------------------------- continue and cancel over REST


@pytest.mark.parametrize("by", PLANES)
@pytest.mark.parametrize("path", [f"/teams/{MANAGER_TEAM_ID}", f"/agents/{MINI_AGENT_ID}"])
def test_continuing_or_cancelling_a_built_in_run_needs_it_by_name(system, by, path):
    plain, named = system.holding(by, PLAIN), system.holding(by, PLAIN + NAMED)
    paused = {"tools": "[]", "session_id": "no-session", "stream": "false"}
    assert system.client.post(f"{path}/runs/no-run/continue", data=paused, headers=plain).status_code == 403
    assert system.client.post(f"{path}/runs/no-run/cancel", headers=plain).status_code == 403
    # Named, both requests reach the route, which answers for a run it does not have
    assert system.client.post(f"{path}/runs/no-run/continue", data=paused, headers=named).status_code == 404
    assert _let_through(system.client.post(f"{path}/runs/no-run/cancel", headers=named))
    # The type-wide grant still continues and cancels the runs of every other component
    assert system.client.post("/teams/support/runs/no-run/continue", data=paused, headers=plain).status_code == 404
    assert _let_through(system.client.post("/teams/support/runs/no-run/cancel", headers=plain))


# ----------------------------------------------------------------- the MCP tools


MCP_CALLS = [
    ("run_team", {"team_id": MANAGER_TEAM_ID, "message": "hi"}),
    ("run_agent", {"agent_id": MINI_AGENT_ID, "message": "hi"}),
    ("continue_run", {"team_id": MANAGER_TEAM_ID, "run_id": "no-run", "session_id": "no-session"}),
    ("continue_run", {"agent_id": MINI_AGENT_ID, "run_id": "no-run", "session_id": "no-session"}),
    ("cancel_run", {"team_id": MANAGER_TEAM_ID, "run_id": "no-run"}),
    ("cancel_run", {"agent_id": MINI_AGENT_ID, "run_id": "no-run"}),
]


async def _mcp_answers(system, monkeypatch, request, calls):
    """Call MCP tools as one caller. Each result, or the error the tool raised, as text."""
    from fastmcp import Client
    from fastmcp.exceptions import ToolError
    from fastmcp.server import dependencies

    from agno.os.mcp import build_mcp_server

    monkeypatch.setattr(dependencies, "get_http_request", lambda: request)
    answers = []
    async with Client(build_mcp_server(system.os)) as client:
        for tool, arguments in calls:
            try:
                answers.append(str(await client.call_tool(tool, arguments)))
            except ToolError as error:
                answers.append(str(error))
    return answers


@pytest.mark.asyncio
@pytest.mark.parametrize("by", PLANES)
async def test_the_mcp_tools_need_a_built_in_by_name(system, monkeypatch, by):
    pytest.importorskip("fastmcp")
    refused = await _mcp_answers(system, monkeypatch, system.mcp_request(by, PLAIN), MCP_CALLS)
    assert all("Insufficient permissions" in answer for answer in refused), refused

    answers = await _mcp_answers(system, monkeypatch, system.mcp_request(by, PLAIN + NAMED), MCP_CALLS)
    assert not any("Insufficient permissions" in answer for answer in answers), answers
    # Super Agent ran. A cancellation is recorded, except for a service account, which may only
    # cancel a run in a session of its own and is told so.
    assert "answer" in answers[0]
    if by != "service_account":
        assert all("cancellation requested" in answer for answer in answers[4:])

    # The type-wide grant still runs every other component
    ordinary = [("run_team", {"team_id": "support", "message": "hi"})]
    assert "answer" in (await _mcp_answers(system, monkeypatch, system.mcp_request(by, PLAIN), ordinary))[0]


# ----------------------------------------------------------------- A2A


@pytest.mark.parametrize("by", PLANES)
def test_a2a_over_super_agent_needs_it_by_name(system, by):
    from agno.os.interfaces.a2a import A2A

    support = next(team for team in system.os.teams if team.id == "support")
    system.serve(A2A(teams=[system.os.manager, support]))
    message = {"role": "user", "parts": [{"kind": "text", "text": "hi"}], "messageId": "m1", "kind": "message"}
    send = {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": message}}
    get_task = {"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "no-task"}}
    cancel_task = {"jsonrpc": "2.0", "id": "1", "method": "tasks/cancel", "params": {"id": "no-task"}}
    super_agent = f"/a2a/teams/{MANAGER_TEAM_ID}"
    card = "/.well-known/agent-card.json"

    plain = system.holding(by, PLAIN)
    for call in (send, get_task, cancel_task):
        assert system.client.post(super_agent, json=call, headers=plain).status_code == 403
    assert system.client.get(f"{super_agent}{card}", headers=plain).status_code == 403
    # Sending a message and cancelling a task are runs
    runner = system.holding(by, [f"teams:{MANAGER_TEAM_ID}:run"])
    assert system.client.post(super_agent, json=send, headers=runner).status_code == 200
    assert _let_through(system.client.post(super_agent, json=cancel_task, headers=runner))
    # Reading a task and the Agent Card are reads
    reader = system.holding(by, [f"teams:{MANAGER_TEAM_ID}:read"])
    assert _let_through(system.client.post(super_agent, json=get_task, headers=reader))
    assert system.client.get(f"{super_agent}{card}", headers=reader).status_code == 200
    # The type-wide grant still reaches a team that is not built in
    assert system.client.post("/a2a/teams/support", json=send, headers=plain).status_code == 200
    assert system.client.get(f"/a2a/teams/support{card}", headers=plain).status_code == 200


# ----------------------------------------------------------------- Slack


def _slack_over_super_agent(system, **options):
    """Super Agent on Slack. The Slack context, bound to the app."""
    from agno.os.interfaces.slack import Slack

    interface = Slack(
        team=system.os.manager, token="xoxb-test", signing_secret="slack-secret", streaming=False, **options
    )
    return interface.ctx.bind(system.serve(interface))


async def _slack_message(ctx, user, number=1):
    """One Slack message from this user. What was posted in reply, and what the user alone was told."""
    from agno.os.interfaces.slack.handlers import handle_message

    from .interfaces.conftest import make_async_client_mock, make_event_body

    client = make_async_client_mock()
    body = make_event_body(user=user, ts=f"170000000{number}.000100", event_id=f"Ev{number}")
    await handle_message(body, client, ctx)
    posted = [call.kwargs.get("text") for call in client.chat_postMessage.call_args_list]
    told = [call.kwargs.get("text") for call in client.chat_postEphemeral.call_args_list]
    return posted, told


REFUSED_ON_SLACK = f"Not run: Permission required: teams:{MANAGER_TEAM_ID}:run"


@pytest.mark.asyncio
async def test_a_slack_user_mapped_to_a_principal_needs_super_agent_by_name(system):
    pytest.importorskip("slack_bolt")
    ctx = _slack_over_super_agent(system, users={"U_PLAIN": "alice", "U_NAMED": "bob"})
    system.authz.set_role_scopes("every-team", ["teams:run", "teams:*:run"], actor="test")
    system.authz.set_role_scopes("super-agent", [f"teams:{MANAGER_TEAM_ID}:run"], actor="test")
    system.authz.set_role("alice", "every-team")
    system.authz.set_role("bob", "super-agent")

    assert await _slack_message(ctx, "U_PLAIN", 1) == ([], [REFUSED_ON_SLACK])
    assert await _slack_message(ctx, "U_NAMED", 2) == (["answer"], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("named", [False, True])
async def test_a_slack_default_role_needs_super_agent_by_name(system, named):
    pytest.importorskip("slack_bolt")
    ctx = _slack_over_super_agent(system, default_role="slack-member")
    scopes = [f"teams:{MANAGER_TEAM_ID}:run"] if named else ["teams:run", "teams:*:run"]
    system.authz.set_role_scopes("slack-member", scopes, actor="test")

    assert await _slack_message(ctx, "U_ANYONE") == ((["answer"], []) if named else ([], [REFUSED_ON_SLACK]))


# ----------------------------------------------------------------- schedules

# One caller works on another's schedule in these tests. A service account sees only its own
# schedules, so it is left out; it is checked when it creates one.
SCHEDULE_PLANES = ["token", "role"]


@pytest.mark.parametrize("by", SCHEDULE_PLANES)
def test_repointing_a_schedule_at_a_built_in_needs_it_by_name(system, by):
    plain, named = system.holding(by, SCHEDULES + PLAIN), system.holding(by, SCHEDULES + PLAIN + NAMED)
    created = system.schedule(plain, "/teams/support/runs")
    assert created.status_code == 201, created.text
    path = f"/schedules/{created.json()['id']}"
    for endpoint in (f"/teams/{MANAGER_TEAM_ID}/runs", f"/agents/{MINI_AGENT_ID}/runs"):
        assert system.client.patch(path, json={"endpoint": endpoint}, headers=plain).status_code == 403
        assert system.client.patch(path, json={"endpoint": endpoint}, headers=named).status_code == 200
        # Once it is aimed at a built-in, a change to what it sends asks the same question
        assert system.client.patch(path, json={"payload": {"message": "other"}}, headers=plain).status_code == 403


@pytest.mark.parametrize("by", SCHEDULE_PLANES)
def test_enabling_a_schedule_aimed_at_a_built_in_needs_it_by_name(system, by):
    plain, named = system.holding(by, SCHEDULES + PLAIN), system.holding(by, SCHEDULES + PLAIN + NAMED)
    created = system.schedule(named, f"/teams/{MANAGER_TEAM_ID}/runs")
    assert created.status_code == 201, created.text
    path = f"/schedules/{created.json()['id']}"
    # Disabling grants nothing; enabling puts the built-in back on the scheduler
    assert system.client.post(f"{path}/disable", headers=plain).status_code == 200
    assert system.client.post(f"{path}/enable", headers=plain).status_code == 403
    assert system.client.post(f"{path}/enable", headers=named).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("by", SCHEDULE_PLANES)
async def test_triggering_a_schedule_aimed_at_a_built_in_needs_it_by_name(system, by):
    plain, named = system.holding(by, SCHEDULES + PLAIN), system.holding(by, SCHEDULES + PLAIN + NAMED)
    created = system.schedule(named, f"/teams/{MANAGER_TEAM_ID}/runs")
    assert created.status_code == 201, created.text
    path = f"/schedules/{created.json()['id']}/trigger"
    async with AsyncClient(transport=ASGITransport(app=system.app), base_url="http://test") as client:
        # No scheduler is started in a test, so one is put where the trigger route looks for it
        system.app.state.scheduler_executor = system.scheduler(client)
        assert (await client.post(path, headers=plain)).status_code == 403
        triggered = await client.post(path, headers=named)
    assert triggered.status_code == 200 and triggered.json()["status"] == "success", triggered.text


@pytest.mark.asyncio
@pytest.mark.parametrize("by", SCHEDULE_PLANES)
async def test_a_schedule_aimed_at_super_agent_fires_only_for_an_author_who_holds_it_by_name(system, by):
    author = system.holding(by, SCHEDULES + PLAIN + NAMED, name="author")
    created = system.schedule(author, f"/teams/{MANAGER_TEAM_ID}/runs")
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    assert (await system.fire(schedule_id))["status"] == "success"

    # The author's authority is asked again each time the schedule fires: the scopes saved from
    # their token, or their role as it is now. A type-wide grant does not fire Super Agent.
    if by == "token":
        system.save_scopes(schedule_id, SCHEDULES + PLAIN)
    else:
        system.authz.set_role_scopes("author", SCHEDULES + PLAIN, actor="test")
    refused = await system.fire(schedule_id)
    assert refused["status_code"] == 403 and "Insufficient permissions for scheduled target" in refused["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["author@example.com", None])
@pytest.mark.parametrize(
    "endpoint, built_in",
    [
        (f"/teams/{MANAGER_TEAM_ID}/runs", True),
        ("/teams/superagen%74/runs", True),
        (f"/agents/{MINI_AGENT_ID}/runs", True),
        ("/agents/research/runs", False),
    ],
)
async def test_a_schedule_with_no_saved_authority_does_not_fire_a_built_in(system, endpoint, built_in, owner):
    # Saved while authorization was off, or from code: nobody's authority is left to ask when it fires
    author = system.holding("token", SCHEDULES + PLAIN + NAMED, name="author")
    created = system.schedule(author, endpoint)
    assert created.status_code == 201, created.text
    fired = await system.fire(created.json()["id"], payload={"message": "hi"}, user_id=owner)
    if built_in:
        assert fired["status_code"] == 403 and "Insufficient permissions for scheduled target" in fired["error"]
    else:
        assert fired["status"] == "success", fired


# ----------------------------------------------------------------- Routines


@pytest.mark.parametrize("by", PLANES)
def test_resuming_a_routine_needs_mini_agent_by_name(system, by):
    routines = _Routines(system)
    plain = system.holding(by, ROUTINE_SCOPES + PLAIN)
    named = system.holding(by, ROUTINE_SCOPES + PLAIN + NAMED)
    saved = routines.save("weekly", named)
    assert saved.status_code == 201, saved.text
    path = f"/company/routines/{saved.json()['id']}"
    # Pausing grants nothing; resuming puts Mini Agent back on the scheduler
    assert system.client.post(f"{path}/pause", headers=plain).status_code == 200
    assert system.client.post(f"{path}/resume", headers=plain).status_code == 403
    assert system.client.post(f"{path}/resume", headers=named).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("by", PLANES)
async def test_triggering_a_routine_needs_mini_agent_by_name(system, by):
    routines = _Routines(system)
    plain = system.holding(by, ROUTINE_SCOPES + PLAIN)
    named = system.holding(by, ROUTINE_SCOPES + PLAIN + NAMED)
    saved = routines.save("weekly", named)
    assert saved.status_code == 201, saved.text
    path = f"/company/routines/{saved.json()['id']}/trigger"
    async with AsyncClient(transport=ASGITransport(app=system.app), base_url="http://test") as client:
        # No scheduler is started in a test, so one is put where the trigger route looks for it
        system.app.state.scheduler_executor = system.scheduler(client)
        assert (await client.post(path, headers=plain)).status_code == 403
        triggered = await client.post(path, headers=named)
    assert triggered.status_code == 200 and triggered.json()["status"] == "success", triggered.text


@pytest.mark.parametrize("by", PLANES)
def test_cancelling_a_routine_run_needs_mini_agent_by_name(system, by):
    routines = _Routines(system)
    plain = system.holding(by, ROUTINE_SCOPES + PLAIN)
    named = system.holding(by, ROUTINE_SCOPES + PLAIN + NAMED)
    saved = routines.save("weekly", named)
    assert saved.status_code == 201, saved.text
    routine_id = saved.json()["id"]
    # A run of the Routine that is still going, as the scheduler records one
    now = int(time.time())
    running = {"schedule_id": routine_id, "attempt": 1, "triggered_at": now, "status": "running", "created_at": now}
    system.db.create_schedule_run({**running, "id": "run-record", "run_id": "no-run", "session_id": "no-session"})
    path = f"/company/routines/{routine_id}/cancel"
    assert system.client.post(path, headers=plain).status_code == 403
    assert system.client.post(path, headers=named).status_code == 200


# ----------------------------------------------------------------- the internal service token


@pytest.mark.asyncio
@pytest.mark.parametrize("named", [False, True])
async def test_the_scheduler_fires_with_the_authority_saved_with_the_schedule(system, named):
    # The scheduler calls every endpoint with the internal service token, which holds agents:run
    # and teams:run. That token's own route check names no component, by design: on its own it
    # passes for any agent or team. What decides is the authority saved with the schedule.
    author = system.holding("token", ROUTINE_SCOPES + SCHEDULES + PLAIN + NAMED)
    routine = _Routines(system).save("weekly", author)
    assert routine.status_code == 201, routine.text
    schedule = system.schedule(author, f"/teams/{MANAGER_TEAM_ID}/runs")
    assert schedule.status_code == 201, schedule.text
    if not named:
        for saved in (routine, schedule):
            system.save_scopes(saved.json()["id"], ROUTINE_SCOPES + SCHEDULES + PLAIN)

    on_mini_agent = await system.fire(routine.json()["id"])
    on_super_agent = await system.fire(schedule.json()["id"])
    # A Routine saved with type-wide scopes keeps running on Mini Agent. Super Agent is named, or refused.
    assert on_mini_agent["status"] == "success", on_mini_agent
    if named:
        assert on_super_agent["status"] == "success", on_super_agent
    else:
        assert on_super_agent["status_code"] == 403, on_super_agent
        assert "Insufficient permissions for scheduled target" in on_super_agent["error"]


# ----------------------------------------------------------------- Company Tasks


@pytest.mark.usefixtures("unavailable_manager_docs")
@pytest.mark.parametrize("by", ["token", "role"])
def test_accepting_and_starting_a_task_on_mini_agent_needs_it_by_name(tmp_path, by):
    from .test_mini_agent_tasks import SCOPES as TASK_SCOPES
    from .test_mini_agent_tasks import SECRET as TASK_SECRET
    from .test_mini_agent_tasks import System as TaskSystem
    from .test_mini_agent_tasks import headers as task_headers

    authz = Authorization(verification_keys=[TASK_SECRET], algorithm="HS256")
    system = TaskSystem(tmp_path, authorization=authz)
    try:
        # The Task scopes name Mini Agent. The plain caller holds the type-wide grants in its place.
        named_scopes = list(TASK_SCOPES)
        plain_scopes = [scope for scope in TASK_SCOPES if scope != f"agents:{MINI_AGENT_ID}:run"] + PLAIN

        def caller(user, scopes):
            if by == "role":
                authz.set_role_scopes(f"{user}-role", scopes, actor="test")
                authz.set_role(user, f"{user}-role")
                return [], user
            return scopes, user

        plain, named = caller("plain-user", plain_scopes), caller("named-user", named_scopes)
        task = system.proposal()
        accept = f"/company/tasks/{task['id']}/transitions"
        start = f"/company/tasks/{task['id']}/runs"
        ready = {"target": "ready", "reason": "Approved"}
        on_mini_agent = {"executor_type": "agent", "executor_id": MINI_AGENT_ID}

        # A Task accepted with no executor named runs on Mini Agent
        assert system.client.post(accept, json=ready, headers=task_headers(*plain)).status_code == 403
        assert system.client.post(start, json=on_mini_agent, headers=task_headers(*plain)).status_code == 403
        assert system.client.post(accept, json=ready, headers=task_headers(*named)).status_code == 200
        # Starting a Task someone else accepted asks the starter the same question
        assert system.client.post(start, headers=task_headers(*plain)).status_code == 403
        done = system.execute(task["id"], scopes=named[0], user=named[1])
        assert done["status"] == "in_review" and done["executor_id"] == MINI_AGENT_ID
    finally:
        system.db.close()


# ----------------------------------------------------------------- the file system


@pytest.mark.parametrize("by", PLANES)
def test_the_file_system_of_a_built_in_needs_it_by_name(system, by):
    plain = system.holding(by, ["filesystem:read"] + PLAIN)
    named = system.holding(by, ["filesystem:read"] + PLAIN + NAMED)
    for agent_id in (MINI_AGENT_ID, BUILDER_ID):
        for route in ("/filesystem/files", "/filesystem/entries"):
            assert system.client.get(route, params={"agent_id": agent_id}, headers=plain).status_code == 403
            assert _let_through(system.client.get(route, params={"agent_id": agent_id}, headers=named))


@pytest.mark.parametrize("by", PLANES)
def test_the_file_listing_leaves_a_built_in_out_unless_it_is_named(system, by):
    # An agent of the deployment and Mini Agent each hold one file. Mini Agent has no file system
    # of its own, so it is given one here.
    notes = Agent(id="notes", name="Notes", model=_FixtureModel(), db=system.db, filesystem=True)
    system.os.agents.append(notes)
    system.app = system.os.get_app()
    system.client = TestClient(system.app)
    mini_agent = system.os._mini_agent
    mini_agent.filesystem = True
    notes.filesystem_instance.write("notes/ordinary.md", "ordinary")
    mini_agent.filesystem_instance.write("work/built-in.md", "built in")

    def listed(headers):
        response = system.client.get("/filesystem/files", headers=headers)
        assert response.status_code == 200, response.text
        return sorted(entry["path"] for entry in response.json()["entries"])

    assert listed(system.holding(by, ["filesystem:read"] + PLAIN)) == ["notes/ordinary.md"]
    assert listed(system.holding(by, ["filesystem:read"] + PLAIN + NAMED)) == ["notes/ordinary.md", "work/built-in.md"]


# ----------------------------------------------------------------- the configuration


@pytest.mark.parametrize("by", PLANES)
def test_the_config_leaves_the_built_ins_out_unless_they_are_named(system, by):
    def listed(headers):
        config = system.client.get("/config", headers=headers).json()
        return [agent["id"] for agent in config["agents"]], [team["id"] for team in config["teams"]]

    assert listed(system.holding(by, ["config:read"] + PLAIN)) == (["research"], ["support"])
    # Super Agent is listed for a caller who holds it. Mini Agent is served for the scheduler and
    # Platform Builder is a member of Super Agent: neither is listed for anyone.
    assert listed(system.holding(by, ["config:read"] + PLAIN + NAMED)) == (["research"], ["support", MANAGER_TEAM_ID])


@pytest.mark.asyncio
@pytest.mark.parametrize("by", PLANES)
async def test_the_mcp_config_leaves_the_built_ins_out_unless_they_are_named(system, monkeypatch, by):
    pytest.importorskip("fastmcp")
    from fastmcp import Client
    from fastmcp.server import dependencies

    from agno.os.mcp import build_mcp_server

    async def listed(scopes):
        request = system.mcp_request(by, scopes)
        monkeypatch.setattr(dependencies, "get_http_request", lambda: request)
        async with Client(build_mcp_server(system.os)) as client:
            config = (await client.call_tool("get_agentos_config", {})).structured_content
        return [agent["id"] for agent in config["agents"]], [team["id"] for team in config["teams"]]

    assert await listed(["config:read"] + PLAIN) == (["research"], ["support"])
    assert await listed(["config:read"] + PLAIN + NAMED) == (["research"], ["support", MANAGER_TEAM_ID])


# ----------------------------------------------------------------- evals


@pytest.mark.parametrize("by", PLANES)
def test_an_eval_of_a_built_in_needs_it_by_name(system, by):
    plain = system.holding(by, ["evals:write"] + PLAIN)
    named = system.holding(by, ["evals:write"] + PLAIN + NAMED)
    run = {"eval_type": "performance", "input": "hi", "num_iterations": 1}
    for target in ({"team_id": MANAGER_TEAM_ID}, {"agent_id": MINI_AGENT_ID}):
        assert system.client.post("/eval-runs", json={**run, **target}, headers=plain).status_code == 403
        assert _let_through(system.client.post("/eval-runs", json={**run, **target}, headers=named))
    # The type-wide grant still evaluates every other component
    assert system.client.post("/eval-runs", json={**run, "agent_id": "research"}, headers=plain).status_code == 200
    assert system.client.post("/eval-runs", json={**run, "team_id": MANAGER_TEAM_ID}, headers=named).status_code == 200


# ----------------------------------------------------------------- service account tokens


@pytest.mark.parametrize("by", PLANES)
def test_minting_a_token_for_a_built_in_needs_it_by_name(system, by):
    plain = system.holding(by, ["service_accounts:write"] + PLAIN)
    named = system.holding(by, ["service_accounts:write"] + PLAIN + NAMED)

    def mint(name, scope, headers):
        body = {"name": name, "scopes": [{"scope": scope, "effect": "allow"}]}
        return system.client.post("/service-accounts", json=body, headers=headers)

    # A token can be minted only with scopes its creator holds, and a type-wide grant does not hold a built-in
    for number, scope in enumerate((f"teams:{MANAGER_TEAM_ID}:run", f"agents:{MINI_AGENT_ID}:run")):
        refused = mint(f"refused-{number}", scope, plain)
        assert refused.status_code == 403 and scope in refused.json()["detail"], refused.text
        assert mint(f"minted-{number}", scope, named).status_code == 201
    assert mint("every-team", "teams:run", plain).status_code == 201
