"""Unit tests for the component metrics methods of the DynamoDb class, against moto's in-process DynamoDB, or
DynamoDB Local when DYNAMODB_ENDPOINT_URL is set."""

import os
import time
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from agno.db.dynamo import DynamoDb  # noqa: E402
from agno.db.dynamo.utils import (  # noqa: E402
    deserialize_metrics_row,
    reopen_metrics_day,
    serialize_to_dynamo_item,
    user_metrics_key,
)
from agno.db.migrations.manager import MigrationManager  # noqa: E402
from agno.db.utils import (  # noqa: E402
    METRICS_LOCK_SECONDS,
    METRICS_REFRESH_ID,
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_FIELDS,
    calculate_date_component_metrics,
    get_months_to_calculate_metrics_for,
    metrics_month_end,
)
from agno.metrics import ModelMetrics, RunMetrics  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.run.workflow import WorkflowRunOutput  # noqa: E402
from agno.session.agent import AgentSession  # noqa: E402
from agno.session.team import TeamSession  # noqa: E402
from agno.session.workflow import WorkflowSession  # noqa: E402


@pytest.fixture
def dynamo_db(monkeypatch):
    """A DynamoDb on DynamoDB Local when DYNAMODB_ENDPOINT_URL is set, else on moto's in-process DynamoDB"""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    endpoint_url = os.environ.get("DYNAMODB_ENDPOINT_URL")
    prefix = f"test_{uuid4().hex[:8]}"
    with moto.mock_aws() if endpoint_url is None else nullcontext():
        db = DynamoDb(
            db_client=boto3.client("dynamodb", endpoint_url=endpoint_url, region_name="us-east-1"),
            session_table=f"{prefix}_sessions",
            runs_table=f"{prefix}_runs",
            component_metrics_table=f"{prefix}_component_metrics",
            user_metrics_table=f"{prefix}_user_metrics",
            metrics_refreshes_table=f"{prefix}_metrics_refreshes",
        )
        for table_type in ["sessions", "runs"]:
            db._get_table(table_type, create_table_if_not_found=True)
        yield db


def _items(db: DynamoDb, table_name: str) -> List[Dict[str, Any]]:
    response = db.client.scan(TableName=table_name)
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = db.client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return [deserialize_metrics_row(item) for item in items]


def _row(db: DynamoDb, aggregation_period: str, day: date, user_id: str) -> Optional[Dict[str, Any]]:
    item = db.client.get_item(
        TableName=db.user_metrics_table_name, Key=user_metrics_key(aggregation_period, day, user_id)
    ).get("Item")
    return deserialize_metrics_row(item) if item else None


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _timestamp(day: date, hour: int = 12) -> int:
    return int(datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc).timestamp())


def _metrics(input_tokens: int, output_tokens: int, **extra: Any) -> RunMetrics:
    tokens = dict(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens)
    return RunMetrics(
        **tokens, **extra, details={"model": [ModelMetrics(id="gpt-5.6-luna", provider="OpenAI", **tokens)]}
    )


def _everyone_row(db: DynamoDb, day: date) -> Optional[Dict[str, Any]]:
    return _row(db, "daily", day, "")


def _backdate(db: DynamoDb) -> None:
    """Date every update of the sessions and runs to a minute ago, so none was updated in the current second."""
    for table_name, key_name in [(db.session_table_name, "session_id"), (db.runs_table_name, "run_id")]:
        for item in db.client.scan(TableName=table_name).get("Items", []):
            db.client.update_item(
                TableName=table_name,
                Key={key_name: item[key_name]},
                UpdateExpression="SET updated_at = :updated_at",
                ExpressionAttributeValues={":updated_at": {"N": str(int(time.time()) - 60)}},
            )


OLD_DAY = 4
MID_DAY = 3


@pytest.fixture
def dataset(dynamo_db: DynamoDb) -> Dict[str, Any]:
    """Store an agent, a team with a member and a workflow for two users and no user over two old days, and a paused
    run on the later day."""
    old_day, mid_day = _utc_date(OLD_DAY), _utc_date(MID_DAY)
    agent_run = RunOutput(
        run_id="agent_run",
        agent_id="agent-1",
        user_id="alice",
        status=RunStatus.completed,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=_metrics(10, 5, cache_read_tokens=3, additional_metrics={"eval_duration": 1.5}),
        created_at=_timestamp(old_day),
    )
    member_run = RunOutput(
        run_id="member_run",
        agent_id="member-1",
        user_id="bob",
        parent_run_id="team_run",
        status=RunStatus.completed,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=_metrics(7, 3, cache_write_tokens=2),
        created_at=_timestamp(old_day),
    )
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        user_id="bob",
        status=RunStatus.completed,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=_metrics(20, 10),
        member_responses=[member_run],
        created_at=_timestamp(old_day),
    )
    workflow_run = WorkflowRunOutput(
        run_id="workflow_run", workflow_id="workflow-1", status=RunStatus.completed, created_at=_timestamp(mid_day)
    )
    paused_run = RunOutput(
        run_id="paused_run",
        agent_id="agent-1",
        user_id="alice",
        status=RunStatus.paused,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=_metrics(4, 1),
        created_at=_timestamp(mid_day),
    )
    sessions = [
        (
            AgentSession(session_id="s_agent", agent_id="agent-1", user_id="alice", created_at=_timestamp(old_day)),
            "alice",
            [agent_run],
        ),
        (
            TeamSession(session_id="s_team", team_id="team-1", user_id="bob", created_at=_timestamp(old_day)),
            "bob",
            [team_run, member_run],
        ),
        (
            WorkflowSession(session_id="s_workflow", workflow_id="workflow-1", created_at=_timestamp(mid_day)),
            None,
            [workflow_run],
        ),
        (
            AgentSession(session_id="s_paused", agent_id="agent-1", user_id="alice", created_at=_timestamp(mid_day)),
            "alice",
            [paused_run],
        ),
    ]
    for session, user_id, runs in sessions:
        dynamo_db.upsert_session(session)
        for run_index, run in enumerate(runs):
            dynamo_db.upsert_run(run, session_id=session.session_id, user_id=user_id, run_index=run_index)
    return {"paused_run": paused_run}


def _ground_truth(db: DynamoDb, day: date, user_id: Optional[str]) -> Dict[str, Any]:
    """Count a day's sessions and runs straight from the stored sessions and runs, of every user for None."""
    start, end = _timestamp(day, 0), _timestamp(day, 0) + 86400
    sessions = [
        s
        for s in _items(db, db.session_table_name)
        if start <= s["created_at"] < end and (user_id is None or s.get("user_id") == user_id)
    ]
    runs = [
        r
        for r in _items(db, db.runs_table_name)
        if start <= r["created_at"] < end and (user_id is None or r.get("user_id") == user_id)
    ]
    truth: Dict[str, Any] = {
        f"{component_type}_{kind}_count": 0
        for component_type in ["agent", "team", "workflow"]
        for kind in ["sessions", "runs"]
    }
    for session in sessions:
        truth[f"{session['session_type']}_sessions_count"] += 1
    for run in runs:
        truth[f"{run['run_type']}_runs_count"] += 1
    truth["root_runs_count"] = sum(1 for run in runs if not run.get("parent_run_id"))
    truth["users_count"] = len({s["user_id"] for s in sessions if s.get("user_id")})
    for field in METRICS_TOKEN_FIELDS:
        truth[field] = sum((run["run_data"].get("metrics") or {}).get(field) or 0 for run in runs)
    return truth


def _stored_user_metrics_row(db: DynamoDb, day: date, user_id: str) -> Dict[str, Any]:
    """The stored user metrics row of a day and user, with its token counts flattened as get_metrics reads them."""
    row = _row(db, "daily", day, user_id)
    metric = next(
        m
        for m in db._get_user_metrics_rows(day, day, user_id)[0]
        if m["date"] == day and (m["user_id"] or "") == user_id
    )
    return {
        **{column: row[column] for column in metric if column.endswith("_count")},
        "root_runs_count": row["root_runs_count"],
        **metric["token_metrics"],
    }


def test_calculate_metrics_matches_the_stored_sessions_and_runs(dynamo_db: DynamoDb, dataset):
    """Ensure every day's everyone row and user rows count what a direct count of the sessions and runs finds"""
    assert dynamo_db.calculate_metrics()

    for day in [_utc_date(OLD_DAY), _utc_date(MID_DAY)]:
        truth = _ground_truth(dynamo_db, day, None)
        stored = _stored_user_metrics_row(dynamo_db, day, "")
        assert {key: stored[key] for key in truth} == truth
        assert _everyone_row(dynamo_db, day)["completed"] is True
        for user_id in ["alice", "bob"]:
            user_truth = _ground_truth(dynamo_db, day, user_id)
            if not any(user_truth[f"{t}_sessions_count"] for t in ["agent", "team", "workflow"]):
                continue
            stored = _stored_user_metrics_row(dynamo_db, day, user_id)
            assert {key: stored[key] for key in user_truth} == user_truth

    totals, _ = dynamo_db.get_metrics_totals(
        _utc_date(OLD_DAY),
        _utc_date(MID_DAY),
        fields=["root_runs_count", "total_tokens", "cache_read_tokens", "cache_write_tokens", "additional_metrics"],
    )
    # The member run counts its own tokens once, not again inside the team run
    assert totals["root_runs_count"] == 4
    assert totals["total_tokens"] == 15 + 30 + 10 + 5
    assert (totals["cache_read_tokens"], totals["cache_write_tokens"]) == (3, 2)
    assert totals["additional_metrics"] == {"eval_duration": 1.5}

    metrics, _ = dynamo_db.get_metrics(_utc_date(OLD_DAY), _utc_date(MID_DAY))
    assert {(m["date"], m["user_id"]) for m in metrics} == {
        (_utc_date(OLD_DAY), "alice"),
        (_utc_date(OLD_DAY), "bob"),
        (_utc_date(MID_DAY), "alice"),
        (_utc_date(MID_DAY), None),
    }


def test_a_completed_run_reopens_its_old_day(dynamo_db: DynamoDb, dataset):
    """Ensure saving a paused run as completed reopens its day, which the next calculation rebuilds and completes"""
    dynamo_db.calculate_metrics()
    mid_day = _utc_date(MID_DAY)
    version = _everyone_row(dynamo_db, mid_day)["version"]
    totals, _ = dynamo_db.get_metrics_totals(mid_day, mid_day, user_id="alice", fields=["status_metrics"])
    assert totals["status_metrics"] == {"PAUSED": 1}

    paused_run = dataset["paused_run"]
    paused_run.status = RunStatus.completed
    dynamo_db.upsert_run(paused_run, session_id="s_paused", user_id="alice")
    reopened = _everyone_row(dynamo_db, mid_day)
    assert (reopened["completed"], reopened["version"], reopened["open_period"]) == (False, version + 1, "daily")
    # The resumed run keeps the day it was created on
    assert dynamo_db.get_run("paused_run", deserialize=False)["created_at"] == _timestamp(mid_day)

    assert mid_day in [metric["date"] for metric in dynamo_db.calculate_metrics()]
    completed_row = _everyone_row(dynamo_db, mid_day)
    assert completed_row["completed"] is True and "open_period" not in completed_row
    totals, _ = dynamo_db.get_metrics_totals(mid_day, mid_day, user_id="alice", fields=["status_metrics"])
    assert totals["status_metrics"] == {"COMPLETED": 1}


def test_a_delete_does_not_reopen_its_day(dynamo_db: DynamoDb, dataset):
    """Ensure deleting a run of an old day leaves its day completed and its version as it was"""
    dynamo_db.calculate_metrics()
    old_row = _everyone_row(dynamo_db, _utc_date(OLD_DAY))

    assert dynamo_db.delete_run("agent_run")
    assert _everyone_row(dynamo_db, _utc_date(OLD_DAY)) == old_row
    assert _utc_date(OLD_DAY) not in [metric["date"] for metric in dynamo_db.calculate_metrics() or []]


def test_a_session_write_reopens_only_when_it_moves_the_session(dynamo_db: DynamoDb, dataset):
    """Ensure saving a session again leaves its day, and moving it to another component reopens it"""
    dynamo_db.calculate_metrics()
    old_day = _utc_date(OLD_DAY)
    version = _everyone_row(dynamo_db, old_day)["version"]

    session = AgentSession(session_id="s_agent", agent_id="agent-1", user_id="alice", created_at=_timestamp(old_day))
    dynamo_db.upsert_session(session)
    assert _everyone_row(dynamo_db, old_day)["version"] == version

    session.agent_id = "agent-2"
    dynamo_db.upsert_session(session)
    assert (_everyone_row(dynamo_db, old_day)["completed"], _everyone_row(dynamo_db, old_day)["version"]) == (
        False,
        version + 1,
    )


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(dynamo_db: DynamoDb, dataset):
    """Ensure a calculation with nothing new builds nothing, and rebuild_from rebuilds every day from that date"""
    dynamo_db.calculate_metrics()
    # Only yesterday and today can be rebuilt, when a write of this second leaves their fingerprint unknown
    assert set(dynamo_db.calculate_metrics_dates() or []) <= {_utc_date(1), _utc_date(0)}

    rebuilt = dynamo_db.calculate_metrics_dates(rebuild_from=_utc_date(OLD_DAY))
    assert rebuilt is not None and {_utc_date(OLD_DAY), _utc_date(MID_DAY)} <= set(rebuilt)
    assert _everyone_row(dynamo_db, _utc_date(OLD_DAY))["completed"] is True


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_completes(
    dynamo_db: DynamoDb, dataset
):
    """Ensure rebuild_from leaves yesterday and today to the next calculation when another process holds the metrics
    refresh and completes it with the fingerprint it read before the rebuild"""
    _backdate(dynamo_db)
    dynamo_db.calculate_metrics()
    refreshes_table_name = dynamo_db._get_table("metrics_refreshes")
    refresh_row = dynamo_db._claim_metrics_refresh(refreshes_table_name, "other_process")
    assert refresh_row is not None and refresh_row["fingerprint"] is not None

    assert dynamo_db.calculate_metrics(rebuild_from=_utc_date(MID_DAY)) is None

    dynamo_db._release_metrics_refresh(
        refreshes_table_name,
        "other_process",
        fingerprint=refresh_row["fingerprint"],
        claimed_fingerprint=refresh_row["fingerprint"],
    )
    assert {_utc_date(MID_DAY), _utc_date(1), _utc_date(0)} <= set(dynamo_db.calculate_metrics_dates() or [])
    assert dynamo_db.calculate_metrics_dates() == []


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_claimed_no_fingerprint(
    dynamo_db: DynamoDb, dataset
):
    """Ensure a release over a claim of no fingerprint keeps the mark a rebuild wrote after the claim"""
    refreshes_table_name = dynamo_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    refresh_row = dynamo_db._claim_metrics_refresh(refreshes_table_name, "other_process")
    assert refresh_row is not None and refresh_row["fingerprint"] is None

    assert dynamo_db.calculate_metrics(rebuild_from=_utc_date(0)) is None
    dynamo_db._release_metrics_refresh(
        refreshes_table_name, "other_process", fingerprint=["today"], claimed_fingerprint=None
    )

    refresh_row = dynamo_db._get_metrics_refresh_row(refreshes_table_name)[0]
    assert (refresh_row["status"], refresh_row["fingerprint"][0]) == ("completed", "rebuild")


def test_calculate_metrics_rebuild_from_records_a_failed_reopen(dynamo_db: DynamoDb, dataset, monkeypatch):
    """Ensure a rebuild that fails before its claim marks the refresh failed with its error"""
    dynamo_db.calculate_metrics()

    def _fail(*args: Any) -> None:
        raise RuntimeError("reopen failed")

    monkeypatch.setattr("agno.db.dynamo.dynamo.reopen_metrics_days_from", _fail)
    with pytest.raises(RuntimeError):
        dynamo_db.calculate_metrics_dates(rebuild_from=_utc_date(OLD_DAY))

    status = dynamo_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", "reopen failed")


def test_calculate_metrics_returns_none_while_another_process_holds_the_refresh(dynamo_db: DynamoDb, dataset):
    """Ensure a calculation finding the refresh held by another process returns None and writes no row, and a stale
    lock reads failed and is taken over"""
    refreshes_table_name = dynamo_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert dynamo_db._claim_metrics_refresh(refreshes_table_name, "another-process") is not None

    assert dynamo_db.calculate_metrics() is None
    assert dynamo_db.get_metrics_refresh_status()["status"] == "running"
    assert _items(dynamo_db, dynamo_db._get_table("user_metrics")) == []
    assert _items(dynamo_db, dynamo_db._get_table("component_metrics")) == []

    # A lock without a heartbeat for longer than its lease went stale: its process stopped
    dynamo_db.client.update_item(
        TableName=refreshes_table_name,
        Key={"id": {"S": METRICS_REFRESH_ID}},
        UpdateExpression="SET #locked_at = :locked_at",
        ExpressionAttributeNames={"#locked_at": "locked_at"},
        ExpressionAttributeValues={":locked_at": {"N": str(int(time.time()) - METRICS_LOCK_SECONDS)}},
    )
    status = dynamo_db.get_metrics_refresh_status()
    assert (status["status"], status["finished_at"]) == ("failed", None)
    assert dynamo_db.calculate_metrics()
    status = dynamo_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)
    assert status["finished_at"] is not None


def test_a_failed_refresh_keeps_the_last_finished_at(dynamo_db: DynamoDb, dataset):
    """Ensure finished_at moves only when a refresh completes, and a failed one keeps its error"""
    refreshes_table_name = dynamo_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    dynamo_db.calculate_metrics()
    finished_at = dynamo_db._get_metrics_refresh_row(refreshes_table_name)[0]["finished_at"]

    assert dynamo_db._claim_metrics_refresh(refreshes_table_name, "worker") is not None
    # Another worker never releases a refresh it does not hold
    dynamo_db._release_metrics_refresh(refreshes_table_name, "another-worker", error="ignored")
    assert dynamo_db.get_metrics_refresh_status()["status"] == "running"
    dynamo_db._release_metrics_refresh(refreshes_table_name, "worker", error="boom")
    refresh_row = dynamo_db._get_metrics_refresh_row(refreshes_table_name)[0]
    assert (refresh_row["status"], refresh_row["error"], refresh_row["finished_at"]) == ("failed", "boom", finished_at)
    assert refresh_row["locked_by"] is None
    assert not dynamo_db._heartbeat_metrics_refresh(refreshes_table_name, "worker")


def test_a_day_without_sessions_or_runs_is_not_read(dynamo_db: DynamoDb, dataset):
    """Ensure yesterday, built with no session or run, keeps an everyone row of zeros that get_metrics leaves out"""
    dynamo_db.calculate_metrics()
    assert _everyone_row(dynamo_db, _utc_date(1)) is not None
    metrics, _ = dynamo_db.get_metrics_by_date(_utc_date(OLD_DAY), _utc_date(0))
    assert [metric["date"] for metric in metrics] == [_utc_date(OLD_DAY), _utc_date(MID_DAY)]


def test_calculate_metrics_with_nothing_changed_returns_today(dynamo_db: DynamoDb, dataset):
    """Ensure a calculation that finds nothing changed returns today's metrics"""
    dynamo_db.upsert_session(
        AgentSession(session_id="s_today", agent_id="agent-1", user_id="carol", created_at=int(time.time()))
    )
    _backdate(dynamo_db)
    dynamo_db.calculate_metrics()
    assert dynamo_db.calculate_metrics_dates() == []
    metrics = dynamo_db.calculate_metrics()
    assert [(metric["date"], metric["user_id"]) for metric in metrics or []] == [(_utc_date(0), "carol")]


def test_reads_never_calculate(dynamo_db: DynamoDb, dataset):
    """Ensure a read before the first calculation reads the deprecated table and calculates nothing"""
    assert dynamo_db.get_metrics() == ([], None)
    assert dynamo_db.get_metrics_refresh_status() is None

    dynamo_db.calculate_metrics()
    metrics, latest_updated_at = dynamo_db.get_metrics(_utc_date(OLD_DAY), _utc_date(MID_DAY))
    assert metrics and latest_updated_at is not None


def test_month_rows_total_the_days_of_a_month(dynamo_db: DynamoDb):
    """Ensure a completed month has a month user metrics row per user and an everyone row adding up its days"""
    old_day = _utc_date(40)
    month_start = old_day.replace(day=1)
    for session_id, user_id, day in [("s_alice", "alice", old_day), ("s_bob", "bob", month_start)]:
        dynamo_db.upsert_session(
            AgentSession(session_id=session_id, agent_id="agent-1", user_id=user_id, created_at=_timestamp(day))
        )
    dynamo_db.calculate_metrics()
    month_rows = [
        row
        for row in _items(dynamo_db, dynamo_db.user_metrics_table_name)
        if row["aggregation_period"] == "monthly" and row["date"] == month_start
    ]
    everyone_row = next(row for row in month_rows if row["user_id"] == "")
    assert (everyone_row["completed"], everyone_row["users_count"]) == (True, 2)
    assert {row["user_id"] for row in month_rows} >= {""}


def test_calculate_metrics_builds_no_month_before_its_last_day_can_be_completed(dynamo_db: DynamoDb):
    """Ensure the month of today is left unbuilt, as a month row is read only once completed"""
    today = _utc_date(0)
    dynamo_db.upsert_session(
        AgentSession(session_id="s_today", agent_id="agent-1", user_id="alice", created_at=int(time.time()))
    )
    dynamo_db.calculate_metrics()

    assert _everyone_row(dynamo_db, today)["agent_sessions_count"] == 1
    month_row = _row(dynamo_db, "monthly", today.replace(day=1), "")
    assert (month_row["completed"], month_row["agent_sessions_count"]) == (False, 0)


def test_legacy_member_runs_are_counted_once(dynamo_db: DynamoDb):
    """Ensure a team member run kept both in its team run and as a legacy run of the session, finished after
    midnight, counts its tokens once"""
    old_day, next_day = _utc_date(OLD_DAY), _utc_date(MID_DAY)
    member_run = RunOutput(
        run_id="legacy_member",
        agent_id="member-1",
        parent_run_id="legacy_team",
        status=RunStatus.completed,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=_metrics(7, 3),
        created_at=_timestamp(next_day, 0),
    )
    team_run = TeamRunOutput(
        run_id="legacy_team",
        team_id="team-1",
        status=RunStatus.completed,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=_metrics(20, 10),
        member_responses=[member_run],
        created_at=_timestamp(old_day),
    )
    dynamo_db.client.put_item(
        TableName=dynamo_db.session_table_name,
        Item=serialize_to_dynamo_item(
            {
                "session_id": "legacy",
                "session_type": "team",
                "team_id": "team-1",
                "created_at": _timestamp(old_day),
                "updated_at": int(time.time()) - 60,
                "runs": [team_run.to_dict(), member_run.to_dict()],
            }
        ),
    )
    # Not yet migrated to v3.0.0, so the legacy runs are read
    dynamo_db.upsert_schema_version(dynamo_db.session_table_name, "2.5.0")
    # The member run's day holds no session or run of the tables, only the legacy run
    dynamo_db.calculate_metrics()
    totals, _ = dynamo_db.get_metrics_totals(old_day, next_day, fields=["total_tokens", "root_runs_count"])
    assert totals == {"total_tokens": 40, "root_runs_count": 1}


def test_calculate_metrics_counts_a_remote_member_run_once(dynamo_db: DynamoDb):
    """Ensure a remote member's run, stored by its own AgentOS with no parent in a session named after the team's
    session, is counted under the team on a shared database: the team's run is the one root run and session"""
    day = _utc_date(OLD_DAY)
    remote_session_id = "team_session:remote-agent"

    def _remote_run(parent_run_id: Optional[str]) -> RunOutput:
        return RunOutput(
            run_id="remote_run",
            agent_id="remote-agent",
            session_id=remote_session_id,
            parent_run_id=parent_run_id,
            status=RunStatus.completed,
            metrics=_metrics(7, 3),
            created_at=_timestamp(day),
        )

    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        session_id="team_session",
        status=RunStatus.completed,
        metrics=_metrics(20, 10),
        member_responses=[_remote_run("team_run")],
        created_at=_timestamp(day),
    )
    dynamo_db.upsert_session(TeamSession(session_id="team_session", team_id="team-1", created_at=_timestamp(day)))
    dynamo_db.upsert_run(team_run, session_id="team_session", run_index=0)
    dynamo_db.upsert_session(
        AgentSession(session_id=remote_session_id, agent_id="remote-agent", created_at=_timestamp(day))
    )
    dynamo_db.upsert_run(_remote_run(None), session_id=remote_session_id, run_index=0)

    dynamo_db.calculate_metrics()

    everyone_row = _everyone_row(dynamo_db, day)
    assert (
        everyone_row["root_runs_count"],
        everyone_row["agent_sessions_count"],
        everyone_row["team_sessions_count"],
    ) == (1, 0, 1)


def test_calculate_metrics_counts_a_remote_member_run_two_days_after_its_team_run_as_a_root_run(dynamo_db: DynamoDb):
    """Ensure a remote member's run two days after its team's run is counted as a root run, as only the day before
    is read for its team's run"""
    day, team_day = _utc_date(OLD_DAY), _utc_date(OLD_DAY + 2)
    remote_session_id = "team_session:remote-agent"

    def _remote_run(parent_run_id: Optional[str]) -> RunOutput:
        return RunOutput(
            run_id="remote_run",
            agent_id="remote-agent",
            session_id=remote_session_id,
            parent_run_id=parent_run_id,
            status=RunStatus.completed,
            metrics=_metrics(7, 3),
            created_at=_timestamp(day),
        )

    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        session_id="team_session",
        status=RunStatus.completed,
        metrics=_metrics(20, 10),
        member_responses=[_remote_run("team_run")],
        created_at=_timestamp(team_day),
    )
    dynamo_db.upsert_session(TeamSession(session_id="team_session", team_id="team-1", created_at=_timestamp(team_day)))
    dynamo_db.upsert_run(team_run, session_id="team_session", run_index=0)
    dynamo_db.upsert_session(
        AgentSession(session_id=remote_session_id, agent_id="remote-agent", created_at=_timestamp(day))
    )
    dynamo_db.upsert_run(_remote_run(None), session_id=remote_session_id, run_index=0)

    dynamo_db.calculate_metrics()

    remote_rows = [
        row
        for row in _items(dynamo_db, dynamo_db._get_table("component_metrics"))
        if row["component_id"] == "remote-agent"
    ]
    assert [(row["parent_component_id"], row["root_component_id"]) for row in remote_rows] == [("", "remote-agent")]


def test_a_created_sessions_table_reads_no_legacy_runs(dynamo_db: DynamoDb, monkeypatch):
    """Ensure the sessions table this class creates is stamped with the latest schema version, so a refresh never
    reads every session for legacy runs"""
    dynamo_db.upsert_session(AgentSession(session_id="s1", agent_id="agent-1", created_at=_timestamp(_utc_date(1))))
    legacy_reads: List[Any] = []
    monkeypatch.setattr(dynamo_db, "_get_metrics_legacy_runs", lambda *args: legacy_reads.append(args) or ({}, {}))

    dynamo_db.calculate_metrics()

    latest_schema_version = MigrationManager(dynamo_db).latest_schema_version.public
    assert dynamo_db.get_latest_schema_version(dynamo_db.session_table_name) == latest_schema_version
    assert legacy_reads == []


def test_an_unstamped_sessions_table_with_no_legacy_runs_is_read_for_them_once(dynamo_db: DynamoDb, monkeypatch):
    """Ensure a sessions table stamped with no version, as 3.0 and 3.1 left it, is read for legacy runs once, and not
    again once that read of every session found none"""
    dynamo_db.upsert_session(AgentSession(session_id="s1", agent_id="agent-1", created_at=_timestamp(_utc_date(1))))
    monkeypatch.setattr(dynamo_db, "get_latest_schema_version", lambda table_name="": "2.0.0")
    legacy_reads: List[Any] = []
    monkeypatch.setattr(dynamo_db, "_get_metrics_legacy_runs", lambda *args: legacy_reads.append(args) or ({}, {}))

    assert dynamo_db.calculate_metrics_dates()
    dynamo_db.upsert_session(AgentSession(session_id="s2", agent_id="agent-1", created_at=_timestamp(_utc_date(1))))
    assert dynamo_db.calculate_metrics_dates()

    # The one read starts at 0, so it read every session
    assert [args[2] for args in legacy_reads] == [0]


def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(dynamo_db: DynamoDb, dataset, monkeypatch):
    """Ensure a stale row is deleted, and a day reopened after its version was read stays open"""
    dynamo_db.calculate_metrics()
    old_day = _utc_date(OLD_DAY)
    dynamo_db.delete_session("s_team")

    def reopen_during_rebuild(date_to_process, *args):
        # A write of the day lands after the rebuild read the day's version
        if date_to_process == old_day:
            reopen_metrics_day(dynamo_db.client, dynamo_db.user_metrics_table_name, old_day)
        return calculate_date_component_metrics(date_to_process, *args)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.dynamo.dynamo.calculate_date_component_metrics", reopen_during_rebuild)
        dynamo_db.calculate_metrics(rebuild_from=old_day)

    rows = [row for row in _items(dynamo_db, dynamo_db.component_metrics_table_name) if row["date"] == old_day]
    assert {row["user_id"] for row in rows} == {"alice"}
    assert _row(dynamo_db, "daily", old_day, "bob") is None
    assert _everyone_row(dynamo_db, old_day)["completed"] is False

    dynamo_db.calculate_metrics()
    assert _everyone_row(dynamo_db, old_day)["completed"] is True


def test_calculate_metrics_no_sessions(dynamo_db: DynamoDb):
    """Ensure a database without a sessions table calculates and creates nothing, and reads no metrics"""
    db = DynamoDb(db_client=dynamo_db.client, session_table=f"empty_{uuid4().hex[:8]}_sessions")

    assert db.calculate_metrics() == []
    assert not db.table_exists(db.session_table_name)
    assert db.get_metrics() == ([], None)
    assert db.get_metrics_refresh_status() is None


def test_a_stopped_calculation_releases_the_refresh(dynamo_db: DynamoDb, dataset):
    """Ensure a stopped first calculation reads failed, and a later stopped one leaves the last completed refresh as
    it was"""
    assert dynamo_db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = dynamo_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)

    dynamo_db.calculate_metrics()
    finished_at = dynamo_db.get_metrics_refresh_status()["finished_at"]
    assert dynamo_db.calculate_metrics_dates(should_stop=lambda: True, rebuild_from=_utc_date(OLD_DAY)) is None
    status = dynamo_db.get_metrics_refresh_status()
    assert (status["status"], status["error"], status["finished_at"]) == ("completed", None, finished_at)


def test_calculate_metrics_rebuilds_the_month_of_a_day_rebuilt_before_a_stop(dynamo_db: DynamoDb, monkeypatch):
    """Ensure a month whose day was rebuilt by a calculation that stopped before its months stays open, is read from
    its days meanwhile, and is rebuilt by the next calculation"""
    old_day = _utc_date(40)
    month_start = old_day.replace(day=1)

    def _run(run_id: str) -> RunOutput:
        return RunOutput(
            run_id=run_id,
            agent_id="agent-1",
            user_id="alice",
            status=RunStatus.completed,
            model="gpt-5.6-luna",
            model_provider="OpenAI",
            metrics=_metrics(10, 5),
            created_at=_timestamp(old_day),
        )

    dynamo_db.upsert_session(
        AgentSession(session_id="s_month", agent_id="agent-1", user_id="alice", created_at=_timestamp(old_day))
    )
    dynamo_db.upsert_run(_run("month_run_1"), session_id="s_month", user_id="alice", run_index=0)
    dynamo_db.calculate_metrics()
    assert _row(dynamo_db, "monthly", month_start, "")["completed"] is True

    dynamo_db.upsert_run(_run("month_run_2"), session_id="s_month", user_id="alice", run_index=1)
    stop = {"months": False}

    def _months_then_stop(days):
        stop["months"] = True
        return get_months_to_calculate_metrics_for(days)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.dynamo.dynamo.get_months_to_calculate_metrics_for", _months_then_stop)
        assert dynamo_db.calculate_metrics_dates(should_stop=lambda: stop["months"]) is None
    assert _row(dynamo_db, "monthly", month_start, "")["completed"] is False
    totals, _ = dynamo_db.get_metrics_totals(month_start, metrics_month_end(month_start), fields=["total_tokens"])
    assert totals == {"total_tokens": 30}

    dynamo_db.calculate_metrics()
    month_row = _row(dynamo_db, "monthly", month_start, "")
    assert (month_row["completed"], month_row["total_tokens"]) == (True, 30)


def test_get_metrics_versions(dynamo_db: DynamoDb, dataset):
    """Ensure versions are None until a first calculation finished, then keyed by period and date, and the version of
    a reopened day moves once it is rebuilt"""
    old_day = _utc_date(OLD_DAY)
    assert dynamo_db.get_metrics_versions(old_day, _utc_date(0)) is None

    dynamo_db.calculate_metrics()
    versions = dynamo_db.get_metrics_versions(old_day, _utc_date(0))
    assert versions is not None and versions[f"daily {old_day.isoformat()}"] == 1
    assert f"daily {_utc_date(0).isoformat()}" in versions

    paused_run = dataset["paused_run"]
    paused_run.status = RunStatus.completed
    dynamo_db.upsert_run(paused_run, session_id="s_paused", user_id="alice")
    dynamo_db.calculate_metrics()
    moved = dynamo_db.get_metrics_versions(old_day, _utc_date(0))
    mid_key = f"daily {_utc_date(MID_DAY).isoformat()}"
    assert moved[mid_key] > versions[mid_key]
    assert moved[f"daily {old_day.isoformat()}"] == versions[f"daily {old_day.isoformat()}"]
