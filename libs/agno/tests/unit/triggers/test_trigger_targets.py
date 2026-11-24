"""What a trigger may run, and whose authority its run has when AgentOS checks callers."""

import json
import time

import jwt

from agno.db.schemas.triggers import EVENT_FAILED, EVENT_SUCCESS
from agno.os import Authorization
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY, RunAuthorization, authorization_scope
from agno.team import Team
from agno.triggers import Trigger, TriggerManager
from agno.triggers.source import EVENT_NOTICE
from agno.workflow import Step, Workflow
from tests.unit.triggers.conftest import call, comment_payload, issue_payload

INSTRUCTION = "Triage this issue: label it and comment."


async def test_a_team_is_the_target(make_os):
    def declare(github, agent):
        team = Team(id="triage-team", name="triage-team", members=[agent], model=agent.model)
        on = github.on("issues.opened")
        return [Trigger(name="team-triage", on=on, continue_on="issue_comment.created", team=team, input=INSTRUCTION)]

    os = await make_os(declare)

    assert (await os.deliver(issue_payload())).status_code == 202
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS, row
    assert row["output"]["content"] == "done"

    # The team's leader was given the instruction and the event.
    assert os.model.inputs[0].startswith(INSTRUCTION)
    assert '<event source="github" kind="issues.opened">' in os.model.inputs[0]
    assert os.model.inputs[0].endswith(f"</event>\n{EVENT_NOTICE}")

    run = await os.run(row, target="teams/triage-team")
    assert run["status"] == "COMPLETED"
    assert run["team_id"] == "triage-team"
    assert run["metadata"]["trigger_name"] == "team-triage"
    assert run["metadata"]["event_id"] == row["id"]

    # A reply on the issue is a second run of the team in the same session.
    assert (await os.deliver(comment_payload(), event="issue_comment", delivery="d-2")).status_code == 202
    await os.run_events()
    first, second = await os.events()
    assert second["status"] == EVENT_SUCCESS, second
    assert second["session_id"] == first["session_id"]
    assert second["run_id"] != first["run_id"]
    assert (await os.run(second, target="teams/triage-team"))["session_id"] == first["session_id"]


async def test_a_workflow_is_the_target(make_os):
    def declare(github, agent):
        workflow = Workflow(id="triage-flow", name="triage-flow", steps=[Step(name="triage", agent=agent)])
        on = github.on("issues.opened")
        return [
            Trigger(
                name="flow-triage", on=on, continue_on="issue_comment.created", workflow=workflow, input=INSTRUCTION
            )
        ]

    os = await make_os(declare)

    assert (await os.deliver(issue_payload())).status_code == 202
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS, row
    assert row["output"]["content"] == "done"

    # The workflow's step was given the instruction and the event.
    assert os.model.inputs[0].startswith(INSTRUCTION)
    assert '<event source="github" kind="issues.opened">' in os.model.inputs[0]
    assert os.model.inputs[0].endswith(f"</event>\n{EVENT_NOTICE}")

    run = await os.run(row, target="workflows/triage-flow")
    assert run["status"] == "COMPLETED"
    assert run["workflow_id"] == "triage-flow"
    assert run["metadata"]["trigger_name"] == "flow-triage"
    assert run["metadata"]["event_id"] == row["id"]

    # A reply on the issue is a second run of the workflow in the same session.
    assert (await os.deliver(comment_payload(), event="issue_comment", delivery="d-2")).status_code == 202
    await os.run_events()
    first, second = await os.events()
    assert second["status"] == EVENT_SUCCESS, second
    assert second["session_id"] == first["session_id"]
    assert second["run_id"] != first["run_id"]
    assert (await os.run(second, target="workflows/triage-flow"))["session_id"] == first["session_id"]


# ------------------------------------------------------------------------ AgentOS checks callers

KEY = "trigger-authorization-test-key-at-least-32-characters"


def checked():
    return {"id": "test", "authorization": Authorization(verification_keys=[KEY], algorithm="HS256", audience="test")}


def bearer(scopes):
    claims = {"sub": "alice", "aud": "test", "scopes": scopes, "exp": int(time.time()) + 300}
    return {"Authorization": "Bearer " + jwt.encode(claims, KEY, algorithm="HS256")}


def caller(scopes):
    context = AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"})
    return RunAuthorization(ScopeAuthorizationProvider(), context)


def record_run_requests(os):
    """The headers of every request the executor makes to start a run."""
    sent = []

    async def record(request):
        if request.method == "POST" and request.url.path.endswith("/runs"):
            sent.append(request.headers)

    os.runtime.executor._client.event_hooks = {"request": [record]}
    return sent


def triage(github, agent):
    return [Trigger(name="triage-issues", on=github.on("issues.opened"), agent=agent, input=INSTRUCTION)]


async def test_with_authorization_on_a_signed_delivery_starts_the_run(make_os):
    os = await make_os(triage, os_options=checked())
    sent = record_run_requests(os)

    # Callers are checked: the API refuses a request with no token, and a token decides what it may do.
    assert (await os.client.get("/agents")).status_code == 401
    assert (await os.client.get("/agents", headers=bearer(["agents:read"]))).status_code == 200

    # A delivery carries no token. Its signature is what lets it in.
    assert (await os.deliver(issue_payload(), signature="sha256=" + "0" * 64)).status_code == 403
    assert await os.events() == []
    assert (await os.deliver(issue_payload())).status_code == 202

    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS, row
    assert len(os.model.inputs) == 1
    assert (await os.run(row))["status"] == "COMPLETED"

    # A trigger declared in code was created by no caller, so it saved nobody's authority.
    (headers,) = sent
    assert AUTHORIZATION_HEADER not in headers


async def test_a_trigger_a_caller_created_runs_with_the_authority_it_saved(make_os):
    os = await make_os(lambda github, agent: [], os_options=checked())
    sent = record_run_requests(os)

    # The executor starts the run and then reads it, both with the saved authority: alice holds both rights.
    alice = caller(["agents:engineer:run", "agents:engineer:read"])
    with authorization_scope(lambda: alice):
        stored = await TriggerManager(os.db).acreate(
            name="alice-triage",
            source_id=os.github.id,
            events=["issues.opened"],
            target_type="agent",
            target_id="engineer",
            input=INSTRUCTION,
        )
    assert stored.payload[AUTHORIZATION_KEY] == alice.snapshot()

    assert (await os.deliver(issue_payload())).status_code == 202
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS, row
    assert len(os.model.inputs) == 1

    # The run was started with the authority saved when the trigger was created, marked as unattended.
    (headers,) = sent
    assert json.loads(headers[AUTHORIZATION_HEADER]) == {**alice.snapshot(), "scheduled": True}

    # That authority decides the run, not the executor's own token. The row is pointed at another
    # agent in storage, past the manager's check, and the run is refused: alice may not run it.
    await call(os.db, "update_trigger", stored.id, target_id="other")
    assert (await os.deliver(issue_payload(number=8), delivery="d-2")).status_code == 202
    await os.run_events()
    _, refused = await os.events()
    assert refused["status"] == EVENT_FAILED, refused
    assert refused["status_code"] == 403
    assert refused["run_id"] is None
    assert len(os.model.inputs) == 1
