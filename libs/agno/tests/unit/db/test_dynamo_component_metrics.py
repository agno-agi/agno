"""Unit tests for the component metrics methods of the DynamoDb class, against moto's in-process DynamoDB."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from agno.db.dynamo import DynamoDb  # noqa: E402
from agno.db.dynamo.utils import (  # noqa: E402
    aggregate_metrics_key,
    deserialize_metrics_row,
    serialize_to_dynamo_item,
)
from agno.db.migrations.manager import MigrationManager  # noqa: E402
from agno.db.utils import (  # noqa: E402
    METRICS_LOCK_SECONDS,
    METRICS_REFRESH_ID,
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_FIELDS,
)
from agno.metrics import ModelMetrics, RunMetrics, ToolCallMetrics  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.models.response import ToolExecution  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.run.workflow import WorkflowRunOutput  # noqa: E402
from agno.session.agent import AgentSession  # noqa: E402
from agno.session.team import TeamSession  # noqa: E402
from agno.session.workflow import WorkflowSession  # noqa: E402


@pytest.fixture
def dynamo_db(monkeypatch):
    """A DynamoDb on moto's in-process DynamoDB"""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        db = DynamoDb(
            db_client=boto3.client("dynamodb", region_name="us-east-1"),
            session_table="sessions",
            runs_table="runs",
            component_metrics_table="component_metrics",
            aggregate_metrics_table="aggregate_metrics",
            metrics_refreshes_table="metrics_refreshes",
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
        TableName=db.aggregate_metrics_table_name, Key=aggregate_metrics_key(aggregation_period, day, user_id)
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


def _stored_aggregate_metrics_row(db: DynamoDb, day: date, user_id: str) -> Dict[str, Any]:
    """The stored aggregate metrics row of a day and user, with its token counts flattened as get_metrics reads them."""
    row = _row(db, "daily", day, user_id)
    metric = next(
        m
        for m in db._get_aggregate_metrics_rows(day, day, user_id)[0]
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
        stored = _stored_aggregate_metrics_row(dynamo_db, day, "")
        assert {key: stored[key] for key in truth} == truth
        assert _everyone_row(dynamo_db, day)["completed"] is True
        for user_id in ["alice", "bob"]:
            user_truth = _ground_truth(dynamo_db, day, user_id)
            if not any(user_truth[f"{t}_sessions_count"] for t in ["agent", "team", "workflow"]):
                continue
            stored = _stored_aggregate_metrics_row(dynamo_db, day, user_id)
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


def test_calculate_metrics_rebuilds_a_reopened_day(dynamo_db: DynamoDb, dataset):
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


def test_session_save_reopens_the_day_the_session_is_stored_on(dynamo_db: DynamoDb, dataset):
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


def test_calculate_metrics_takes_over_a_lock_that_went_stale(dynamo_db: DynamoDb, dataset):
    """Ensure a calculation finding the refresh held by another process returns None and writes no row, and a stale
    lock reads failed and is taken over"""
    refreshes_table_name = dynamo_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert dynamo_db._claim_metrics_refresh(refreshes_table_name, "another-process") is not None

    assert dynamo_db.calculate_metrics() is None
    assert dynamo_db.get_metrics_refresh_status()["status"] == "running"
    assert _items(dynamo_db, dynamo_db._get_table("aggregate_metrics")) == []
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


def test_calculate_metrics_counts_tool_calls(dynamo_db: DynamoDb):
    """Ensure each tool call is counted under its tool, that a tool call a forked run copied is not, and that a totals
    read adds the tools up"""
    day = _utc_date(OLD_DAY)
    copied_call = ToolExecution(
        tool_call_id="copied-call",
        tool_name="search",
        tool_args={"query": "agno"},
        metrics=ToolCallMetrics(duration=0.4),
    )
    new_call = ToolExecution(tool_call_id="new-call", tool_name="search", metrics=ToolCallMetrics(duration=0.1))
    original = RunOutput(
        run_id="original_run",
        agent_id="agent-1",
        status=RunStatus.completed,
        messages=[Message(role="tool", tool_call_id="copied-call", content="agno")],
        tools=[copied_call],
        created_at=_timestamp(day),
    )
    forked = RunOutput(
        run_id="forked_run",
        agent_id="agent-1",
        status=RunStatus.completed,
        messages=[
            Message(role="tool", tool_call_id="copied-call", content="agno"),
            Message(role="tool", tool_call_id="new-call", content="agno"),
        ],
        tools=[copied_call, new_call],
        forked_from_message_index=1,
        created_at=_timestamp(day) + 1,
    )
    dynamo_db.upsert_session(
        AgentSession(session_id="s_fork", agent_id="agent-1", user_id="bob", created_at=_timestamp(day))
    )
    for run_index, run in enumerate([original, forked]):
        dynamo_db.upsert_run(run, session_id="s_fork", user_id="bob", run_index=run_index)

    dynamo_db.calculate_metrics()

    # The forked run counts only the tool call it made
    expected = {
        "": {
            "search": {
                "count": 2,
                "failed_count": 0,
                "total_ms": 500,
                "max_ms": 400,
                "buckets": {"le_100": 1, "le_400": 1},
            }
        }
    }
    metrics, _ = dynamo_db.get_component_metrics(day, day, fields=["tool_metrics"])
    assert metrics[0]["tool_metrics"] == expected
    totals, _ = dynamo_db.get_metrics_totals(day, day, user_id="bob", fields=["tool_metrics"])
    assert totals == {"tool_metrics": expected}


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


def test_get_metrics_returns_a_day_with_only_a_regenerated_run(dynamo_db: DynamoDb):
    """Ensure a day with only regenerated runs, which have tokens but no count, is returned for a user and for the
    runs with no user"""
    old_day, mid_day = _utc_date(OLD_DAY), _utc_date(MID_DAY)
    for session_id, user_id, input_tokens in [("s_alice", "alice", 10), ("s_no_user", None, 20)]:
        dynamo_db.upsert_session(
            AgentSession(session_id=session_id, agent_id="agent-1", user_id=user_id, created_at=_timestamp(old_day))
        )
        regenerated_run = RunOutput(
            run_id=f"{session_id}_run",
            agent_id="agent-1",
            user_id=user_id,
            status=RunStatus.regenerated,
            model="gpt-5.6-luna",
            model_provider="OpenAI",
            metrics=_metrics(input_tokens, 5),
            created_at=_timestamp(mid_day),
        )
        dynamo_db.upsert_run(regenerated_run, session_id=session_id, user_id=user_id, run_index=0)

    dynamo_db.calculate_metrics()

    metrics, _ = dynamo_db.get_metrics(mid_day, mid_day)
    assert [(row["user_id"], row["agent_runs_count"], row["token_metrics"]["total_tokens"]) for row in metrics] == [
        (None, 0, 25),
        ("alice", 0, 15),
    ]
