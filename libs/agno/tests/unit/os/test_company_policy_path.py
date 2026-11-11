"""auto_accept: one switch on a Routine takes its work from a proposal to In review with no person."""

import asyncio
import json
import time

import pytest

from agno.company import CompanyManager, Product, Routine
from agno.company.bootstrap import arehydrate_product
from agno.company.declarations import AutoAccept
from agno.company.execution import _automatic_task, _ExecutorAuthorization
from agno.company.routines import (
    _DECLARED,
    _check_automatic_policy,
    _CompanyScheduleExecutor,
    _open_tasks,
    _policy_fingerprint,
    _RoutineAuthorization,
)
from agno.os.auth import INTERNAL_SCHEDULER_USER_ID
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID, MINI_AGENT_ID
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, RunAuthorization, authorization_scope
from agno.scheduler import ScheduleManager
from agno.tools.company import CompanyTools
from agno.tools.studio import StudioTools
from tests.unit.os.test_mini_agent_tasks import RUN_TOOLS, ScriptedModel, System, headers
from tests.unit.os.test_mini_agent_tasks import SCOPES as TASK_SCOPES

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

SCOPES = [*TASK_SCOPES, "routines:read", "schedules:read"]
FUTURE = 4102444800


class PolicySystem(System):
    def __init__(self, tmp_path, authorization=True):
        super().__init__(tmp_path, **({} if authorization else {"authorization": None}))
        token = self.os._internal_service_token
        self.app.state.internal_service_token = token
        self.executor = _CompanyScheduleExecutor(
            self.os, self.app, base_url="http://test", internal_service_token=token
        )
        self.manager = CompanyManager(self.db, self.os.registry, schedule_db=self.db)

    def declare(self, auto_accept=True, name="intake", product="Docs", trusted=True):
        """A Product with one Routine, as the deployment's own code declares it."""
        routine = Routine(name=name, instructions="Read the Sources and propose work.", auto_accept=auto_accept)
        declaration = Product(id=product.lower(), name=product, routines=[routine])
        row = asyncio.run(
            arehydrate_product(
                self.db, declaration, self.os.registry, schedule_db=self.db, agent_os=self.os, trusted=trusted
            )
        )
        return row["id"], row["metadata"]["routine_ids"][-1]

    def api_routine(self, product_id, policy=None, scopes=None, name="intake"):
        body = {"product_id": product_id, "name": name, "instructions": "Read the Sources and propose work."}
        if policy is not None:
            body["auto_accept"] = policy
        return self.client.post("/company/routines", json=body, headers=headers(SCOPES if scopes is None else scopes))

    def proposes(self, product_id, routine_id, project="Fixes", title="Fix the install page", executor=(None, None)):
        """What a Routine run leaves behind: a proposed Project and a Backlog Task in it."""
        authority = _RoutineAuthorization(None, routine_id=routine_id, product_id=product_id)
        with authorization_scope(lambda: authority):
            proposed = self.manager.create_project(product_id=product_id, name=project)
        task = self.manager.create_task(
            product_id=product_id,
            project_id=proposed["id"],
            title=title,
            brief="Correct the install command on the install page.",
            origin="routine",
            routine_id=routine_id,
            executor_type=executor[0],
            executor_id=executor[1],
        )
        return proposed, task

    def tick(self):
        return asyncio.run(self.executor._tick())

    def run_queued(self, calls=()):
        """Run the Task job the tick queued, as the queue worker does."""
        self.mini.model = ScriptedModel(calls)

        async def run():
            job = await self.queue.store.claim_job(self.queue.worker_id, self.queue.config.lock_grace_seconds)
            assert job is not None
            await self.queue._execute_claimed(job)

        asyncio.run(run())

    def stored(self, routine_id):
        return self.db.get_schedule(routine_id)["payload"]

    def outcome(self, outcomes, record_id):
        return next((item for item in outcomes if record_id in (item.get("task_id"), item.get("project_id"))), None)


@pytest.fixture
def system(tmp_path):
    """A deployment with authorization on. A person sets auto_accept here."""
    value = PolicySystem(tmp_path)
    yield value
    value.db.close()


@pytest.fixture
def open_system(tmp_path):
    """A deployment with authorization off, where a declared auto_accept acts."""
    value = PolicySystem(tmp_path, authorization=False)
    yield value
    value.db.close()


def receipts(record):
    return [
        (entry["target"], entry.get("user_id"), entry["auto_accept"])
        for entry in record["transitions"]
        if entry.get("auto_accept")
    ]


# ----------------------------------------------------------------- one line in a declaration


def test_one_line_takes_a_routines_work_to_in_review_with_no_person(open_system):
    product_id, routine_id = open_system.declare(auto_accept=True)
    payload = open_system.stored(routine_id)
    assert payload["_agno_company_acceptance"] == _DECLARED
    assert payload["metadata"]["auto_accept"] == {
        "executor_type": "agent",
        "executor_id": MINI_AGENT_ID,
        "source_ids": None,
        "work_scope": None,
        "required_checks": ["executor_registered"],
        "limits": None,
        "complete_projects": False,
        "approve_projects": True,
        "max_open": 5,
    }
    project, task = open_system.proposes(product_id, routine_id)

    outcomes = open_system.tick()
    assert open_system.outcome(outcomes, task["id"])["status"] == "accepted", outcomes
    assert open_system.db.get_project(project["id"])["status"] == "active"
    accepted = open_system.db.get_task(task["id"])
    assert (accepted["status"], accepted["executor_type"], accepted["executor_id"]) == (
        "in_progress",
        "agent",
        MINI_AGENT_ID,
    )

    # The Task runs on Mini Agent with no run tools.
    open_system.run_queued([("run_agent", {"agent_id": "writer", "message": "Fix it"})])
    assert not RUN_TOOLS & open_system.mini.model.offered and open_system.writer.model.turns == 0
    assert "This run is a Task." in open_system.mini.model.system

    # Finished work waits In review. Nothing completes it.
    open_system.tick()
    review = open_system.db.get_task(task["id"])
    assert review["status"] == "in_review" and review["result"]["status"] == "COMPLETED"

    # Each automatic step is on the record with the Routine and the policy.
    version = _policy_fingerprint(open_system.db.get_schedule(routine_id))
    receipt = {"routine_id": routine_id, "policy": version, "declared": True}
    assert receipts(open_system.db.get_project(project["id"])) == [("active", None, receipt)]
    assert receipts(review) == [("ready", None, {**receipt, "executor_chosen_by": "policy"})]
    decisions = open_system.manager.auto_accept_status(product_id)["automatic_decisions"]
    assert sorted((item["record"], item["decision"]) for item in decisions) == [
        ("project", "approved"),
        ("task", "accepted"),
    ]
    shown = json.loads(CompanyTools(open_system.db).get_company_product(product_id))
    assert shown["automatic_decisions"] == decisions and "auto_accept_at_limit" not in shown


def test_a_declaration_applies_only_when_the_routine_is_first_created(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert system.stored(routine_id)["metadata"]["auto_accept"] is False
    # Turning it on in code later does not change the stored Routine, and neither does removing it.
    assert system.declare(auto_accept=True) == (product_id, routine_id)
    assert system.stored(routine_id)["metadata"]["auto_accept"] is False
    other_product, other_routine = system.declare(auto_accept=True, product="Other")
    assert system.declare(auto_accept=False, product="Other") == (other_product, other_routine)
    assert system.stored(other_routine)["_agno_company_acceptance"] == _DECLARED


def test_only_the_deployments_own_declarations_carry_a_policy(system):
    with pytest.raises(ValueError, match="Authorize automatic acceptance through the Routine API"):
        system.declare(auto_accept=True, trusted=False)
    body = {"name": "Setup", "routines": [{"name": "intake", "instructions": "Read.", "auto_accept": True}]}
    setup = system.client.post("/company/setup", json=body, headers=headers([*SCOPES, "sources:write"]))
    assert setup.status_code == 422 and "Authorize automatic acceptance through the Routine API" in setup.text
    with pytest.raises(ValueError, match="missing from the registry"):
        system.declare(auto_accept=AutoAccept(executor_type="agent", executor_id="missing"), product="Bad")


def test_a_declared_policy_acts_only_where_authorization_is_off(system):
    product_id, routine_id = system.declare(auto_accept=True)
    project, task = system.proposes(product_id, routine_id)
    # Code cannot give a Routine a caller's grant, so with authorization on the tick accepts nothing.
    outcome = system.outcome(system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "acts only where authorization is off" in outcome["reason"], outcome
    assert system.db.get_task(task["id"])["status"] == "backlog"
    assert system.db.get_project(project["id"])["status"] == "proposed"

    # A person turns it on once. From then on it runs under that person's saved permissions.
    assert turn_on(system, routine_id).startswith("Auto-accept is on")
    system.tick()
    accepted = system.db.get_task(task["id"])
    assert accepted["status"] == "in_progress"
    assert [(target, user, "declared" in receipt) for target, user, receipt in receipts(accepted)] == [
        ("ready", "alice", False)
    ]
    assert receipts(system.db.get_project(project["id"]))[0][1] == "alice"


# ----------------------------------------------------------------- the executor is a default


def test_a_task_runs_on_the_executor_its_proposal_suggests(open_system):
    product_id, routine_id = open_system.declare(auto_accept=True)
    _, suggested = open_system.proposes(
        product_id, routine_id, title="Suggests the writer", executor=("agent", "writer")
    )
    _, plain = open_system.proposes(product_id, routine_id, title="Suggests nothing")
    open_system.tick()
    on_writer, on_default = open_system.db.get_task(suggested["id"]), open_system.db.get_task(plain["id"])
    assert on_writer["executor_id"] == "writer" and on_default["executor_id"] == MINI_AGENT_ID
    assert receipts(on_writer)[0][2]["executor_chosen_by"] == "proposal"
    assert receipts(on_default)[0][2]["executor_chosen_by"] == "policy"


@pytest.mark.parametrize("executor", [("team", MANAGER_TEAM_ID), ("agent", BUILDER_ID), ("agent", "missing")])
def test_a_suggested_executor_that_cannot_run_the_task_waits_for_a_person(open_system, executor):
    product_id, routine_id = open_system.declare(auto_accept=True)
    _, task = open_system.proposes(product_id, routine_id, executor=executor)
    outcome = open_system.outcome(open_system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "cannot run this Task" in outcome["reason"], outcome
    assert open_system.db.get_task(task["id"])["status"] == "backlog"


def legacy(system, product_id, executor_id="writer"):
    """A Routine whose policy was saved through the API before approve_projects existed."""
    policy = {
        "executor_type": "agent",
        "executor_id": executor_id,
        "limits": {"max_acceptances": 5, "expires_at": FUTURE},
    }
    response = system.api_routine(product_id, {**policy, "approve_projects": False}, name="legacy")
    assert response.status_code == 201, response.text
    row = system.db.get_schedule(response.json()["id"])
    saved = {
        key: value
        for key, value in row["payload"]["metadata"]["auto_accept"].items()
        if key not in {"approve_projects", "max_open"}
    }
    payload = {**row["payload"], "metadata": {**row["payload"]["metadata"], "auto_accept": saved}}
    system.db.update_schedule(row["id"], payload=payload)
    return row["id"]


def test_a_policy_saved_before_this_change_keeps_its_rules(system):
    product_id = system.client.post("/company/products", json={"name": "SDK"}, headers=headers(SCOPES)).json()["id"]
    routine_id = legacy(system, product_id)
    project, task = system.proposes(product_id, routine_id)
    _, other = system.proposes(product_id, routine_id, title="Suggests another", executor=("agent", MINI_AGENT_ID))

    # It approves no Project.
    outcome = system.outcome(system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "Project approval is required" in outcome["reason"]
    assert system.db.get_project(project["id"])["status"] == "proposed"

    approved = system.client.post(
        f"/company/projects/{project['id']}/transitions",
        json={"target": "active", "reason": "Approved"},
        headers=headers(SCOPES),
    )
    assert approved.status_code == 200, approved.text
    outcomes = system.tick()
    # Its executor is fixed: a proposal that suggests another waits for a person.
    assert "outside automatic acceptance authorization" in system.outcome(outcomes, other["id"])["reason"]
    accepted = system.db.get_task(task["id"])
    assert accepted["executor_id"] == "writer" and accepted["transitions"][-2]["auto_accept"]["max_acceptances"] == 5


def test_a_policy_saved_before_this_change_keeps_its_version():
    # Versions computed on main, before approve_projects and max_open existed.
    saved = [
        (
            {"executor_type": "agent", "executor_id": "writer", "limits": {"expires_at": FUTURE}},
            "31a16c309b772dc0cc766571e6907da86f6aaf5ff27f85f3e684175727e3afa3",
        ),
        (
            {
                "executor_type": "team",
                "executor_id": "editors",
                "source_ids": ["notes"],
                "work_scope": {"project_ids": ["p1"]},
                "required_checks": ["project_active", "has_source_evidence"],
                "limits": {"max_acceptances": 5, "expires_at": FUTURE},
                "complete_projects": True,
            },
            "1282d7a5a42b2295b9dbde641d54ffa3459821b47a1183f89d76aa31bb8668c6",
        ),
    ]
    for policy, version in saved:
        assert _policy_fingerprint({"payload": {"metadata": {"auto_accept": policy}}}) == version
    # A policy saved after it states both fields, and each is part of its version.
    new = AutoAccept().model_dump()
    versions = {
        _policy_fingerprint({"payload": {"metadata": {"auto_accept": {**new, **change}}}})
        for change in ({}, {"approve_projects": False}, {"max_open": 2})
    }
    assert len(versions) == 3


# ----------------------------------------------------------------- Projects and the bound


def test_approve_projects_off_leaves_each_project_to_a_person(open_system):
    product_id, routine_id = open_system.declare(auto_accept=AutoAccept(approve_projects=False))
    project, task = open_system.proposes(product_id, routine_id)
    outcome = open_system.outcome(open_system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "Project approval is required" in outcome["reason"]
    assert open_system.db.get_project(project["id"])["status"] == "proposed"
    open_system.manager.transition_project(project_id=project["id"], target="active", reason="Approved by a person")
    open_system.tick()
    assert open_system.db.get_task(task["id"])["status"] == "in_progress"
    assert receipts(open_system.db.get_project(project["id"])) == []


def test_only_a_project_the_routine_proposed_is_approved(open_system):
    product_id, routine_id = open_system.declare(auto_accept=True)
    renamed, in_renamed = open_system.proposes(product_id, routine_id, project="Renamed", title="In a renamed Project")
    open_system.manager.update_project(renamed["id"], name="Renamed by a person")
    person = open_system.manager.create_project(product_id=product_id, name="From a person")
    in_person = open_system.manager.create_task(
        product_id=product_id,
        project_id=person["id"],
        title="In a person's Project",
        origin="routine",
        routine_id=routine_id,
    )
    outcomes = open_system.tick()
    for project, task in ((renamed, in_renamed), (person, in_person)):
        assert "Project approval is required" in open_system.outcome(outcomes, task["id"])["reason"]
        assert open_system.db.get_project(project["id"])["status"] == "proposed"
        assert open_system.db.get_task(task["id"])["status"] == "backlog"


def test_the_bound_is_the_routines_open_tasks_and_a_person_makes_room(open_system):
    product_id, routine_id = open_system.declare(auto_accept=AutoAccept(max_open=2))
    tasks = [open_system.proposes(product_id, routine_id, title=f"Task {n}")[1] for n in range(3)]
    outcomes = open_system.tick()
    statuses = [open_system.db.get_task(task["id"])["status"] for task in tasks]
    assert sorted(statuses) == ["backlog", "in_progress", "in_progress"], outcomes
    waiting = next(task for task in tasks if open_system.db.get_task(task["id"])["status"] == "backlog")
    outcome = open_system.outcome(outcomes, waiting["id"])
    assert outcome["status"] == "skipped" and "2 Tasks open, its limit" in outcome["reason"]

    # The Product's status and the list of what needs a decision both say so.
    tools = CompanyTools(open_system.db)
    at_limit = json.loads(tools.get_company_product(product_id))["auto_accept_at_limit"]
    assert [
        (item["routine"], item["open_tasks"], item["max_open"], item["proposals_waiting"]) for item in at_limit
    ] == [("intake", 2, 2, 1)]
    assert json.loads(tools.list_company_tasks(status="backlog"))["auto_accept_at_limit"] == at_limit
    assert json.loads(asyncio.run(tools.alist_company_tasks(status="backlog")))["auto_accept_at_limit"] == at_limit
    assert "auto_accept_at_limit" not in json.loads(tools.list_company_tasks(status="ready"))

    # A failed run leaves its Task In progress, so it still counts as open.
    running = open_system.db.get_task(next(task["id"] for task in tasks if task["id"] != waiting["id"]))
    assert _open_tasks([{**running, "result": {"status": "ERROR"}}], routine_id) == 1
    assert (
        _open_tasks(
            [{**running, "status": "done"}, {**running, "status": "cancelled"}, {**running, "status": "backlog"}],
            routine_id,
        )
        == 0
    )

    # A person cancels one open Task. The next tick accepts the waiting proposal.
    cancelled = open_system.client.post(
        f"/company/tasks/{running['id']}/transitions",
        json={"target": "cancelled", "reason": "Not needed"},
        headers=headers(SCOPES),
    )
    assert cancelled.status_code in (200, 409), cancelled.text
    if cancelled.status_code == 409:
        open_system.db.transition_task(running["id"], "cancelled", "Not needed")
    open_system.tick()
    assert open_system.db.get_task(waiting["id"])["status"] == "in_progress"
    assert "auto_accept_at_limit" in json.loads(tools.get_company_product(product_id))


def test_a_policy_with_limits_keeps_its_lifetime_count_and_gets_no_open_bound(system):
    product_id = system.client.post("/company/products", json={"name": "SDK"}, headers=headers(SCOPES)).json()["id"]
    policy = {"max_open": 1, "limits": {"max_acceptances": 2, "expires_at": FUTURE}}
    routine_id = system.api_routine(product_id, policy).json()["id"]
    tasks = [system.proposes(product_id, routine_id, title=f"Task {n}")[1] for n in range(3)]
    outcomes = system.tick()
    statuses = sorted(system.db.get_task(task["id"])["status"] for task in tasks)
    assert statuses == ["backlog", "in_progress", "in_progress"], outcomes
    assert any("acceptance limit reached" in (item.get("reason") or "") for item in outcomes)
    accepted = next(row for row in (system.db.get_task(task["id"]) for task in tasks) if row["status"] == "in_progress")
    target, user, receipt = receipts(accepted)[0]
    # A person wrote this policy through the API, so it runs under that person's saved permissions.
    assert (target, user, receipt["max_acceptances"]) == ("ready", "alice", 2) and "declared" not in receipt


# ----------------------------------------------------------------- the declared marker


def test_a_person_changing_a_declared_routine_replaces_the_declared_policy(open_system):
    product_id, routine_id = open_system.declare(auto_accept=True)
    _, task = open_system.proposes(product_id, routine_id)
    open_system.tick()
    accepted = open_system.db.get_task(task["id"])
    asyncio.run(_check_automatic_policy(open_system.db, accepted))

    # The Routine API writes the person's own grant, never the declared marker.
    patched = open_system.client.patch(
        f"/company/routines/{routine_id}", json={"instructions": "Read the Sources again."}, headers=headers(SCOPES)
    )
    assert patched.status_code == 200, patched.text
    grant = open_system.stored(routine_id)["_agno_company_acceptance"]
    assert grant != _DECLARED and "declared" not in grant
    # Work the declared policy accepted no longer runs as the deployment.
    with pytest.raises(ValueError, match="changed or revoked"):
        asyncio.run(_check_automatic_policy(open_system.db, accepted))


def test_the_routine_api_cannot_be_given_the_declared_marker(system):
    product_id, routine_id = system.declare(auto_accept=False)
    marker = {"_agno_company_acceptance": _DECLARED}
    body = {"product_id": product_id, "name": "second", "instructions": "Read.", "auto_accept": True}
    assert system.client.post("/company/routines", json={**body, **marker}, headers=headers(SCOPES)).status_code == 422
    assert (
        system.client.post("/company/routines", json={**body, "payload": marker}, headers=headers(SCOPES)).status_code
        == 422
    )
    path = f"/company/routines/{routine_id}"
    assert system.client.patch(path, json={"auto_accept": True, **marker}, headers=headers(SCOPES)).status_code == 422
    assert system.client.patch(path, json={"payload": marker}, headers=headers(SCOPES)).status_code == 422
    created = system.client.post("/company/routines", json=body, headers=headers(SCOPES))
    assert created.status_code == 201, created.text
    assert system.stored(created.json()["id"])["_agno_company_acceptance"]["user_id"] == "alice"
    assert system.client.patch(path, json={"auto_accept": True}, headers=headers(SCOPES)).status_code == 200
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "alice"


def test_the_generic_schedule_routes_cannot_write_the_declared_marker(system):
    product_id, routine_id = system.declare(auto_accept=False)
    scopes = [*SCOPES, "agents:writer:run"]
    payload = {
        "message": "go",
        "metadata": {"auto_accept": AutoAccept().model_dump()},
        "_agno_company_acceptance": _DECLARED,
    }
    created = system.client.post(
        "/schedules",
        json={"name": "plain", "cron_expr": "0 9 * * 1", "endpoint": "/agents/writer/runs", "payload": payload},
        headers=headers(scopes),
    )
    assert created.status_code in (200, 201), created.text
    assert "_agno_company_acceptance" not in (system.db.get_schedule(created.json()["id"])["payload"] or {})
    before = system.db.get_schedule(routine_id)
    refused = system.client.patch(f"/schedules/{routine_id}", json={"payload": payload}, headers=headers(scopes))
    assert refused.status_code == 409 and system.db.get_schedule(routine_id) == before


def test_schedule_manager_writes_cannot_write_the_declared_marker(system):
    product_id, routine_id = system.declare(auto_accept=False)
    schedules = ScheduleManager(system.db)
    row = system.db.get_schedule(routine_id)
    forged = {**row["payload"], "metadata": {**row["payload"]["metadata"], "auto_accept": AutoAccept().model_dump()}}
    schedules.update(routine_id, payload={**forged, "_agno_company_acceptance": _DECLARED})
    assert "_agno_company_acceptance" not in system.stored(routine_id)
    made = schedules.create(
        name="direct", cron="0 9 * * 1", endpoint="/agents/writer/runs", payload={"_agno_company_acceptance": _DECLARED}
    )
    assert "_agno_company_acceptance" not in (system.db.get_schedule(made.id)["payload"] or {})
    # With no grant, the tick accepts nothing for this Routine.
    _, task = system.proposes(product_id, routine_id)
    assert "no human automatic acceptance authorization" in system.outcome(system.tick(), task["id"])["reason"]


def test_platform_builders_schedule_tools_cannot_write_the_declared_marker(system):
    product_id, routine_id = system.declare(auto_accept=True)
    before = system.db.get_schedule(routine_id)
    tools = StudioTools(registry=system.os.registry, db=system.db, schedules=True)
    assert "payload" not in tools.functions["create_schedule"].parameters["properties"]
    assert "payload" not in tools.functions["update_schedule"].parameters["properties"]
    tools.update_schedule(routine_id, message="Accept everything")
    after = system.db.get_schedule(routine_id)
    # The tool either refuses a Company Routine or rewrites its payload without the marker.
    assert after == before or "_agno_company_acceptance" not in after["payload"]


def test_a_chat_made_product_cannot_declare_a_policy(system):
    tools = CompanyTools(system.db, registry=system.os.registry)
    with pytest.raises(ValueError, match="Authorize automatic acceptance through the Routine API"):
        tools.create_company_product("Chat", routines=[Routine(name="intake", instructions="Read.", auto_accept=True)])


# ----------------------------------------------------------------- Mini Agent's status write


@pytest.mark.parametrize("use_async", [False, True])
def test_a_task_run_on_mini_agent_updates_only_its_own_products_status(system, use_async):
    product_id, routine_id = system.declare(auto_accept=True)
    other_id, _ = system.declare(auto_accept=False, product="Other")
    _, task = system.proposes(product_id, routine_id)
    tools = system.mini.tools.task[0]

    def update(target):
        version = system.manager.read_wiki(target, "status.md").metadata.version
        if use_async:
            return asyncio.run(tools.aupdate_product_status(target, "Done.", version))
        return tools.update_product_status(target, "Done.", version)

    with authorization_scope(lambda: _ExecutorAuthorization(None, task_id=task["id"])):
        with pytest.raises(PermissionError, match="its own Product only"):
            update(other_id)
        assert json.loads(update(product_id))["path"] == "status.md"
    with authorization_scope(lambda: _ExecutorAuthorization(None, task_id="missing")):
        with pytest.raises(PermissionError, match="its own Product only"):
            update(product_id)


# ----------------------------------------------------------------- auto-accept from chat


def chat(scopes=None, user="alice", **authority_fields):
    authority = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id=user, scopes=SCOPES if scopes is None else scopes, claims={"sub": user}),
        **authority_fields,
    )
    return RunContext(run_id="chat-run", session_id="chat-session", user_id=user, authorization=authority)


def turn_on(system, routine_id, context=None, routine="intake", product="Docs", executor=("agent", MINI_AGENT_ID)):
    tools = CompanyTaskTools(system.os)
    call = tools.aturn_on_routine_auto_accept(
        routine, product, executor[0], executor[1], routine_id, _agno_run_context=context or chat()
    )
    return asyncio.run(call)


def turn_off(system, routine_id, context=None, routine="intake"):
    tools = CompanyTaskTools(system.os)
    return asyncio.run(tools.aturn_off_routine_auto_accept(routine, routine_id, _agno_run_context=context or chat()))


def test_turning_auto_accept_on_pauses_and_turning_it_off_does_not(system):
    functions = CompanyTaskTools(system.os).get_async_functions()
    assert functions["turn_on_routine_auto_accept"].requires_confirmation is True
    assert not functions["turn_off_routine_auto_accept"].requires_confirmation
    functions["turn_on_routine_auto_accept"].process_entrypoint()
    shown = set(functions["turn_on_routine_auto_accept"].parameters["required"])
    assert shown == {"routine_name", "product_name", "executor_type", "executor_id", "routine_id"}


def test_super_agent_pauses_before_auto_accept_is_turned_on(system):
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    arguments = {
        "routine_name": "intake",
        "product_name": "Docs",
        "executor_type": "agent",
        "executor_id": "writer",
        "routine_id": routine_id,
    }
    system.os.manager.model = ScriptedModel([("turn_on_routine_auto_accept", arguments)])
    authority = chat().authorization
    with authorization_scope(lambda: authority):
        paused = asyncio.run(system.os.manager.arun("Turn it on", user_id="alice", session_id="chat"))
    assert paused.is_paused and system.db.get_schedule(routine_id) == before
    assert paused.requirements[0].tool_execution.tool_args == arguments
    paused.requirements[0].confirm()
    with authorization_scope(lambda: authority):
        result = asyncio.run(system.os.manager.acontinue_run(run_response=paused, user_id="alice"))
    assert "Auto-accept is on for Routine 'intake'" in str(result.content), result.content
    payload = system.stored(routine_id)
    assert payload["metadata"]["auto_accept"]["executor_id"] == "writer"
    # A policy a person turns on runs under that person's saved permissions, not as the deployment.
    grant = payload["_agno_company_acceptance"]
    assert grant["user_id"] == "alice" and grant[AUTHORIZATION_KEY]["context"]["principal_id"] == "alice"

    _, task = system.proposes(product_id, routine_id)
    system.tick()
    accepted = system.db.get_task(task["id"])
    assert accepted["status"] == "in_progress" and accepted["executor_id"] == "writer"
    assert [(target, user) for target, user, _ in receipts(accepted)] == [("ready", "alice")]

    assert turn_off(system, routine_id).startswith("Auto-accept is off"), turn_off(system, routine_id)
    off = system.stored(routine_id)
    assert off["metadata"]["auto_accept"] is False and "_agno_company_acceptance" not in off


def test_auto_accept_is_turned_on_only_for_the_routine_the_person_confirmed(system):
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    assert "is named 'intake'" in turn_on(system, routine_id, routine="other")
    assert "belongs to Product 'Docs'" in turn_on(system, routine_id, product="Other")
    assert "is named 'intake'" in turn_off(system, routine_id, routine="other")
    assert "Routine not found" in turn_on(system, "missing")
    assert "leave both out to use Mini Agent" in turn_on(system, routine_id, executor=("agent", None))
    assert turn_on(
        system, routine_id, chat(scopes=[*SCOPES, "teams:*:run"]), executor=("team", MANAGER_TEAM_ID)
    ).startswith("Not done")
    assert system.db.get_schedule(routine_id) == before
    tools = CompanyTaskTools(system.os)
    assert "asynchronous run" in tools.turn_on_routine_auto_accept("intake", "Docs", "agent", MINI_AGENT_ID, routine_id)
    assert "asynchronous run" in tools.turn_off_routine_auto_accept("intake", routine_id)
    assert system.db.get_schedule(routine_id) == before


PATCH_GRANTS = [
    "routines:write",
    "schedules:write",
    "tasks:write",
    "wiki:read",
    "projects:write",
    f"agents:{MINI_AGENT_ID}:run",
]


@pytest.mark.parametrize("missing", PATCH_GRANTS)
def test_the_chat_tool_refuses_whoever_the_routine_api_refuses(system, missing):
    system.app.state.user_isolation_enabled = True
    system.os.user_isolation = True
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    without = [scope for scope in SCOPES if scope != missing]
    api = system.client.patch(
        f"/company/routines/{routine_id}", json={"auto_accept": True}, headers=headers(without, user="bob")
    )
    assert api.status_code == 403, api.text
    reply = turn_on(system, routine_id, chat(scopes=without, user="bob"))
    assert reply.startswith("Not done"), reply
    assert system.db.get_schedule(routine_id) == before
    # A person the API accepts is accepted by the tool, and recorded.
    assert turn_on(system, routine_id, chat(user="bob")).startswith("Auto-accept is on")
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "bob"


def test_under_isolation_the_chat_tool_needs_a_signed_in_person(system):
    system.app.state.user_isolation_enabled = True
    system.os.user_isolation = True
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    anonymous = RunContext(run_id="r", session_id="s", user_id=None, authorization=None)
    for reply in (turn_on(system, routine_id, anonymous), turn_off(system, routine_id, anonymous)):
        assert reply.startswith("Not done") and "signed-in person" in reply, reply
    assert system.db.get_schedule(routine_id) == before


def automated(caller):
    context = chat()
    if caller == "routine-run":
        context.authorization = _RoutineAuthorization(context.authorization, routine_id="routine", product_id=None)
    elif caller == "task-run":
        context.authorization = _ExecutorAuthorization(context.authorization, task_id="task")
    elif caller == "service-account":
        context = chat(service_account=True)
    elif caller == "scheduler":
        context = chat(user=INTERNAL_SCHEDULER_USER_ID)
    return context


@pytest.mark.parametrize("tool", ["on", "off"])
@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler", "automation-tick"])
def test_only_a_person_turns_auto_accept_on_or_off(system, tool, caller):
    product_id, routine_id = system.declare(auto_accept=tool == "off")
    before = system.db.get_schedule(routine_id)
    token = _automatic_task.set({"id": "task"}) if caller == "automation-tick" else None
    try:
        reply = (
            turn_on(system, routine_id, automated(caller))
            if tool == "on"
            else turn_off(system, routine_id, automated(caller))
        )
    finally:
        if token is not None:
            _automatic_task.reset(token)
    assert reply.startswith("Not done") and "human" in reply, reply
    assert system.db.get_schedule(routine_id) == before
