"""A Task for an executor that works in a sandbox is filed under the Goal that has its repository."""

import pytest

from agno.db.schemas.projects import DEFAULT_PROJECT_ID
from agno.os.manager import company_tasks
from agno.registry._reserved import MINI_AGENT_ID
from agno.sandbox import Repository
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from tests.unit.os.test_company_decision_tools import SCOPES, accept, build, call, context, headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

URL = "https://github.com/a/b"
ENGINEER = {"executor_type": "agent", "executor_id": "engineer"}
ENGINEER_SCOPES = [*SCOPES, "agents:engineer:run", "sources:write"]


@pytest.fixture(autouse=True)
def fresh_run_counts():
    company_tasks._accepted_in_run.clear()
    yield
    company_tasks._accepted_in_run.clear()


@pytest.fixture(params=[False, True], ids=["shared", "isolated"])
def system(request, tmp_path):
    """An AgentOS that serves a sandboxed engineer next to the writer."""
    client, db, agent_os, queue = build(tmp_path, user_isolation=request.param)
    engineer = FixtureAgent(
        id="engineer",
        name="Engineer",
        sandbox=DockerSandbox("unused", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}),
        repository=Repository(URL),
    )
    agent_os.agents.append(engineer)
    agent_os.registry.agents.append(engineer)
    yield client, db, agent_os, queue
    db.close()


def goal(client, name, reference=URL, user="alice"):
    """A Goal, with a git Source for the reference when one is given."""
    created = client.post("/company/goals", json={"name": name}, headers=headers(ENGINEER_SCOPES, user=user))
    assert created.status_code == 201, created.text
    if reference is not None:
        source = client.post(
            "/company/sources",
            json={"goal_id": created.json()["id"], "type": "git", "reference": reference},
            headers=headers(ENGINEER_SCOPES, user=user),
        )
        assert source.status_code == 201, source.text
    return created.json()


def writer_pushes_code(monkeypatch, client, agent_os, goal_id=None):
    """Make the plain writer count as sandboxed on the repository, with a Goal that has it as a git Source."""
    monkeypatch.setattr(
        "agno.company.sandbox._is_sandboxed", lambda component: getattr(component, "id", "") == "writer"
    )
    monkeypatch.setattr(agent_os.registry.get_agent("writer"), "repository", Repository(URL), raising=False)
    goal_id = goal_id or goal(client, "Platform", reference=None)["id"]
    source = client.post(
        "/company/sources",
        json={"goal_id": goal_id, "type": "git", "reference": URL},
        headers=headers(ENGINEER_SCOPES),
    )
    assert source.status_code == 201, source.text
    return goal_id


def add(agent_os, **arguments):
    arguments = {"title": "Fix the typo", "brief": "Fix the typo in the README.", "start": True, **arguments}
    return call(agent_os, "add_company_task", context(ENGINEER_SCOPES), **arguments)


def tasks(db):
    return db.get_tasks(limit=100)[0]


def test_with_no_goal_named_it_is_filed_under_the_one_goal_that_has_the_repository(system):
    client, db, agent_os, queue = system
    goal(client, "Docs", reference="https://github.com/a/other")
    platform = goal(client, "Platform")
    reply = add(agent_os, **ENGINEER)
    (task,) = tasks(db)
    assert reply.startswith("Recorded") and f"filed under Goal 'Platform' ({platform['id']})" in reply, reply
    assert (task["goal_id"], task["project_id"], task["status"]) == (platform["id"], DEFAULT_PROJECT_ID, "backlog")
    # The acceptance the result asks for goes through, where a Task with no Goal is refused.
    assert accept(agent_os, context(ENGINEER_SCOPES), task, executor=("agent", "engineer")).startswith("Accepted")
    assert db.get_task(task["id"])["status"] == "ready"


def test_with_no_goal_that_has_the_repository_nothing_is_recorded(system):
    client, db, agent_os, queue = system
    goal(client, "Docs", reference="https://github.com/a/other")
    reply = add(agent_os, **ENGINEER)
    assert reply.startswith("Not done, and nothing was recorded") and URL in reply, reply
    assert "No Goal has one" in reply and "no Goal was named" in reply, reply
    assert tasks(db) == []


def test_with_several_goals_that_have_the_repository_it_names_them_and_records_nothing(system):
    client, db, agent_os, queue = system
    first, second = goal(client, "Platform"), goal(client, "Maintenance")
    reply = add(agent_os, **ENGINEER)
    assert reply.startswith("Not done, and nothing was recorded"), reply
    for row in (first, second):
        assert f"'{row['name']}' ({row['id']})" in reply, reply
    assert tasks(db) == []
    # The person's choice is then used as given.
    assert add(agent_os, goal_id=second["id"], **ENGINEER).startswith("Recorded")
    assert [row["goal_id"] for row in tasks(db)] == [second["id"]]


def test_a_named_goal_is_used_and_is_not_replaced(system):
    client, db, agent_os, queue = system
    goal(client, "Platform")
    named = goal(client, "Maintenance")
    reply = add(agent_os, goal_id=named["id"], **ENGINEER)
    (task,) = tasks(db)
    assert reply.startswith("Recorded") and "filed under" not in reply, reply
    assert task["goal_id"] == named["id"]


def test_a_named_goal_without_the_repository_leaves_no_task_behind(system):
    client, db, agent_os, queue = system
    platform = goal(client, "Platform")
    docs = goal(client, "Docs", reference=None)
    reply = add(agent_os, goal_id=docs["id"], **ENGINEER)
    assert reply.startswith("Not done, and nothing was recorded") and "Goal 'Docs' has none" in reply, reply
    assert f"'Platform' ({platform['id']})" in reply, reply
    assert tasks(db) == []
    assert add(agent_os, goal_id="missing", **ENGINEER) == "Not done: Goal not found"
    # A second try under the Goal that fits is not blocked by anything the first one left.
    assert add(agent_os, goal_id=platform["id"], **ENGINEER).startswith("Recorded")


def test_where_people_are_isolated_another_persons_goal_is_not_offered(system):
    client, db, agent_os, queue = system
    theirs = goal(client, "Theirs", user="bob")
    reply = add(agent_os, **ENGINEER)
    if agent_os.user_isolation:
        assert reply.startswith("Not done, and nothing was recorded") and "Theirs" not in reply, reply
        assert tasks(db) == []
    else:
        assert f"filed under Goal 'Theirs' ({theirs['id']})" in reply, reply
    # A Goal declared in code has no owner and is offered to everyone.
    declared = goal(client, "Declared")
    with db.Session() as session, session.begin():
        from sqlalchemy import update

        table = db._get_table("goals")
        session.execute(update(table).where(table.c.id == declared["id"]).values(user_id=None))
    company_tasks._accepted_in_run.clear()
    reply = add(agent_os, **ENGINEER)
    if agent_os.user_isolation:
        assert f"filed under Goal 'Declared' ({declared['id']})" in reply, reply
    else:
        assert reply.startswith("Not done, and nothing was recorded") and "Theirs" in reply and "Declared" in reply


def test_in_a_project_the_projects_goal_decides(system):
    client, db, agent_os, queue = system
    platform, docs = goal(client, "Platform"), goal(client, "Docs", reference=None)
    projects = {}
    for row in (platform, docs):
        project = client.post(
            "/company/projects", json={"goal_id": row["id"], "name": row["name"]}, headers=headers(ENGINEER_SCOPES)
        ).json()
        client.post(
            f"/company/projects/{project['id']}/transitions",
            json={"target": "active", "reason": "Approved"},
            headers=headers(ENGINEER_SCOPES),
        )
        projects[row["name"]] = project["id"]
    assert "Goal 'Docs' has none" in add(agent_os, project_id=projects["Docs"], **ENGINEER)
    assert tasks(db) == []
    assert add(agent_os, project_id=projects["Platform"], **ENGINEER).startswith("Recorded")
    assert [(row["goal_id"], row["project_id"]) for row in tasks(db)] == [(platform["id"], projects["Platform"])]


def test_work_for_an_executor_with_no_sandbox_still_has_no_goal(system):
    client, db, agent_os, queue = system
    goal(client, "Platform")
    assert add(agent_os, start=False).startswith("Added")
    assert add(agent_os, start=False, executor_type="agent", executor_id="writer").startswith("Added")
    assert [(row["goal_id"], row["project_id"], row["status"]) for row in tasks(db)] == [
        (None, DEFAULT_PROJECT_ID, "ready")
    ] * 2
    assert {row["executor_id"] for row in tasks(db)} == {MINI_AGENT_ID, "writer"}


@pytest.mark.parametrize("use_async", [False, True])
def test_the_manager_lists_the_goals_a_sandboxed_executor_accepts_under(system, use_async):
    import asyncio

    from agno.company.manager import AsyncCompanyManager, CompanyManager

    client, db, agent_os, queue = system
    platform = goal(client, "Platform")
    goal(client, "Docs", reference="https://github.com/a/other")
    # A Source whose credential the sandbox does not hold is not one the acceptance check takes.
    locked = goal(client, "Locked", reference=None)
    db.create_source(
        {
            "id": "locked-source",
            "goal_id": locked["id"],
            "type": "git",
            "reference": URL,
            "credential_ref": "GITHUB_READ_TOKEN",
            "user_id": "alice",
            "config": {},
            "created_at": 1,
            "updated_at": None,
            "deleted_at": None,
        }
    )
    if use_async:
        from agno.db.sqlite import AsyncSqliteDb

        manager = AsyncCompanyManager(AsyncSqliteDb(db_file=db.db_file), agent_os.registry)
    else:
        manager = CompanyManager(db, agent_os.registry)

    def read(*arguments):
        result = manager.sandbox_goals(*arguments)
        return asyncio.run(result) if use_async else result

    assert [row["id"] for row in read("agent", "engineer")] == [platform["id"]]
    assert read("agent", "writer") is None
