"""auto_accept: one switch on a Routine takes its work from a proposal to In review with no person."""

import asyncio
import json

import pytest

from agno.agent import Agent
from agno.company import CompanyManager, Product, Routine
from agno.company.bootstrap import arehydrate_product
from agno.company.declarations import AutoAccept
from agno.company.execution import _automatic_task, _ExecutorAuthorization
from agno.company.routines import (
    _DECLARED,
    _check_automatic_policy,
    _CompanyScheduleExecutor,
    _executor_kind,
    _open_tasks,
    _policy_executors,
    _policy_fingerprint,
    _RoutineAuthorization,
)
from agno.os.auth import INTERNAL_SCHEDULER_USER_ID
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.manager.company_tasks import CompanyTaskTools, _policy_line
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID, MINI_AGENT_ID
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, RunAuthorization, authorization_scope
from agno.scheduler import ScheduleManager
from agno.team import Team
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
        "default_executor": MINI_AGENT_ID,
        "executors": None,
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
    assert receipts(review) == [("ready", None, {**receipt, "executor_chosen_by": "default"})]
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
    with pytest.raises(ValueError, match="'missing' is not a registered agent, team or workflow"):
        system.declare(auto_accept=AutoAccept(default_executor="missing"), product="Bad")


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
    assert receipts(on_default)[0][2]["executor_chosen_by"] == "default"


def test_a_named_default_runs_a_task_whose_proposal_suggests_none(open_system):
    product_id, routine_id = open_system.declare(auto_accept=AutoAccept(default_executor="writer"))
    assert open_system.stored(routine_id)["metadata"]["auto_accept"]["executors"] is None
    _, plain = open_system.proposes(product_id, routine_id, title="Suggests nothing")
    _, mini = open_system.proposes(
        product_id, routine_id, title="Suggests Mini Agent", executor=("agent", MINI_AGENT_ID)
    )
    open_system.tick()
    on_default, on_mini = open_system.db.get_task(plain["id"]), open_system.db.get_task(mini["id"])
    assert (on_default["executor_type"], on_default["executor_id"]) == ("agent", "writer")
    assert receipts(on_default)[0][2]["executor_chosen_by"] == "default"
    assert on_mini["executor_id"] == MINI_AGENT_ID and receipts(on_mini)[0][2]["executor_chosen_by"] == "proposal"


def test_a_list_of_executors_limits_what_a_proposal_may_suggest(open_system):
    editor = Agent(id="editor", name="Editor", model=ScriptedModel(), db=open_system.db)
    reviewer = Agent(id="reviewer", name="Reviewer", model=ScriptedModel(), db=open_system.db)
    open_system.os.registry.agents.extend([editor, reviewer])
    policy = AutoAccept(default_executor="writer", executors=["editor"], max_open=10)
    product_id, routine_id = open_system.declare(auto_accept=policy)
    suggests = {
        name: open_system.proposes(product_id, routine_id, title=name, executor=executor)[1]["id"]
        for name, executor in {
            "listed": ("agent", "editor"),
            "default": ("agent", "writer"),
            "mini": ("agent", MINI_AGENT_ID),
            "none": (None, None),
            "unlisted": ("agent", "reviewer"),
            "wrong kind": ("team", "editor"),
        }.items()
    }
    outcomes = open_system.tick()
    ran_on = {name: open_system.db.get_task(task_id)["executor_id"] for name, task_id in suggests.items()}
    assert ran_on == {
        "listed": "editor",
        "default": "writer",
        "mini": MINI_AGENT_ID,
        "none": "writer",
        "unlisted": "reviewer",
        "wrong kind": "editor",
    }
    status = {name: open_system.db.get_task(task_id)["status"] for name, task_id in suggests.items()}
    assert [name for name, value in status.items() if value == "backlog"] == ["unlisted", "wrong kind"], outcomes
    # A proposal that names an executor outside the list waits for a person.
    for name in ("unlisted", "wrong kind"):
        reason = open_system.outcome(outcomes, suggests[name])["reason"]
        assert "outside automatic acceptance authorization" in reason
    chosen = {
        name: receipts(open_system.db.get_task(task_id))[0][2]["executor_chosen_by"]
        for name, task_id in suggests.items()
        if status[name] != "backlog"
    }
    assert chosen == {"listed": "proposal", "default": "proposal", "mini": "proposal", "none": "default"}


@pytest.mark.parametrize("field", ["default_executor", "executors"])
@pytest.mark.parametrize("executor_id", [MANAGER_TEAM_ID, BUILDER_ID, "missing", "no-database"])
def test_every_executor_a_policy_names_passes_the_executor_checks(system, field, executor_id):
    # Super Agent is refused even where a registry lists it, and an executor needs a database for durable runs.
    system.os.registry.teams.append(system.os.manager)
    system.os.registry.agents.append(Agent(id="no-database", name="No database", model=ScriptedModel()))
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    policy = {field: executor_id if field == "default_executor" else [executor_id]}
    scopes = [*SCOPES, "teams:*:run", "agents:*:run"]
    with pytest.raises(ValueError):
        system.declare(auto_accept=AutoAccept(**policy), product="Bad")
    patched = system.client.patch(
        f"/company/routines/{routine_id}", json={"auto_accept": policy}, headers=headers(scopes)
    )
    assert patched.status_code == 422, patched.text
    assert system.api_routine(product_id, policy, scopes=scopes, name="second").status_code == 422
    assert system.db.get_schedule(routine_id) == before


def test_the_author_must_be_allowed_to_run_each_executor_the_policy_names(system):
    product_id, routine_id = system.declare(auto_accept=False)
    path = f"/company/routines/{routine_id}"
    without = [scope for scope in SCOPES if scope != "agents:writer:run"]
    assert "agents:writer:run" in SCOPES and f"agents:{MINI_AGENT_ID}:run" in without
    for policy in ({"default_executor": "writer"}, {"executors": ["writer"]}):
        refused = system.client.patch(path, json={"auto_accept": policy}, headers=headers(without))
        assert refused.status_code == 403, refused.text
        assert system.stored(routine_id)["metadata"]["auto_accept"] is False
        assert system.client.patch(path, json={"auto_accept": policy}, headers=headers(SCOPES)).status_code == 200
        assert system.client.patch(path, json={"auto_accept": False}, headers=headers(SCOPES)).status_code == 200


def test_an_executor_id_that_names_two_components_is_refused_not_guessed(system):
    # Code-defined components are checked for duplicate IDs within a kind only, so an agent and a team can share one.
    system.os.registry.teams.append(Team(id="writer", name="Writers", members=[system.writer], model=ScriptedModel()))
    assert _executor_kind(system.os.registry, MINI_AGENT_ID) == "agent"
    with pytest.raises(ValueError, match="is shared by agent and team. Give each its own ID"):
        _executor_kind(system.os.registry, "writer")
    product_id, routine_id = system.declare(auto_accept=False)
    for policy in ({"default_executor": "writer"}, {"executors": ["writer"]}):
        patched = system.client.patch(
            f"/company/routines/{routine_id}", json={"auto_accept": policy}, headers=headers(SCOPES)
        )
        assert patched.status_code == 422 and "Give each its own ID" in patched.text, patched.text
    assert "Give each its own ID" in turn_on(system, routine_id, executor="writer")
    assert system.stored(routine_id)["metadata"]["auto_accept"] is False


def test_a_studio_published_executor_is_named_by_its_id(system, monkeypatch):
    published = Team(id="editors", name="Editors", members=[system.writer], model=ScriptedModel(), db=system.db)
    system.os.registry.component_db = system.db
    monkeypatch.setattr(
        "agno.team.team.get_team_by_id", lambda db, id, **kwargs: published if id == "editors" else None
    )
    monkeypatch.setattr("agno.agent.agent.get_agent_by_id", lambda db, id, **kwargs: None)
    monkeypatch.setattr("agno.workflow.workflow.get_workflow_by_id", lambda db, id, **kwargs: None)
    assert _executor_kind(system.os.registry, "editors") == "team"
    assert _policy_executors(system.os.registry, AutoAccept(default_executor="editors")) == ["/teams/editors/runs"]


@pytest.mark.parametrize("executor", [("team", MANAGER_TEAM_ID), ("agent", BUILDER_ID), ("agent", "missing")])
def test_a_suggested_executor_that_cannot_run_the_task_waits_for_a_person(open_system, executor):
    product_id, routine_id = open_system.declare(auto_accept=True)
    _, task = open_system.proposes(product_id, routine_id, executor=executor)
    outcome = open_system.outcome(open_system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "cannot run this Task" in outcome["reason"], outcome
    assert open_system.db.get_task(task["id"])["status"] == "backlog"


def legacy(system, product_id, executor_id="writer"):
    """A Routine whose policy was saved through the API when a policy named executor_type and executor_id."""
    limits = {"max_acceptances": 5, "expires_at": FUTURE}
    response = system.api_routine(product_id, {"default_executor": executor_id, "limits": limits}, name="legacy")
    assert response.status_code == 201, response.text
    row = system.db.get_schedule(response.json()["id"])
    saved = {
        "executor_type": "agent",
        "executor_id": executor_id,
        "source_ids": None,
        "work_scope": None,
        "required_checks": ["executor_registered"],
        "limits": limits,
        "complete_projects": False,
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
    # It allows its one executor: a proposal that suggests another, Mini Agent included, waits for a person.
    assert "outside automatic acceptance authorization" in system.outcome(outcomes, other["id"])["reason"]
    accepted = system.db.get_task(task["id"])
    assert (accepted["executor_type"], accepted["executor_id"]) == ("agent", "writer")
    receipt = accepted["transitions"][-2]["auto_accept"]
    assert receipt["max_acceptances"] == 5 and receipt["executor_chosen_by"] == "default"
    # It reads as a default and a list of that one executor.
    read = AutoAccept.model_validate(system.stored(routine_id)["metadata"]["auto_accept"])
    assert (read.default_executor, read.executors) == ("writer", ["writer"])


def test_a_policy_sent_with_executor_type_and_executor_id_is_read_as_a_default_and_a_list(system):
    product_id, routine_id = system.declare(auto_accept=False)
    path = f"/company/routines/{routine_id}"
    sent = {"executor_type": "agent", "executor_id": "writer"}
    assert system.client.patch(path, json={"auto_accept": sent}, headers=headers(SCOPES)).status_code == 200
    stored = system.stored(routine_id)["metadata"]["auto_accept"]
    assert (stored["default_executor"], stored["executors"]) == ("writer", ["writer"]) and "executor_type" not in stored
    for refused in (
        {**sent, "default_executor": MINI_AGENT_ID},
        {**sent, "executors": ["writer"]},
        {"executor_id": "writer"},
    ):
        assert system.client.patch(path, json={"auto_accept": refused}, headers=headers(SCOPES)).status_code == 422
    assert system.stored(routine_id)["metadata"]["auto_accept"] == stored


def test_the_old_shape_approves_no_project_whether_it_is_sent_or_stored(system):
    product_id, routine_id = system.declare(auto_accept=False)
    path = f"/company/routines/{routine_id}"
    sent = {"executor_type": "agent", "executor_id": "writer", "limits": {"expires_at": FUTURE}}
    # A client that wrote this before needed no projects:write, and its Routine approved no Project.
    without = [scope for scope in SCOPES if scope != "projects:write"]
    patched = system.client.patch(path, json={"auto_accept": sent}, headers=headers(without))
    assert patched.status_code == 200, patched.text
    assert system.stored(routine_id)["metadata"]["auto_accept"]["approve_projects"] is False
    assert patched.json()["payload"]["metadata"]["auto_accept"]["approve_projects"] is False
    assert AutoAccept.model_validate(sent).approve_projects is False
    # In the new form it is on unless the policy says otherwise.
    assert AutoAccept.model_validate({"default_executor": "writer"}).approve_projects is True
    created = system.api_routine(product_id, sent, scopes=without, name="second")
    assert created.status_code == 201, created.text
    assert system.stored(created.json()["id"])["metadata"]["auto_accept"]["approve_projects"] is False


def test_a_stored_policy_read_from_the_api_and_sent_back_keeps_its_version_and_its_count(system):
    product_id = system.client.post("/company/products", json={"name": "SDK"}, headers=headers(SCOPES)).json()["id"]
    routine_id = legacy(system, product_id)
    project, task = system.proposes(product_id, routine_id)
    system.manager.transition_project(project_id=project["id"], target="active", reason="Approved by a person")
    system.tick()
    accepted = system.db.get_task(task["id"])
    assert accepted["status"] == "in_progress"
    before = system.stored(routine_id)["metadata"]["auto_accept"]
    version = _policy_fingerprint(system.db.get_schedule(routine_id))
    assert system.db.count_company_acceptances(routine_id, version, "") == 1

    path = f"/company/routines/{routine_id}"
    read = system.client.get(path, headers=headers(SCOPES)).json()["payload"]["metadata"]["auto_accept"]
    # The response states what the stored policy does.
    assert read["approve_projects"] is False and read["executors"] == ["writer"]
    sent_back = system.client.patch(path, json={"auto_accept": read}, headers=headers(SCOPES))
    assert sent_back.status_code == 200, sent_back.text
    assert sent_back.json()["payload"]["metadata"]["auto_accept"] == read
    assert system.stored(routine_id)["metadata"]["auto_accept"] == before
    assert _policy_fingerprint(system.db.get_schedule(routine_id)) == version
    assert system.db.count_company_acceptances(routine_id, version, "") == 1
    # Work it accepted is still its work.
    asyncio.run(_check_automatic_policy(system.db, accepted))
    # The same holds for the request an existing client sends: the policy in the shape it was saved in.
    assert system.client.patch(path, json={"auto_accept": before}, headers=headers(SCOPES)).status_code == 200
    assert system.stored(routine_id)["metadata"]["auto_accept"] == before
    # A change is a new policy, stored in the new form with a new version.
    changed = system.client.patch(path, json={"auto_accept": {**read, "max_open": 2}}, headers=headers(SCOPES))
    assert changed.status_code == 200, changed.text
    assert "executor_type" not in system.stored(routine_id)["metadata"]["auto_accept"]
    assert _policy_fingerprint(system.db.get_schedule(routine_id)) != version


def test_a_policy_saved_before_this_change_keeps_its_version():
    # Versions computed on main, where a policy named executor_type and executor_id.
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
    assert json.loads(tools.list_company_tasks())["auto_accept_at_limit"] == at_limit
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


# ----------------------------------------------------------------- auto-accept from chat


def chat(scopes=None, user="alice", **authority_fields):
    authority = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id=user, scopes=SCOPES if scopes is None else scopes, claims={"sub": user}),
        **authority_fields,
    )
    return RunContext(run_id="chat-run", session_id="chat-session", user_id=user, authorization=authority)


def turn_on(system, routine_id, context=None, routine="intake", product="Docs", executor=None, kept=None):
    tools = CompanyTaskTools(system.os)
    call = tools.aturn_on_routine_auto_accept(
        routine, product, executor, kept, routine_id, _agno_run_context=context or chat()
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
    assert shown == {"routine_name", "product_name", "default_executor", "kept_policy", "routine_id"}


def company_tools(system):
    """Super Agent's Company tools, bound to the deployment as AgentOS binds them."""
    return next(tool for tool in system.os.manager.tools if isinstance(tool, CompanyTools))


def waiting(system, product_id="docs", use_async=False):
    tools = company_tools(system)
    if use_async:
        shown = json.loads(asyncio.run(tools.aget_company_product(product_id)))
        listed = json.loads(asyncio.run(tools.alist_company_tasks(product_id=product_id, status="backlog")))
    else:
        shown = json.loads(tools.get_company_product(product_id))
        listed = json.loads(tools.list_company_tasks(product_id=product_id, status="backlog"))
    assert shown.get("auto_accept_waiting_for_a_person") == listed.get("auto_accept_waiting_for_a_person")
    return [
        (item["routine"], item["product_id"], item["default_executor"])
        for item in shown.get("auto_accept_waiting_for_a_person") or []
    ]


@pytest.mark.parametrize("use_async", [False, True])
def test_with_authorization_on_one_confirmation_turns_on_the_declared_routine_and_its_policy(system, use_async):
    declared = AutoAccept(default_executor="writer", executors=["writer"], approve_projects=False, max_open=2)
    product_id, routine_id = system.declare(auto_accept=declared)
    system.declare(auto_accept=False, product="Other")
    before = system.stored(routine_id)
    assert AUTHORIZATION_KEY not in before

    # Until a person acts, the Product's status and the list of what needs a decision say so.
    assert waiting(system, use_async=use_async) == [("intake", "docs", "writer")]
    assert waiting(system, "other", use_async=use_async) == []
    # With no Product named, the list covers the company.
    for listing in ({"status": "backlog"}, {}):
        everywhere = json.loads(company_tools(system).list_company_tasks(**listing))
        assert [item["routine_id"] for item in everywhere["auto_accept_waiting_for_a_person"]] == [routine_id]
    assert "auto_accept_waiting_for_a_person" not in json.loads(
        company_tools(system).list_company_tasks(status="ready")
    )

    # One confirmation: the Routine runs under this person's grant, and so does the policy its code declares.
    reply = turn_on(system, routine_id)
    assert "with the policy its code declares" in reply and "run on writer" in reply, reply
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] == declared.model_dump() == before["metadata"]["auto_accept"]
    assert after[AUTHORIZATION_KEY]["context"]["principal_id"] == "alice"
    assert after["_agno_company_acceptance"]["user_id"] == "alice"
    assert waiting(system, use_async=use_async) == []

    project, task = system.proposes(product_id, routine_id)
    system.manager.transition_project(project_id=project["id"], target="active", reason="Approved by a person")
    system.tick()
    accepted = system.db.get_task(task["id"])
    assert (accepted["status"], accepted["executor_id"]) == ("in_progress", "writer")
    assert [(target, user, "declared" in receipt) for target, user, receipt in receipts(accepted)] == [
        ("ready", "alice", False)
    ]


def test_a_person_who_names_an_executor_changes_only_the_declared_default(system):
    declared = AutoAccept(default_executor="writer", max_open=2)
    product_id, routine_id = system.declare(auto_accept=declared)
    assert turn_on(system, routine_id, executor=MINI_AGENT_ID).startswith("Auto-accept is on")
    assert system.stored(routine_id)["metadata"]["auto_accept"] == {
        **declared.model_dump(),
        "default_executor": MINI_AGENT_ID,
    }
    # A declared policy may be confirmed with its line too. A line that is not the stored policy is refused.
    other_product, other_routine = system.declare(auto_accept=declared, product="Other")
    before = system.db.get_schedule(other_routine)
    assert "already has a policy" in turn_on(system, other_routine, product="Other", kept="default executor miniagent")
    assert system.db.get_schedule(other_routine) == before
    assert turn_on(system, other_routine, product="Other", kept=_policy_line(declared)).startswith("Auto-accept is on")


def test_turning_auto_accept_on_keeps_a_policy_a_person_wrote(system):
    product_id, routine_id = system.declare(auto_accept=False)
    path = f"/company/routines/{routine_id}"
    written = {
        "default_executor": "writer",
        "executors": ["writer"],
        "approve_projects": False,
        "limits": {"max_acceptances": 3, "expires_at": FUTURE},
    }
    assert system.client.patch(path, json={"auto_accept": written}, headers=headers(SCOPES)).status_code == 200
    before = system.db.get_schedule(routine_id)
    policy, version = before["payload"]["metadata"]["auto_accept"], _policy_fingerprint(before)

    project, task = system.proposes(product_id, routine_id)
    system.manager.transition_project(project_id=project["id"], target="active", reason="Approved by a person")
    system.tick()
    accepted = system.db.get_task(task["id"])
    assert accepted["status"] == "in_progress", accepted

    # The person confirms the policy that is kept. A call that does not show it changes nothing and says what to show.
    line = _policy_line(AutoAccept.model_validate(policy))
    assert line == (
        "default executor writer; proposals may name writer; a person approves its Projects; "
        "at most 3 acceptances, expires 2100-01-01 00:00 UTC"
    )
    scoped = AutoAccept(source_ids=["notes"], work_scope={"project_ids": ["p1"]}, complete_projects=True, executors=[])
    assert _policy_line(scoped) == (
        "default executor miniagent; proposals may name no other executor; approves its Projects; "
        "at most 5 Tasks open; Sources notes; Projects p1; completes Projects"
    )
    bob = chat(user="bob")
    for refused in (turn_on(system, routine_id, bob), turn_on(system, routine_id, bob, kept="default executor writer")):
        assert refused.startswith("Not done") and "already has a policy" in refused and line in refused, refused
        assert system.db.get_schedule(routine_id) == before

    # Confirmed, the policy is kept as it is, with its version, and from then on it runs under this person.
    reply = turn_on(system, routine_id, bob, kept=line)
    assert "with the policy it already had" in reply and "A person approves its Projects" in reply, reply
    assert "from writer" in reply and "at most 3 Tasks" in reply, reply
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] == policy
    assert _policy_fingerprint(system.db.get_schedule(routine_id)) == version
    assert after["_agno_company_acceptance"]["user_id"] == "bob"
    asyncio.run(_check_automatic_policy(system.db, accepted))

    # Naming an executor changes the default and nothing else.
    assert turn_on(system, routine_id, executor=MINI_AGENT_ID, kept=line).startswith("Auto-accept is on")
    assert system.stored(routine_id)["metadata"]["auto_accept"] == {**policy, "default_executor": MINI_AGENT_ID}

    # A Routine with no policy has nothing to keep, and gets the defaults.
    other_product, other_routine = system.declare(auto_accept=False, product="Other")
    assert "has no policy to keep" in turn_on(system, other_routine, product="Other", kept=line)
    assert system.stored(other_routine)["metadata"]["auto_accept"] is False
    assert turn_on(system, other_routine, product="Other").startswith("Auto-accept is on")
    assert system.stored(other_routine)["metadata"]["auto_accept"] == AutoAccept().model_dump()


def test_where_authorization_is_off_a_declared_routine_is_not_reported_as_waiting(open_system):
    product_id, routine_id = open_system.declare(auto_accept=True)
    assert open_system.manager.auto_accept_waiting(product_id) != []
    assert waiting(open_system) == []


def test_the_routine_api_still_returns_executor_type_and_executor_id_marked_deprecated(system):
    product_id, routine_id = system.declare(auto_accept=False)
    path = f"/company/routines/{routine_id}"
    assert system.client.get(path, headers=headers(SCOPES)).json()["payload"]["metadata"]["auto_accept"] is False
    patched = system.client.patch(path, json={"auto_accept": {"default_executor": "writer"}}, headers=headers(SCOPES))
    assert patched.status_code == 200, patched.text
    listed = system.client.get("/company/routines", params={"product_id": product_id}, headers=headers(SCOPES))
    for returned in (patched.json(), system.client.get(path, headers=headers(SCOPES)).json(), listed.json()["data"][0]):
        policy = returned["payload"]["metadata"]["auto_accept"]
        assert (policy["default_executor"], policy["executors"]) == ("writer", None)
        assert (policy["executor_type"], policy["executor_id"]) == ("agent", "writer")
        assert policy["max_open"] == 5 and "_agno_company_acceptance" not in returned["payload"]
    # They are returned only: the stored policy does not hold them.
    stored = system.stored(routine_id)["metadata"]["auto_accept"]
    assert "executor_type" not in stored
    # A client can send back the policy it read, with both forms in it.
    assert system.client.patch(path, json={"auto_accept": policy}, headers=headers(SCOPES)).status_code == 200
    assert system.stored(routine_id)["metadata"]["auto_accept"] == stored

    # A policy stored with the two fields is returned with the new ones too.
    legacy_id = legacy(system, product_id)
    policy = system.client.get(f"/company/routines/{legacy_id}", headers=headers(SCOPES)).json()["payload"]["metadata"][
        "auto_accept"
    ]
    assert (policy["executor_type"], policy["executor_id"]) == ("agent", "writer")
    assert (policy["default_executor"], policy["executors"]) == ("writer", ["writer"])

    schema = system.client.get("/openapi.json").json()["components"]["schemas"]["RoutineAutoAccept"]["properties"]
    assert schema["executor_type"]["deprecated"] is True and schema["executor_id"]["deprecated"] is True
    assert "deprecated" not in schema["default_executor"]


def test_super_agent_pauses_before_auto_accept_is_turned_on(system):
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    arguments = {
        "routine_name": "intake",
        "product_name": "Docs",
        "default_executor": "writer",
        "kept_policy": None,
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
    policy = payload["metadata"]["auto_accept"]
    assert (policy["default_executor"], policy["executors"]) == ("writer", None)
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
    assert "'missing' is not a registered" in turn_on(system, routine_id, executor="missing")
    assert turn_on(system, routine_id, chat(scopes=[*SCOPES, "teams:*:run"]), executor=MANAGER_TEAM_ID).startswith(
        "Not done"
    )
    assert system.db.get_schedule(routine_id) == before
    tools = CompanyTaskTools(system.os)
    assert "asynchronous run" in tools.turn_on_routine_auto_accept("intake", "Docs", None, None, routine_id)
    assert "asynchronous run" in tools.turn_off_routine_auto_accept("intake", routine_id)
    assert system.db.get_schedule(routine_id) == before
    # A schedule listing shows the Routine under its Product's ID. That name is the same Routine.
    assert turn_on(system, routine_id, routine="docs.intake").startswith("Auto-accept is on for Routine 'intake'")
    assert turn_off(system, routine_id, routine="docs.intake").startswith("Auto-accept is off")


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


def test_a_run_with_no_authority_changes_auto_accept_only_where_authorization_is_off(system, open_system):
    nobody = RunContext(run_id="r", session_id="s", user_id=None, authorization=None)
    # The deployment checks permissions and this run carries none: an admin's grant is not replaced.
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id).startswith("Auto-accept is on")
    before = system.db.get_schedule(routine_id)
    for reply in (turn_off(system, routine_id, nobody), turn_on(system, routine_id, nobody)):
        assert reply.startswith("Not done") and "signed-in person" in reply, reply
    assert system.db.get_schedule(routine_id) == before
    # Where authorization is off every caller is a trusted operator.
    product_id, routine_id = open_system.declare(auto_accept=False, product="Open")
    assert turn_on(open_system, routine_id, nobody, product="Open").startswith("Auto-accept is on")
    assert open_system.stored(routine_id)["metadata"]["auto_accept"] == AutoAccept().model_dump()
    assert turn_off(open_system, routine_id, nobody).startswith("Auto-accept is off")
    assert open_system.stored(routine_id)["metadata"]["auto_accept"] is False


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
