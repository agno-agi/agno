"""TriggerTools: an agent creates and manages triggers on the sources declared in code, with the
refusals of SchedulerTools, and Super Agent holds the toolkit."""

import asyncio
import json
import time

import jwt
import pytest

from agno.agent import Agent
from agno.db.base import ComponentType
from agno.db.schemas.triggers import CODE_MANAGED, EVENT_SUCCESS
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, OSManager
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.interfaces.github import GitHub
from agno.registry import Registry
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, RunAuthorization, authorization_scope
from agno.tools.triggers import TriggerTools
from agno.triggers import Trigger, TriggerManager
from tests.unit.triggers.conftest import REPOSITORY, SECRET, Harness, call, issue_payload

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

INSTRUCTION = "Triage this issue: label it and comment."
KEY = "trigger-tools-test-key-at-least-32-characters-long"


def nothing(github, agent):
    return []


def toolkit(os, **options):
    return TriggerTools(db=os.db, sources=[os.github], os_id=os.agent_os._trigger_os_id, **options)


async def use(tools, tool, use_async, /, *args, **kwargs):
    """Call a tool in its sync or its async form and read its answer."""
    if use_async:
        return json.loads(await getattr(tools, "a" + tool)(*args, **kwargs))
    return json.loads(await asyncio.to_thread(getattr(tools, tool), *args, **kwargs))


def new_trigger(**overrides):
    fields = {
        "name": "triage-issues",
        "source_id": "github",
        "events": ["issues.opened"],
        "target_type": "agent",
        "target_id": "engineer",
        "input": INSTRUCTION,
    }
    fields.update(overrides)
    return fields


@pytest.mark.parametrize("use_async", [False, True])
async def test_an_agent_creates_lists_disables_and_deletes_a_trigger(make_os, use_async):
    os = await make_os(nothing, os_options={"id": "the-os"})
    tools = toolkit(os)

    (source,) = (await use(tools, "list_trigger_sources", use_async))["sources"]
    assert source["id"] == "github" and "issues.opened" in source["event_kinds"]

    created = await use(tools, "create_trigger", use_async, **new_trigger(filters='{"labels": ["Agent"]}'))
    assert created["status"] == "created" and created["enabled"] is True
    assert created["filters"] == {"allow": "members", "labels": ["agent"]}
    stored = await TriggerManager(os.db).aget(created["id"])
    assert stored.os_id == "the-os" and stored.managed_by is None

    listed = await use(tools, "list_triggers", use_async)
    assert listed["count"] == 1 and listed["triggers"][0]["id"] == created["id"]
    assert (await use(tools, "get_trigger", use_async, created["id"]))["input"] == INSTRUCTION

    # Asked for again under the same name, it is changed in place.
    changed = await use(tools, "create_trigger", use_async, **new_trigger(input="Only label it."))
    assert (
        changed["status"] == "updated" and changed["id"] == created["id"] and changed["filters"] == {"allow": "members"}
    )

    # It fires for a matching delivery, and its events can be read back.
    await os.deliver(issue_payload())
    await os.run_events()
    assert os.model.inputs[0].startswith("Only label it.")
    (event,) = (await use(tools, "get_trigger_events", use_async, created["id"]))["events"]
    assert event["status"] == EVENT_SUCCESS and event["run_id"]

    off = await use(tools, "disable_trigger", use_async, created["id"])
    assert off == {"status": "disabled", "id": created["id"], "name": "triage-issues", "enabled": False}
    assert (await use(tools, "list_triggers", use_async, enabled_only=True))["count"] == 0
    assert (await use(tools, "enable_trigger", use_async, created["id"]))["enabled"] is True

    assert await use(tools, "delete_trigger", use_async, created["id"]) == {"status": "deleted", "id": created["id"]}
    assert (await use(tools, "list_triggers", use_async))["count"] == 0
    assert "error" in await use(tools, "get_trigger", use_async, created["id"])


@pytest.mark.parametrize("use_async", [False, True])
async def test_the_refusals_of_schedules_hold_for_triggers(make_os, use_async):
    os = await make_os(nothing)
    tools = toolkit(os)
    os.db.upsert_component("retired", component_type=ComponentType.AGENT, name="Retired")
    os.db.delete_component("retired")
    os.db.upsert_component("unfinished", component_type=ComponentType.AGENT, name="Unfinished")
    os.db.upsert_config("unfinished", config={"name": "Unfinished"})

    async def refused(**overrides):
        return await use(tools, "create_trigger", use_async, **new_trigger(**overrides))

    assert (await refused(source_id="posthog"))["error_type"] == "source_not_declared"
    internal = await refused(target_id=BUILDER_ID)
    assert internal["error_type"] == "target_internal"
    assert internal["error"] == "Manager specialists are internal. Give the trigger Super Agent as its target instead."
    archived = await refused(target_id="retired")
    assert archived["error_type"] == "target_archived" and archived["target_id"] == "retired"
    assert archived["error"] == (
        "Cannot create trigger 'triage-issues': its target agent 'retired' is archived. Restore the component first."
    )
    draft = await refused(target_id="unfinished")
    assert draft["error_type"] == "target_not_published" and "Publish it first." in draft["error"]
    assert (await refused(filters="{not json"))["error"] == "Invalid JSON in filters parameter"
    assert (await refused(filters='{"branch": "main"}'))["error_type"] == "invalid_filters"
    assert "target_type must be one of" in (await refused(target_type="tool"))["error"]
    assert (await call(os.db, "get_triggers"))[1] == 0

    # A stored trigger aimed at such a target is not turned on, and its events are not run again.
    old = await TriggerManager(os.db).acreate(**new_trigger(name="old", target_id=BUILDER_ID), enabled_on_create=False)
    assert (await use(tools, "enable_trigger", use_async, old.id))["error_type"] == "target_internal"
    assert (await use(tools, "replay_trigger_event", use_async, old.id, "te_any"))["error_type"] == "target_internal"
    retired = await TriggerManager(os.db).acreate(**new_trigger(name="retired", target_id="retired"))
    assert (await use(tools, "enable_trigger", use_async, retired.id))["error_type"] == "target_archived"


@pytest.mark.parametrize("use_async", [False, True])
async def test_a_trigger_declared_in_code_is_left_to_the_code(make_os, use_async):
    def in_code(github, agent):
        return [Trigger(name="triage-issues", on=github.on("issues.opened"), agent=agent, input="From code.")]

    os = await make_os(in_code)
    tools = toolkit(os)
    (declared,) = (await use(tools, "list_triggers", use_async))["triggers"]
    assert declared["declared_in_code"] is True

    assert (await use(tools, "create_trigger", use_async, **new_trigger()))["error_type"] == "declared_in_code"
    assert (await use(tools, "delete_trigger", use_async, declared["id"]))["error_type"] == "declared_in_code"
    (kept,) = (await call(os.db, "get_triggers"))[0]
    assert kept["input"] == "From code." and kept["managed_by"] == CODE_MANAGED
    # It can be turned off: a declared trigger keeps its stored state.
    assert (await use(tools, "disable_trigger", use_async, declared["id"]))["enabled"] is False


@pytest.mark.parametrize("use_async", [False, True])
async def test_an_agent_replays_an_event(make_os, use_async):
    os = await make_os(nothing)
    woken = []
    tools = toolkit(os, wake=lambda: woken.append(1))
    created = await use(tools, "create_trigger", use_async, **new_trigger())
    await os.deliver(issue_payload())
    await os.run_events()
    (first,) = await os.events()

    replayed = await use(tools, "replay_trigger_event", use_async, created["id"], first["id"])

    assert replayed["status"] == "pending" and replayed["replayed_event_id"] == first["id"]
    assert woken == [1]
    await os.run_events()
    _, second = await os.events()
    assert second["id"] == replayed["id"] and second["status"] == EVENT_SUCCESS
    assert second["run_id"] != first["run_id"] and len(os.model.inputs) == 2

    # An event still waiting cannot be replayed.
    await os.deliver(issue_payload(number=8), delivery="d-2")
    waiting = (await os.events())[-1]
    refused = await use(tools, "replay_trigger_event", use_async, created["id"], waiting["id"])
    assert refused["error_type"] == "cannot_replay" and "still being handled" in refused["error"]
    assert "error" in await use(tools, "replay_trigger_event", use_async, created["id"], "te_missing")


@pytest.mark.parametrize("use_async", [False, True])
async def test_each_user_has_their_own_triggers(make_os, use_async):
    os = await make_os(nothing)
    tools = toolkit(os)
    alice = RunContext(run_id="run-a", session_id="session-a", user_id="alice")
    bob = RunContext(run_id="run-b", session_id="session-b", user_id="bob")

    mine = await use(tools, "create_trigger", use_async, **new_trigger(), run_context=alice)
    stored = await TriggerManager(os.db).aget(mine["id"])
    assert stored.user_id == "alice"
    assert stored.created_by_run_id == "run-a" and stored.created_by_session_id == "session-a"

    assert (await use(tools, "list_triggers", use_async, run_context=bob))["count"] == 0
    for tool in ("get_trigger", "enable_trigger", "disable_trigger", "delete_trigger", "get_trigger_events"):
        assert "not found" in (await use(tools, tool, use_async, mine["id"], run_context=bob))["error"].lower()
    his = await use(tools, "create_trigger", use_async, **new_trigger(), run_context=bob)
    assert his["status"] == "created" and his["id"] != mine["id"]
    assert (await use(tools, "list_triggers", use_async, run_context=alice))["triggers"][0]["id"] == mine["id"]


def caller(scopes):
    context = AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"})
    return RunAuthorization(ScopeAuthorizationProvider(), context)


@pytest.mark.parametrize("use_async", [False, True])
async def test_a_trigger_an_agent_creates_saves_its_callers_authority(make_os, use_async):
    os = await make_os(nothing)
    tools = toolkit(os)

    # Without the right to write triggers the tool is refused before it does anything.
    with authorization_scope(lambda: caller(["triggers:read", "agents:engineer:run"])):
        with pytest.raises(PermissionError, match="triggers:write"):
            await use(tools, "create_trigger", use_async, **new_trigger()) if use_async else tools.create_trigger(
                **new_trigger()
            )
    # The right to write triggers is not the right to run the target.
    with authorization_scope(lambda: caller(["triggers:write"])):
        refused = (
            await use(tools, "create_trigger", use_async, **new_trigger())
            if use_async
            else json.loads(tools.create_trigger(**new_trigger()))
        )
    assert "agents:engineer:run" in refused["error"]
    assert (await call(os.db, "get_triggers"))[1] == 0

    alice = caller(["triggers:write", "agents:engineer:run"])
    with authorization_scope(lambda: alice):
        created = (
            await use(tools, "create_trigger", use_async, **new_trigger())
            if use_async
            else json.loads(tools.create_trigger(**new_trigger()))
        )
    assert created["status"] == "created"
    stored = await TriggerManager(os.db).aget(created["id"])
    assert stored.payload[AUTHORIZATION_KEY] == alice.snapshot()
    # What the caller may do is saved with the trigger and never shown.
    assert "payload" not in created and AUTHORIZATION_KEY not in json.dumps(created)


# ------------------------------------------------------------------------------------ Super Agent


class ScriptedModel(Model):
    """Calls one tool, then answers with what the tool returned. With no tool it answers at once."""

    def __init__(self, tool=None, arguments=None):
        super().__init__(id="fixture", provider="test")
        self.tool = tool
        self.arguments = arguments or {}

    def invoke(self, messages, **kwargs):
        if self.tool and messages[-1].role != "tool":
            call_ = {
                "id": "call",
                "type": "function",
                "function": {"name": self.tool, "arguments": json.dumps(self.arguments)},
            }
            return ModelResponse(role="assistant", tool_calls=[call_], response_usage=MessageMetrics())
        content = str(messages[-1].content) if self.tool else "allowed target ran"
        return ModelResponse(role="assistant", content=content, response_usage=MessageMetrics())

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


@pytest.fixture
async def with_super_agent(database):
    """An AgentOS with Super Agent, a GitHub source, and callers checked by token."""
    import httpx

    built = []

    async def build(model=None, sources=True, **options):
        db = database()
        github = GitHub(repositories=REPOSITORY, webhook_secret=SECRET)
        target = Agent(id="allowed", name="allowed", model=ScriptedModel())
        agent_os = AgentOS(
            id="test",
            db=db,
            telemetry=False,
            agents=[target],
            interfaces=[github] if sources else [],
            registry=Registry(models=[ScriptedModel()]),
            manager=OSManager(model=model or ScriptedModel()),
            **options,
        )
        app = agent_os.get_app()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        if agent_os._trigger_runtime is not None:
            executor = agent_os._trigger_runtime.executor
            executor._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30)
            executor.poll_interval = 0.02
        harness = Harness(agent_os=agent_os, app=app, db=db, github=github, model=None, client=client)  # type: ignore[arg-type]
        built.append(harness)
        return harness

    yield build
    for harness in built:
        if harness.agent_os._trigger_runtime is not None:
            await harness.runtime.poller.stop()
        await harness.client.aclose()


def builder_trigger_tools(agent_os):
    builder = agent_os._manager.builder
    return [tool for tool in builder.tools if isinstance(tool, TriggerTools)]


@pytest.mark.parametrize("use_async", [False, True])
async def test_super_agent_creates_lists_disables_and_deletes_a_trigger(with_super_agent, use_async):
    os = await with_super_agent()
    (tools,) = builder_trigger_tools(os.agent_os)
    assert tools.os_id == "test" and [source.id for source in tools.sources] == ["github"]
    # Deleting a trigger removes its events, so it asks first, as deleting a schedule does.
    assert "delete_trigger" in tools.requires_confirmation_tools

    created = await use(tools, "create_trigger", use_async, **new_trigger(target_id="allowed"))
    assert created["status"] == "created", created
    assert (await use(tools, "list_triggers", use_async))["triggers"][0]["id"] == created["id"]
    assert (await use(tools, "disable_trigger", use_async, created["id"]))["enabled"] is False
    assert (await use(tools, "delete_trigger", use_async, created["id"]))["status"] == "deleted"
    assert (await use(tools, "list_triggers", use_async))["count"] == 0

    # Super Agent itself can be a trigger's target. Its members cannot.
    assert (
        await use(tools, "create_trigger", use_async, **new_trigger(target_type="team", target_id=MANAGER_TEAM_ID))
    )["status"] == "created"
    internal = await use(tools, "create_trigger", use_async, **new_trigger(name="inner", target_id=BUILDER_ID))
    assert internal["error_type"] == "target_internal"


async def test_super_agent_holds_no_trigger_tools_without_a_source(with_super_agent):
    os = await with_super_agent(sources=False)

    assert builder_trigger_tools(os.agent_os) == []


def bearer(scopes, sub="alice"):
    claims = {"sub": sub, "aud": "test", "scopes": scopes, "exp": int(time.time()) + 300}
    return {"Authorization": "Bearer " + jwt.encode(claims, KEY, algorithm="HS256")}


@pytest.mark.parametrize("allowed", [False, True])
async def test_a_trigger_does_not_gain_a_right_its_creator_lacks(with_super_agent, allowed):
    # Super Agent, when it runs, tries to run the agent "allowed".
    os = await with_super_agent(
        model=ScriptedModel("run_agent", {"agent_id": "allowed", "message": "hi"}),
        user_isolation=True,
        authorization=Authorization(verification_keys=[KEY], algorithm="HS256", audience="test"),
    )
    scopes = ["teams:superagent:run", "triggers:write"] + (["agents:allowed:run"] if allowed else [])
    created = await os.client.post(
        "/triggers",
        headers=bearer(scopes),
        json=new_trigger(target_type="team", target_id=MANAGER_TEAM_ID, input="Run the agent."),
    )
    assert created.status_code == 201, created.text
    assert created.json()["payload"] is None

    assert (await os.deliver(issue_payload())).status_code == 202
    await os.run_events()

    # The run acts as the trigger's creator: it may run what the creator could, and nothing more.
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS, row
    expected = "allowed target ran" if allowed else "Permission required: agents:allowed:run"
    assert expected in row["output"]["content"]


# ------------------------------------------------------------------------- found in review


@pytest.mark.parametrize("use_async", [False, True])
async def test_turning_on_and_replaying_need_the_right_to_run_the_target(make_os, use_async):
    os = await make_os(nothing)
    tools = toolkit(os)
    created = await use(tools, "create_trigger", use_async, **new_trigger())
    await os.deliver(issue_payload())
    await os.run_events()
    (event,) = await os.events()
    await use(tools, "disable_trigger", use_async, created["id"])

    async def as_caller(scopes, tool, *args):
        with authorization_scope(lambda: caller(scopes)):
            if use_async:
                return json.loads(await getattr(tools, "a" + tool)(*args))
            return json.loads(getattr(tools, tool)(*args))

    # Whoever may write triggers and may not run the agent can neither turn the trigger on nor
    # run one of its events again: both run the target.
    refused = await as_caller(["triggers:write"], "enable_trigger", created["id"])
    assert "agents:engineer:run" in refused["error"]
    assert (await TriggerManager(os.db).aget(created["id"])).enabled is False
    allowed = await as_caller(["triggers:write", "agents:engineer:run"], "enable_trigger", created["id"])
    assert allowed["status"] == "enabled"

    refused = await as_caller(["triggers:write"], "replay_trigger_event", created["id"], event["id"])
    assert "agents:engineer:run" in refused["error"]
    assert len(await os.events()) == 1
    allowed = await as_caller(
        ["triggers:write", "agents:engineer:run"], "replay_trigger_event", created["id"], event["id"]
    )
    assert allowed["status"] == "pending"


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("target_id", ["platform%2Dbuilder", "x/../platform-builder", "platform-builder/"])
async def test_an_internal_member_is_refused_however_its_id_is_written(make_os, use_async, target_id):
    os = await make_os(nothing)
    tools = toolkit(os)

    refused = await use(tools, "create_trigger", use_async, **new_trigger(target_id=target_id))

    assert refused.get("error_type") in ("target_internal", "invalid_target"), refused
    assert (await call(os.db, "get_triggers"))[1] == 0


@pytest.mark.parametrize("use_async", [False, True])
async def test_the_tools_take_what_the_api_takes(make_os, use_async):
    os = await make_os(nothing)
    tools = toolkit(os)

    async def refused(**overrides):
        answer = await use(tools, "create_trigger", use_async, **new_trigger(**overrides))
        assert "error" in answer, answer
        return answer["error"]

    assert "name" in await refused(name="   ")
    assert "255" in await refused(name="n" * 256)
    assert "input" in await refused(input="  ")
    assert "target_id" in await refused(target_id="")
    assert "1024" in await refused(description="d" * 1025)
    assert "continue_on" in await refused(continue_on=["issue_comment.created", " "])
    assert "events" in await refused(events=["issues.opened", 7])
    assert (await call(os.db, "get_triggers"))[1] == 0

    # What is stored is trimmed, as over the API.
    created = await use(tools, "create_trigger", use_async, **new_trigger(name="  spaced  ", input="  Do it.  "))
    assert created["name"] == "spaced" and created["input"] == "Do it."


@pytest.mark.parametrize("use_async", [False, True])
async def test_a_tool_stores_a_trigger_for_its_own_agentos_only(make_os, use_async):
    first = await make_os(nothing, os_options={"id": "first-os"})
    second = await make_os(nothing, os_options={"id": "second-os"})
    theirs = await use(toolkit(first), "create_trigger", use_async, **new_trigger(input="The first app's."))

    mine = await use(toolkit(second), "create_trigger", use_async, **new_trigger(input="The second app's."))

    # The same name on another AgentOS is another trigger. Nothing of the first app's was changed.
    assert mine["status"] == "created" and mine["id"] != theirs["id"]
    kept = await TriggerManager(first.db).aget(theirs["id"])
    assert kept.os_id == "first-os" and kept.input == "The first app's."
