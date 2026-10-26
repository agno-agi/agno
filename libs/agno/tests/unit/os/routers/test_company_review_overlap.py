"""Overlapping reviews must not reach discovery with the same empty work list."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agno.company.manager import CompanyManager
from agno.company.review_lock import _active_review, _claim_review, _record_review_run, _review_filesystem
from agno.company.scheduler import CompanyScheduleExecutor
from agno.db.sqlite import SqliteDb
from agno.run import RunContext
from tests.unit.os.routers.test_company_manager_routines import ScriptedModel, create_routine, system


@pytest.mark.parametrize("second_routine", [False, True])
async def test_overlapping_reviews_create_one_project_and_task(tmp_path, second_routine):
    async with system(tmp_path) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Feedback", user_id="alice")
        path = tmp_path / "notes.md"
        path.write_text("Two customers report CSV exports fail across midnight.")
        source = manager.create_source(product_id=product["id"], type="markdown", reference=str(path))
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []

        async def hold_review(_agno_run_context: RunContext) -> str:
            calls.append(_agno_run_context.run_id)
            entered.set()
            await finish.wait()
            return _agno_run_context.run_id

        s.os.company_manager.tools.append(hold_review)
        s.os.company_manager.model = ScriptedModel(
            [
                ("hold_review", {}),
                ("list_company_projects", {"product_id": product["id"]}),
                ("list_company_tasks", {"product_id": product["id"]}),
                (
                    "propose_company_project",
                    lambda results: {"product_id": product["id"], "name": "CSV reliability " + results[0].content},
                ),
                ("read_product_source", {"source_id": source["id"], "path": path.name}),
                (
                    "intake_product_source",
                    lambda results: {
                        "source_id": source["id"],
                        "project_id": json.loads(results[3].content)["id"],
                        "title": "Fix midnight exports",
                        "brief": "Investigate the two customer reports",
                        # Intentionally different on every run: exact-key deduplication cannot save this race.
                        "proposal_key": "midnight-" + results[0].content,
                        "evidence_links": [path.as_uri()],
                        "evidence_hashes": {path.as_uri(): json.loads(results[4].content)["content_hash"]},
                    },
                ),
            ]
        )
        row = await create_routine(s, product["id"])
        other = dict(s.db.get_schedule(row["id"]))
        if second_routine:
            other["id"] += "-second"
            other["name"] += "-second"
            s.db.create_schedule(other)
        # Separate adapter and executor simulate another scheduler process using the same database.
        db2 = SqliteDb(db_file=str(tmp_path / "company.db"))
        contender = CompanyScheduleExecutor(
            company_db=db2,
            schedule_db=db2,
            base_url="http://test",
            internal_service_token=s.os._internal_service_token,
            poll_interval=0.01,
            timeout=10,
        )
        contender._client = s.client
        first = asyncio.create_task(s.client.post("/company/routines/" + row["id"] + "/trigger", headers=s.headers))
        try:
            await asyncio.wait_for(entered.wait(), 10)
            rejected = await asyncio.wait_for(contender.execute(other, db2), 5)
            assert rejected["status"] == "failed", rejected
            assert "Another Routine review holds this Product" in rejected["error"]
            assert rejected["run_id"] is None
            assert len(calls) == 1
        finally:
            finish.set()
            result = await asyncio.wait_for(first, 15)
        assert result.json()["status"] == "success", result.text
        assert manager.list_projects(product_id=product["id"])[1] == 1
        tasks, total = manager.list_tasks(product_id=product["id"])
        assert total == 1 and tasks[0]["status"] == "backlog"
        assert tasks[0]["evidence"] and not tasks[0].get("job_id")
        # A later review is admitted after the first run is durably completed.
        s.os.company_manager.model = ScriptedModel()
        later = await contender.execute(other, s.db, release_schedule=False)
        assert later["status"] == "success", later
        assert manager.list_projects(product_id=product["id"])[1] == 1
        assert manager.list_tasks(product_id=product["id"])[1] == 1
        db2.close()


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "PAUSED", "COMPLETED", "ERROR", "CANCELLED", "missing"])
async def test_recovery_uses_actual_run_status_not_schedule_status(tmp_path, status):
    db = SqliteDb(db_file=str(tmp_path / "state.db"))
    client = SimpleNamespace(
        request=AsyncMock(return_value=httpx.Response(404 if status == "missing" else 200, json={"status": status}))
    )
    executor = SimpleNamespace(
        company_db=db,
        base_url="http://test",
        internal_service_token="internal",
        _get_client=AsyncMock(return_value=client),
    )
    schedule = SimpleNamespace(id="review", endpoint="/agents/reviewer/runs", user_id="alice")
    claim = await _claim_review(executor, schedule, "p")
    token = _active_review.set(claim)
    try:
        await _record_review_run("run-one", "session-one")
    finally:
        _active_review.reset(token)
    if status in {"COMPLETED", "ERROR", "CANCELLED"}:
        replacement = await _claim_review(executor, schedule, "p")
        assert replacement[2]["claim_id"] != claim[2]["claim_id"]
    else:
        with pytest.raises(ValueError, match="Another Routine review"):
            await _claim_review(executor, schedule, "p")
    assert client.request.call_args.kwargs["params"] == {"session_id": "session-one"}
    # A different Product does not contend with this one.
    await _claim_review(executor, schedule, "other")
    db.close()


async def test_unknown_submission_is_not_released_by_elapsed_time(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "unknown.db"))
    executor = SimpleNamespace(company_db=db)
    schedule = SimpleNamespace(id="review", endpoint="/agents/reviewer/runs", user_id=None)
    await _claim_review(executor, schedule, "p")
    with pytest.raises(ValueError, match="submission outcome unknown"):
        await _claim_review(executor, schedule, "p")
    assert await _review_filesystem(db, "p").aread_with_meta("review.md") is not None
    db.close()


@pytest.mark.parametrize("outcome", ["timeout", "cancel", "transport", "connect", "rejected"])
async def test_failed_poll_does_not_release_a_live_review(tmp_path, monkeypatch, outcome):
    from agno.db.schemas.scheduler import Schedule
    from agno.scheduler.executor import ScheduleExecutor

    db = SqliteDb(db_file=str(tmp_path / "failure.db"))
    product = CompanyManager(db).create(name="Feedback")
    schedule = Schedule(
        id="review",
        name="review",
        cron_expr="0 9 * * *",
        endpoint="/agents/reviewer/runs",
        managed_by="company",
        payload={"metadata": {"product_id": product["id"]}},
    )
    executor = CompanyScheduleExecutor(
        company_db=db, schedule_db=db, base_url="http://test", internal_service_token="internal"
    )
    client = SimpleNamespace(request=AsyncMock(return_value=httpx.Response(200, json={"status": "RUNNING"})))
    executor._get_client = AsyncMock(return_value=client)

    async def submit(self, schedule):
        if outcome == "rejected":
            return {"status": "failed", "status_code": 422}
        if outcome == "connect":
            raise httpx.ConnectError("Not connected")
        if outcome == "transport":
            raise httpx.ReadTimeout("Response lost")
        await _record_review_run("still-running", "session")
        if outcome == "cancel":
            raise asyncio.CancelledError()
        return {"status": "failed", "run_id": "still-running", "session_id": "session", "error": "Polling timed out"}

    monkeypatch.setattr(ScheduleExecutor, "_call_endpoint", submit)
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await executor._call_endpoint(schedule)
    elif outcome == "connect":
        with pytest.raises(httpx.ConnectError):
            await executor._call_endpoint(schedule)
    elif outcome == "transport":
        with pytest.raises(httpx.ReadTimeout):
            await executor._call_endpoint(schedule)
    else:
        await executor._call_endpoint(schedule)
    assert _active_review.get() is None
    if outcome in {"rejected", "connect"}:
        await _claim_review(executor, schedule, product["id"])
    else:
        with pytest.raises(ValueError, match="Another Routine review"):
            await _claim_review(executor, schedule, product["id"])
    db.close()


async def test_interrupted_run_recording_recovers_from_schedule_record(tmp_path):
    from agno.scheduler.executor import _active_schedule_run

    db = SqliteDb(db_file=str(tmp_path / "recording.db"))
    schedule = SimpleNamespace(id="review", endpoint="/agents/reviewer/runs/", user_id="alice")
    schedule_db = SimpleNamespace(get_schedule_run=lambda _: {"run_id": "persisted", "session_id": "session"})
    client = SimpleNamespace(request=AsyncMock(return_value=httpx.Response(200, json={"status": "COMPLETED"})))
    executor = SimpleNamespace(
        company_db=db,
        schedule_db=schedule_db,
        base_url="http://test",
        internal_service_token="test",
        _get_client=AsyncMock(return_value=client),
    )
    token = _active_schedule_run.set((schedule_db, "schedule-record"))
    try:
        claim = await _claim_review(executor, schedule, "p")
    finally:
        _active_schedule_run.reset(token)
    assert claim[2]["schedule_run_id"] == "schedule-record"
    await _claim_review(executor, schedule, "p")
    assert client.request.call_args.args[1] == "http://test/agents/reviewer/runs/persisted"
    assert client.request.call_args.kwargs["headers"]["X-Schedule-Owner"] == "alice"
    db.close()


async def test_product_identity_preserves_case_and_company_table(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "identities.db"))
    peer = SqliteDb(db_file=db.db_file, products_table="other_products")
    schedule = SimpleNamespace(id="review", endpoint="/agents/reviewer/runs", user_id=None)
    try:
        await _claim_review(SimpleNamespace(company_db=db), schedule, "Product")
        await _claim_review(SimpleNamespace(company_db=db), schedule, "product")
        await _claim_review(SimpleNamespace(company_db=peer), schedule, "Product")
        with pytest.raises(ValueError, match="Another Routine review"):
            await _claim_review(SimpleNamespace(company_db=db), schedule, "Product")
    finally:
        peer.close()
        db.close()


@pytest.mark.parametrize("ticket_status", ["queued", "running", "paused", "completed", "failed", "cancelled"])
async def test_failed_attempt_with_pending_retry_keeps_product_reserved(tmp_path, ticket_status):
    db = SqliteDb(db_file=str(tmp_path / "retry.db"))
    client = SimpleNamespace(request=AsyncMock(return_value=httpx.Response(200, json={"status": "ERROR"})))
    store = SimpleNamespace(get_job=AsyncMock(return_value={"status": ticket_status}))
    executor = SimpleNamespace(
        company_db=db,
        queue_store=store,
        base_url="http://test",
        internal_service_token="test",
        _get_client=AsyncMock(return_value=client),
    )
    schedule = SimpleNamespace(id="review", endpoint="/agents/reviewer/runs", user_id=None)
    claim = await _claim_review(executor, schedule, "p")
    token = _active_review.set(claim)
    try:
        await _record_review_run("retrying", "session")
    finally:
        _active_review.reset(token)
    if ticket_status in {"completed", "failed", "cancelled"}:
        await _claim_review(executor, schedule, "p")
    else:
        with pytest.raises(ValueError, match="Another Routine review"):
            await _claim_review(executor, schedule, "p")
    store.get_job.assert_awaited_once_with("retrying", strict=True)
    db.close()
