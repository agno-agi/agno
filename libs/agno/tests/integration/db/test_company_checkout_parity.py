"""Atomic Task checkout projection on all Company SQL adapters."""

from types import SimpleNamespace

import pytest

from agno.company.execution import _call, _project_run
from agno.company.sandbox import _project_checkout
from agno.sandbox import Repository
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from tests.integration.db.test_company_execution_parity import accepted, system  # noqa: F401, F811

URL = "https://github.com/octocat/Hello-World"
PIN = {"url": URL, "branch": "master", "commit": "a" * 40}


@pytest.mark.asyncio
async def test_checkout_is_atomic_and_a_different_pin_fails_the_attempt(system):  # noqa: F811
    client, db, worker, _, components = system
    task = await accepted(client)
    source = await _call(
        db,
        "create_source",
        {"id": "repository", "product_id": task["product_id"], "type": "git", "reference": URL, "created_at": 1},
    )
    response = await client.post("/company/tasks/" + task["id"] + "/runs")
    assert response.status_code == 202
    job = await worker.store.get_job(response.json()["run_id"])
    task = await _call(db, "get_task", task["id"])
    agent = FixtureAgent(
        id="writer",
        sandbox=DockerSandbox("unused", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}),
        repository=Repository(URL, "master"),
    )
    data = {"run_id": job["id"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}}
    checkout, result = await _project_checkout(db, task, agent, data, {"run_id": job["id"], "status": "COMPLETED"})
    assert checkout == {"source_id": source["id"], **PIN}
    stale = await _call(
        db, "complete_task_run", task["id"], job["id"], result, expected_transitions=[], checkout=checkout
    )
    assert stale is None
    assert (await _call(db, "get_task", task["id"]))["metadata"] is None
    saved = await _call(
        db,
        "complete_task_run",
        task["id"],
        job["id"],
        result,
        expected_transitions=task["transitions"],
        checkout=checkout,
    )
    assert saved["metadata"]["checkout"] == checkout and saved["status"] == "in_review"
    for bad in (
        {**PIN, "commit": "b" * 40},
        {**PIN, "branch": "other"},
        {**PIN, "url": "https://github.com/other/repo"},
        None,
    ):
        next_checkout, failed = await _project_checkout(
            db, saved, agent, {"metadata": {"sandbox": {"repository": bad}}}, result
        )
        assert next_checkout is None and failed["status"] == "ERROR"
    # Exercise the worker completion projection itself against a reserved second attempt.
    task = await _call(db, "start_task_run", task["id"], 2, saved["transitions"], user_id=None)
    job = {
        **job,
        "id": task["job_id"],
        "payload": {**job["payload"], "company_task_attempt": 2, "company_task_transitions": saved["transitions"]},
    }
    data = {**data, "run_id": job["id"], "metadata": {"sandbox": {"repository": {**PIN, "commit": "b" * 40}}}}

    async def output(*args, **kwargs):
        return SimpleNamespace(status="COMPLETED", to_dict=lambda: data)

    agent.aget_run_output = output
    components["writer"] = agent
    await _project_run(worker, job, "completed")
    failed = await _call(db, "get_task", task["id"])
    assert failed["result"]["status"] == "ERROR"
    assert failed["metadata"]["checkout"] == checkout
    assert failed["status"] == "in_progress"


@pytest.mark.asyncio
async def test_git_source_partial_updates_validate_complete_reference(system):  # noqa: F811
    client, db, _, _, _ = system
    task = await accepted(client)
    await _call(
        db,
        "create_source",
        {"id": "source", "product_id": task["product_id"], "type": "git", "reference": URL, "created_at": 1},
    )
    updated = await _call(db, "update_source", "source", config={"branch": "main"})
    assert updated["config"] == {"branch": "main"}
    for fields in ({"reference": "https://gitlab.com/a/b"}, {"config": {"branch": "--bad"}}):
        with pytest.raises(ValueError):
            await _call(db, "update_source", "source", **fields)
        assert await _call(db, "get_source", "source") == updated


@pytest.mark.asyncio
async def test_legacy_git_source_can_be_updated_without_replacing_reference(system):  # noqa: F811
    client, db, _, _, _ = system
    task = await accepted(client)
    source = await _call(
        db,
        "create_source",
        {
            "id": "legacy",
            "product_id": task["product_id"],
            "type": "git",
            "reference": "https://gitlab.com/a/b",
            "created_at": 1,
        },
    )
    updated = await _call(db, "update_source", source["id"], credential_ref="READ_TOKEN", config={"branch": "main"})
    assert updated["reference"] == source["reference"]
    assert updated["credential_ref"] == "READ_TOKEN"
    with pytest.raises(ValueError):
        await _call(db, "update_source", source["id"], reference="https://gitlab.com/a/c")
    with pytest.raises(ValueError):
        await _call(db, "update_source", source["id"], config={"branch": "--invalid"})
    assert await _call(db, "get_source", source["id"]) == updated
