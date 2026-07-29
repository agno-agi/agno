"""Unit tests for AgentOSTools toolkit.

Uses a real SqliteDb (and AsyncSqliteDb) backed by a pytest tmp_path so the
full db read path is exercised, not mocked.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest

from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.tools.agentos import AgentOSTools
from agno.tracing.schemas import Span, Trace

# ----------------------------------------------------------------------
# Fixtures and helpers
# ----------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="agentos-test-db", db_file=str(tmp_path / "agentos.db"))


@pytest.fixture
def async_db(tmp_path):
    return AsyncSqliteDb(id="agentos-test-async-db", db_file=str(tmp_path / "agentos_async.db"))


@pytest.fixture
def toolkit(db):
    return AgentOSTools(db=db)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _make_trace(
    agent_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    session_id: Optional[str] = "session-1",
    user_id: Optional[str] = "user-1",
    duration_ms: int = 100,
    status: str = "OK",
    minutes_ago: int = 5,
) -> Trace:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return Trace(
        trace_id=str(uuid.uuid4()),
        name="Agent.run",
        status=status,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        total_spans=0,
        error_count=1 if status == "ERROR" else 0,
        run_id=None,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        team_id=team_id,
        workflow_id=workflow_id,
        created_at=start,
    )


def _make_span(
    trace_id: str,
    name: str = "my_tool",
    span_type: Optional[str] = "TOOL",
    duration_ms: int = 100,
    status_code: str = "OK",
    minutes_ago: int = 5,
) -> Span:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    attributes: Dict[str, Any] = {"openinference.span.kind": span_type} if span_type else {}
    return Span(
        span_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_span_id=None,
        name=name,
        span_kind="INTERNAL",
        status_code=status_code,
        status_message=None,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        attributes=attributes,
        created_at=start,
    )


ALL_TOOLS = {
    "get_platform_metrics",
    "get_run_activity",
    "get_tool_activity",
    "get_eval_history",
    "list_schedules",
    "get_schedule_history",
    "list_platform_components",
    "list_pending_approvals",
}


# ----------------------------------------------------------------------
# Initialization and flags
# ----------------------------------------------------------------------


class TestInitialization:
    def test_default_registers_all_tools(self, toolkit):
        assert ALL_TOOLS == set(toolkit.functions.keys())

    def test_async_variants_match_sync(self, toolkit):
        assert set(toolkit.async_functions.keys()) == set(toolkit.functions.keys())

    def test_flags_disable_surfaces(self, db):
        toolkit = AgentOSTools(db=db, schedules=False, approvals=False, components=False)
        expected = ALL_TOOLS - {
            "list_schedules",
            "get_schedule_history",
            "list_pending_approvals",
            "list_platform_components",
        }
        assert expected == set(toolkit.functions.keys())

    def test_metrics_only(self, db):
        toolkit = AgentOSTools(db=db, traces=False, schedules=False, evals=False, components=False, approvals=False)
        assert {"get_platform_metrics"} == set(toolkit.functions.keys())

    def test_add_instructions_defaults_on_and_respects_override(self, db):
        assert AgentOSTools(db=db).add_instructions is True
        assert AgentOSTools(db=db, add_instructions=False).add_instructions is False

    def test_instructions_mention_read_only(self, toolkit):
        assert "read-only" in toolkit.instructions

    def test_requires_db(self):
        with pytest.raises(ValueError):
            AgentOSTools(db=None)  # type: ignore[arg-type]

    def test_async_db_disables_components_by_default(self, async_db):
        toolkit = AgentOSTools(db=async_db)
        assert "list_platform_components" not in toolkit.functions
        assert ALL_TOOLS - {"list_platform_components"} == set(toolkit.functions.keys())

    def test_async_db_components_true_raises(self, async_db):
        with pytest.raises(ValueError):
            AgentOSTools(db=async_db, components=True)


# ----------------------------------------------------------------------
# Db layer: get_trace_stats default shape (backwards compatibility)
# ----------------------------------------------------------------------


class TestTraceStatsDefaultShape:
    def test_default_output_shape_is_unchanged(self, db):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="session-1", minutes_ago=10))
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="session-1", minutes_ago=9))
        db.upsert_trace(_make_trace(agent_id="agent-2", session_id="session-2", minutes_ago=1))

        rows, total = db.get_trace_stats()

        assert total == 2
        assert len(rows) == 2
        expected_keys = {
            "session_id",
            "user_id",
            "agent_id",
            "team_id",
            "workflow_id",
            "total_traces",
            "first_trace_at",
            "last_trace_at",
        }
        for row in rows:
            assert set(row.keys()) == expected_keys
            assert isinstance(row["first_trace_at"], datetime)
            assert isinstance(row["last_trace_at"], datetime)
        # Ordered by last activity, most recent session first
        assert rows[0]["session_id"] == "session-2"
        assert rows[1]["total_traces"] == 2

    def test_invalid_group_by_raises(self, db):
        with pytest.raises(ValueError):
            db.get_trace_stats(group_by="bogus")  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Db layer: get_trace_stats component groupings
# ----------------------------------------------------------------------


class TestTraceStatsGroupBy:
    def test_group_by_agent_aggregates(self, db):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", duration_ms=300, status="ERROR"))
        db.upsert_trace(_make_trace(agent_id="agent-2", session_id="s3", duration_ms=50))
        # Endpoint-level trace: no component ids, must be excluded from the grouping
        db.upsert_trace(_make_trace(session_id=None, user_id=None))

        rows, total = db.get_trace_stats(group_by="agent")

        assert total == 2
        assert len(rows) == 2
        # Ordered by total_traces descending
        top = rows[0]
        assert top["agent_id"] == "agent-1"
        assert top["total_traces"] == 2
        assert top["total_sessions"] == 2
        assert top["avg_duration_ms"] == 200.0
        assert top["max_duration_ms"] == 300
        assert top["error_traces"] == 1
        assert top["p95_duration_ms"] is None  # SQLite has no percentile function
        assert isinstance(top["first_trace_at"], datetime)
        assert isinstance(top["last_trace_at"], datetime)

    def test_group_by_workflow(self, db):
        db.upsert_trace(_make_trace(workflow_id="wf-1", session_id="s1", duration_ms=1000))
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2"))

        rows, total = db.get_trace_stats(group_by="workflow")

        assert total == 1
        assert rows[0]["workflow_id"] == "wf-1"
        assert rows[0]["total_traces"] == 1

    def test_group_by_respects_filters(self, db):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", user_id="user-1"))
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", user_id="user-2"))

        rows, _ = db.get_trace_stats(group_by="agent", user_id="user-2")

        assert rows[0]["total_traces"] == 1

    def test_group_by_respects_time_window(self, db):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", minutes_ago=120))
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", minutes_ago=5))

        start_time = datetime.now(timezone.utc) - timedelta(minutes=60)
        rows, _ = db.get_trace_stats(group_by="agent", start_time=start_time)

        assert rows[0]["total_traces"] == 1

    def test_group_by_endpoint(self, db):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1"))
        endpoint_trace = _make_trace(session_id=None, user_id=None, duration_ms=40)
        db.upsert_trace(endpoint_trace)
        other_endpoint = _make_trace(session_id=None, user_id=None, duration_ms=60)
        other_endpoint.name = "tools/list"
        db.upsert_trace(other_endpoint)

        rows, total = db.get_trace_stats(group_by="endpoint")

        assert total == 2
        by_name = {row["name"]: row for row in rows}
        # Only traces with no component ids at all are endpoint-level
        assert by_name["Agent.run"]["total_traces"] == 1
        assert by_name["Agent.run"]["avg_duration_ms"] == 40.0
        assert by_name["tools/list"]["total_traces"] == 1


# ----------------------------------------------------------------------
# Db layer: get_span_stats
# ----------------------------------------------------------------------


class TestSpanStats:
    def _seed(self, db):
        trace = _make_trace(agent_id="agent-1", session_id="s1")
        db.upsert_trace(trace)
        db.create_spans(
            [
                _make_span(trace.trace_id, name="slow_tool", duration_ms=900),
                _make_span(trace.trace_id, name="slow_tool", duration_ms=1100),
                _make_span(trace.trace_id, name="fast_tool", duration_ms=10),
                _make_span(trace.trace_id, name="fast_tool", duration_ms=20),
                _make_span(trace.trace_id, name="fast_tool", duration_ms=30, status_code="ERROR"),
                _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
            ]
        )
        return trace

    def test_aggregates_by_name(self, db):
        self._seed(db)

        rows, total = db.get_span_stats()

        assert total == 3
        by_name = {row["name"]: row for row in rows}
        assert by_name["slow_tool"]["total_calls"] == 2
        assert by_name["slow_tool"]["avg_duration_ms"] == 1000.0
        assert by_name["slow_tool"]["max_duration_ms"] == 1100
        assert by_name["slow_tool"]["span_type"] == "TOOL"
        assert by_name["fast_tool"]["error_count"] == 1
        assert by_name["Model.invoke"]["span_type"] == "LLM"
        assert isinstance(by_name["slow_tool"]["last_called_at"], datetime)

    def test_span_type_filter(self, db):
        self._seed(db)

        rows, total = db.get_span_stats(span_type="TOOL")

        assert total == 2
        assert {row["name"] for row in rows} == {"slow_tool", "fast_tool"}

    def test_name_filter(self, db):
        self._seed(db)

        rows, total = db.get_span_stats(name="slow_tool")

        assert total == 1
        assert rows[0]["total_calls"] == 2

    def test_sort_by_avg_duration(self, db):
        self._seed(db)

        rows, _ = db.get_span_stats(span_type="TOOL", sort_by="avg_duration_ms")

        assert rows[0]["name"] == "slow_tool"

    def test_component_filter_joins_traces(self, db):
        self._seed(db)
        other_trace = _make_trace(agent_id="agent-2", session_id="s2")
        db.upsert_trace(other_trace)
        db.create_span(_make_span(other_trace.trace_id, name="other_tool"))

        rows, total = db.get_span_stats(agent_id="agent-1")

        assert total == 3
        assert "other_tool" not in {row["name"] for row in rows}

    def test_time_window(self, db):
        trace = _make_trace(agent_id="agent-1", session_id="s1")
        db.upsert_trace(trace)
        db.create_span(_make_span(trace.trace_id, name="old_tool", minutes_ago=120))
        db.create_span(_make_span(trace.trace_id, name="new_tool", minutes_ago=5))

        start_time = datetime.now(timezone.utc) - timedelta(minutes=60)
        rows, total = db.get_span_stats(start_time=start_time)

        assert total == 1
        assert rows[0]["name"] == "new_tool"

    def test_paging_with_tied_name_groups_is_lossless(self, db):
        trace = _make_trace(agent_id="agent-1")
        db.upsert_trace(trace)
        for i in range(20):
            db.create_spans([_make_span(trace.trace_id, name="dup", span_type=f"KIND{i:02d}")])

        seen = []
        total = 0
        for page in range(1, 24):
            rows, total = db.get_span_stats(limit=3, page=page)
            if not rows:
                break
            seen.extend((row["name"], row["span_type"]) for row in rows)

        assert total == 20
        assert len(seen) == 20
        assert len(set(seen)) == 20

    def test_never_returns_attributes(self, db):
        self._seed(db)

        rows, _ = db.get_span_stats()

        for row in rows:
            assert "attributes" not in row


# ----------------------------------------------------------------------
# Toolkit: run activity
# ----------------------------------------------------------------------


class TestGetRunActivity:
    def test_reports_components_and_endpoint_level(self, db, toolkit):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", duration_ms=300))
        db.upsert_trace(_make_trace(team_id="team-1", session_id="s3"))
        db.upsert_trace(_make_trace(session_id=None, user_id=None))  # endpoint-level

        out = _loads(toolkit.get_run_activity(days=7))

        assert out["total_traces"] == 4
        assert [(r["agent_id"], r["total_traces"]) for r in out["agents"]] == [("agent-1", 2)]
        assert [(r["team_id"], r["total_traces"]) for r in out["teams"]] == [("team-1", 1)]
        assert out["workflows"] == []
        assert [(r["name"], r["total_traces"]) for r in out["endpoint_level"]] == [("Agent.run", 1)]
        assert any("endpoint_level" in note for note in out["notes"])

    def test_empty_platform(self, toolkit):
        out = _loads(toolkit.get_run_activity())

        assert out["total_traces"] == 0
        assert out["agents"] == []
        assert out["endpoint_level"] == []

    def test_truncation_note(self, db, toolkit, monkeypatch):
        import agno.tools.agentos as agentos_module

        monkeypatch.setattr(agentos_module, "_GROUP_LIMIT", 1)
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1"))
        db.upsert_trace(_make_trace(agent_id="agent-2", session_id="s2"))

        out = _loads(toolkit.get_run_activity())

        assert len(out["agents"]) == 1
        assert any("top 1 of 2 agents" in note for note in out["notes"])


# ----------------------------------------------------------------------
# Toolkit: tool activity
# ----------------------------------------------------------------------


class TestGetToolActivity:
    def test_reports_tools_and_model_calls(self, db, toolkit):
        trace = _make_trace(agent_id="agent-1", session_id="s1")
        db.upsert_trace(trace)
        db.create_spans(
            [
                _make_span(trace.trace_id, name="busy_tool", duration_ms=10),
                _make_span(trace.trace_id, name="busy_tool", duration_ms=20),
                _make_span(trace.trace_id, name="slow_tool", duration_ms=2000),
                _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
            ]
        )

        out = _loads(toolkit.get_tool_activity(days=7))

        assert out["tools_most_used"][0]["name"] == "busy_tool"
        assert out["tools_slowest"][0]["name"] == "slow_tool"
        assert [r["name"] for r in out["model_calls"]] == ["Model.invoke"]
        # SQLite has no percentile support, the payload must say so
        assert any("p95" in note for note in out["notes"])

    def test_truncation_note(self, db, toolkit):
        trace = _make_trace(agent_id="agent-1", session_id="s1")
        db.upsert_trace(trace)
        db.create_spans([_make_span(trace.trace_id, name=f"tool_{i:02d}") for i in range(16)])

        out = _loads(toolkit.get_tool_activity())

        assert len(out["tools_most_used"]) == 15
        assert any("top 15 of 16 tools" in note for note in out["notes"])


# ----------------------------------------------------------------------
# Toolkit: platform metrics
# ----------------------------------------------------------------------


class TestGetPlatformMetrics:
    def test_calculates_and_reports(self, db, toolkit):
        from agno.session.agent import AgentSession

        now = int(time.time())
        session = AgentSession(
            session_id=str(uuid.uuid4()),
            agent_id="agent-1",
            user_id="user-1",
            created_at=now,
            updated_at=now,
        )
        db.upsert_session(session)

        out = _loads(toolkit.get_platform_metrics(days=7))

        assert out["totals"]["agent_sessions"] == 1
        assert len(out["daily"]) == 1
        assert out["daily"][0]["distinct_users"] == 1

    def test_empty_platform_notes_absence(self, toolkit):
        out = _loads(toolkit.get_platform_metrics())

        assert out["daily"] == []
        assert any("no metrics" in note for note in out["notes"])


class TestLazyMetricsRefresh:
    def _seed_session(self, db, agent_id="agent-1", user_id="user-1"):
        from agno.session.agent import AgentSession

        now = int(time.time())
        db.upsert_session(
            AgentSession(
                session_id=str(uuid.uuid4()), agent_id=agent_id, user_id=user_id, created_at=now, updated_at=now
            )
        )

    def test_get_metrics_refreshes_lazily(self, db):
        self._seed_session(db)

        # No calculate_metrics call: get_metrics must refresh on its own
        rows, _ = db.get_metrics()

        assert len(rows) == 1
        assert rows[0]["agent_sessions_count"] == 1

    def test_refresh_is_throttled(self, db):
        self._seed_session(db)
        rows, _ = db.get_metrics()
        assert rows[0]["agent_sessions_count"] == 1

        # A second read within the throttle window must not recompute
        self._seed_session(db, user_id="user-2")
        rows, _ = db.get_metrics()
        assert rows[0]["agent_sessions_count"] == 1

        # Expiring the throttle picks the new session up
        db._metrics_refreshed_at = 0.0
        rows, _ = db.get_metrics()
        assert rows[0]["agent_sessions_count"] == 2

    def test_explicit_calculate_stamps_the_throttle(self, db):
        self._seed_session(db)

        db.calculate_metrics()

        assert db._metrics_refreshed_at > 0.0


# ----------------------------------------------------------------------
# Toolkit: eval history
# ----------------------------------------------------------------------


class TestGetEvalHistory:
    def test_normalizes_pass_fail_and_reasons(self, db, toolkit):
        db.create_eval_run(
            EvalRunRecord(
                run_id="eval-1",
                eval_type=EvalType.RELIABILITY,
                eval_data={"eval_status": "PASSED", "failed_tool_calls": []},
                agent_id="agent-1",
                name="tool check",
            )
        )
        db.create_eval_run(
            EvalRunRecord(
                run_id="eval-2",
                eval_type=EvalType.RELIABILITY,
                eval_data={"eval_status": "FAILED", "failed_tool_calls": ["web_search"], "missing_tool_calls": []},
                agent_id="agent-1",
                name="tool check",
            )
        )
        db.create_eval_run(
            EvalRunRecord(
                run_id="eval-3",
                eval_type=EvalType.AGENT_AS_JUDGE,
                eval_data={
                    "pass_rate": 0.0,
                    "avg_score": 4.0,
                    "results": [{"passed": False, "reason": "Answer missed the deadline constraint"}],
                },
                agent_id="agent-1",
                name="judge check",
            )
        )
        db.create_eval_run(
            EvalRunRecord(
                run_id="eval-4",
                eval_type=EvalType.ACCURACY,
                eval_data={"avg_score": 8.5},
                agent_id="agent-1",
                name="accuracy check",
            )
        )

        out = _loads(toolkit.get_eval_history())

        assert out["total"] == 4
        by_id = {run["id"]: run for run in out["eval_runs"]}
        assert by_id["eval-1"]["status"] == "PASS"
        assert "reason" not in by_id["eval-1"]
        assert by_id["eval-2"]["status"] == "FAIL"
        assert by_id["eval-2"]["reason"]["failed_tool_calls"] == ["web_search"]
        assert by_id["eval-3"]["status"] == "FAIL"
        assert "deadline" in by_id["eval-3"]["reason"]
        assert by_id["eval-4"]["status"] == "SCORED"
        assert by_id["eval-4"]["avg_score"] == 8.5

    def test_performance_eval_reports_run_time(self, db, toolkit):
        from agno.eval.performance import PerformanceEval, PerformanceResult

        # Seed through the writer's own shape so this breaks if it changes again
        perf = PerformanceEval(func=lambda: None)
        perf.result = PerformanceResult(run_times=[1.0, 3.0])
        db.create_eval_run(
            EvalRunRecord(
                run_id="eval-perf",
                eval_type=EvalType.PERFORMANCE,
                eval_data=perf._parse_eval_run_data(),
                agent_id="agent-1",
                name="perf check",
            )
        )

        out = _loads(toolkit.get_eval_history())

        run = out["eval_runs"][0]
        assert run["status"] == "MEASURED"
        assert run["avg_run_time"] == pytest.approx(2.0)

    def test_performance_eval_tolerates_flat_rows(self, db, toolkit):
        db.create_eval_run(
            EvalRunRecord(
                run_id="eval-perf-flat",
                eval_type=EvalType.PERFORMANCE,
                eval_data={"avg_run_time": 1.5},
                agent_id="agent-1",
            )
        )

        out = _loads(toolkit.get_eval_history())

        assert out["eval_runs"][0]["avg_run_time"] == 1.5

    def test_truncation_note(self, db, toolkit):
        for i in range(3):
            db.create_eval_run(
                EvalRunRecord(
                    run_id=f"eval-{i}",
                    eval_type=EvalType.ACCURACY,
                    eval_data={"avg_score": 5.0},
                    agent_id="agent-1",
                )
            )

        out = _loads(toolkit.get_eval_history(limit=2))

        assert out["count"] == 2
        assert out["total"] == 3
        assert any("most recent" in note for note in out["notes"])


# ----------------------------------------------------------------------
# Toolkit: schedules
# ----------------------------------------------------------------------


class TestSchedules:
    def _seed(self, db):
        schedule = Schedule(
            id="sched-1",
            name="daily-report",
            cron_expr="0 9 * * *",
            endpoint="/agents/reporter/runs",
        )
        db.create_schedule(schedule.to_dict())
        now = int(time.time())
        db.create_schedule_run(
            ScheduleRun(
                id="run-1",
                schedule_id="sched-1",
                status="failed",
                triggered_at=now - 120,
                error="endpoint timed out",
                created_at=now - 120,
            ).to_dict()
        )
        db.create_schedule_run(
            ScheduleRun(
                id="run-2",
                schedule_id="sched-1",
                status="success",
                triggered_at=now - 60,
                completed_at=now - 30,
                status_code=200,
                created_at=now - 60,
            ).to_dict()
        )

    def test_list_schedules_with_last_outcome(self, db, toolkit):
        self._seed(db)

        out = _loads(toolkit.list_schedules())

        assert out["total"] == 1
        schedule = out["schedules"][0]
        assert schedule["name"] == "daily-report"
        assert schedule["cron_expr"] == "0 9 * * *"
        assert schedule["last_run"]["status"] == "success"

    def test_schedule_history_page_summary(self, db, toolkit):
        self._seed(db)

        out = _loads(toolkit.get_schedule_history("sched-1"))

        assert out["page_summary"]["status_counts"] == {"success": 1, "failed": 1}
        assert out["page_summary"]["last_failure"]["error"] == "endpoint timed out"
        # Run input/output can hold conversation content and must not be exposed
        for run in out["runs"]:
            assert "input" not in run
            assert "output" not in run

    def test_page_summary_is_scoped_to_the_page_and_says_so(self, db, toolkit):
        schedule = Schedule(id="sched-1", name="hourly-digest", cron_expr="0 * * * *", endpoint="/agents/d/runs")
        db.create_schedule(schedule.to_dict())
        now = int(time.time())
        # The only failure is the oldest run, outside the default page below
        db.create_schedule_run(
            ScheduleRun(
                id="run-fail",
                schedule_id="sched-1",
                status="failed",
                triggered_at=now - 1000,
                error="boom",
                created_at=now - 1000,
            ).to_dict()
        )
        for i in range(9):
            db.create_schedule_run(
                ScheduleRun(
                    id=f"run-ok-{i}",
                    schedule_id="sched-1",
                    status="success",
                    triggered_at=now - 900 + i * 100,
                    completed_at=now - 890 + i * 100,
                    status_code=200,
                    created_at=now - 900 + i * 100,
                ).to_dict()
            )

        out = _loads(toolkit.get_schedule_history("sched-1", limit=3))

        assert "summary" not in out
        assert out["page_summary"]["status_counts"] == {"success": 3}
        assert out["page_summary"]["last_failure"] is None
        assert out["total"] == 10
        assert any("page_summary covers only these 3 runs" in note for note in out["notes"])

    def test_error_bodies_are_redacted_and_bounded(self, db, toolkit):
        marker = "SECRET_PAYLOAD_MARKER ssn=123-45-6789"
        schedule = Schedule(id="sched-1", name="daily-report", cron_expr="0 9 * * *", endpoint="/agents/r/runs")
        db.create_schedule(schedule.to_dict())
        now = int(time.time())
        # An upstream 422 echoes the run input back in the response body
        body = json.dumps({"detail": [{"loc": ["body", "user_id"], "input": marker}]}) + "x" * 5000
        db.create_schedule_run(
            ScheduleRun(
                id="run-1",
                schedule_id="sched-1",
                status="failed",
                triggered_at=now - 60,
                status_code=422,
                error=body,
                created_at=now - 60,
            ).to_dict()
        )

        history = toolkit.get_schedule_history("sched-1")
        schedules = toolkit.list_schedules()

        assert marker not in history
        assert marker not in schedules
        out = _loads(history)
        assert out["runs"][0]["error"] == "HTTP 422"
        assert out["page_summary"]["last_failure"]["error"] == "HTTP 422"
        assert _loads(schedules)["schedules"][0]["last_run"]["error"] == "HTTP 422"
        for run in out["runs"]:
            assert run["error"] is None or len(run["error"]) <= 200

    def test_framework_errors_keep_a_capped_first_line(self, db, toolkit):
        schedule = Schedule(id="sched-1", name="daily-report", cron_expr="0 9 * * *", endpoint="/agents/r/runs")
        db.create_schedule(schedule.to_dict())
        now = int(time.time())
        db.create_schedule_run(
            ScheduleRun(
                id="run-1",
                schedule_id="sched-1",
                status="failed",
                triggered_at=now - 120,
                error="Polling timed out after 300s for run abc\n" + "Traceback (most recent call last):\n" * 50,
                created_at=now - 120,
            ).to_dict()
        )
        db.create_schedule_run(
            ScheduleRun(
                id="run-2",
                schedule_id="sched-1",
                status="failed",
                triggered_at=now - 60,
                error="y" * 5000,
                created_at=now - 60,
            ).to_dict()
        )

        out = _loads(toolkit.get_schedule_history("sched-1"))

        by_error = [run["error"] for run in out["runs"]]
        assert "Polling timed out after 300s for run abc" in by_error
        assert "y" * 200 in by_error
        for error in by_error:
            assert len(error) <= 200

    def test_unsupported_backend_returns_clear_error(self, db, toolkit, monkeypatch):
        def raise_not_implemented(*args: Any, **kwargs: Any):
            raise NotImplementedError

        monkeypatch.setattr(db, "get_schedules", raise_not_implemented)

        out = _loads(toolkit.list_schedules())

        assert "not supported" in out["error"]


# ----------------------------------------------------------------------
# Toolkit: components
# ----------------------------------------------------------------------


class TestComponents:
    def test_lists_components(self, db, toolkit):
        from agno.db.base import ComponentType

        db.upsert_component(
            component_id="news-scout",
            component_type=ComponentType.AGENT,
            name="News Scout",
            description="Summarizes tech news",
        )

        out = _loads(toolkit.list_platform_components())

        assert out["total"] == 1
        component = out["components"][0]
        assert component["component_id"] == "news-scout"
        assert component["component_type"] == "agent"
        assert component["name"] == "News Scout"
        assert "current_version" in component


# ----------------------------------------------------------------------
# Toolkit: approvals
# ----------------------------------------------------------------------


class TestPendingApprovals:
    def test_lists_only_pending_and_hides_tool_args(self, db, toolkit):
        db.create_approval(
            {
                "id": "approval-1",
                "run_id": "run-1",
                "session_id": "s1",
                "status": "pending",
                "source_type": "agent",
                "pause_type": "confirmation",
                "tool_name": "send_email",
                "tool_args": {"to": "someone@example.com", "body": "private content"},
                "agent_id": "agent-1",
                "user_id": "user-1",
            }
        )
        db.create_approval(
            {
                "id": "approval-2",
                "run_id": "run-2",
                "session_id": "s2",
                "status": "approved",
                "source_type": "agent",
                "pause_type": "confirmation",
            }
        )

        out = _loads(toolkit.list_pending_approvals())

        assert out["total"] == 1
        approval = out["approvals"][0]
        assert approval["id"] == "approval-1"
        assert approval["tool_name"] == "send_email"
        assert "tool_args" not in approval
        assert "context" not in approval


# ----------------------------------------------------------------------
# Toolkit: error paths
# ----------------------------------------------------------------------


class TestErrorPaths:
    def test_db_failure_returns_generic_error_without_leaking_detail(self, db, toolkit, monkeypatch):
        # Raw exception text can carry SQL fragments, table and column names. These
        # tools read the db with no endpoint scopes, so the detail must not reach
        # whoever talks to the agent -- it is logged instead.
        def fail(*args: Any, **kwargs: Any):
            raise RuntimeError("db exploded: SELECT secret_col FROM secret_table")

        monkeypatch.setattr(db, "get_eval_runs", fail)

        out = _loads(toolkit.get_eval_history())

        assert "error" in out
        assert "secret_table" not in out["error"]
        assert "db exploded" not in out["error"]
        assert "Failed to get eval history" in out["error"]


# ----------------------------------------------------------------------
# Async variants
# ----------------------------------------------------------------------


class TestAsyncVariants:
    @pytest.mark.asyncio
    async def test_native_async_path(self, async_db):
        await async_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
        toolkit = AgentOSTools(db=async_db)

        out = _loads(await toolkit.aget_run_activity(days=7))

        assert out["total_traces"] == 1
        assert out["agents"][0]["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_async_trace_stats_aggregates(self, async_db):
        await async_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
        await async_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", duration_ms=300, status="ERROR"))
        await async_db.upsert_trace(_make_trace(session_id=None, user_id=None))

        rows, total = await async_db.get_trace_stats(group_by="agent")

        assert total == 1
        top = rows[0]
        assert top["agent_id"] == "agent-1"
        assert top["total_traces"] == 2
        assert top["total_sessions"] == 2
        assert top["avg_duration_ms"] == 200.0
        assert top["max_duration_ms"] == 300
        assert top["error_traces"] == 1
        assert top["p95_duration_ms"] is None

        endpoint_rows, endpoint_total = await async_db.get_trace_stats(group_by="endpoint")
        assert endpoint_total == 1
        assert endpoint_rows[0]["name"] == "Agent.run"

    @pytest.mark.asyncio
    async def test_async_span_stats_aggregates(self, async_db):
        trace = _make_trace(agent_id="agent-1", session_id="s1")
        await async_db.upsert_trace(trace)
        await async_db.create_spans(
            [
                _make_span(trace.trace_id, name="my_tool", duration_ms=100),
                _make_span(trace.trace_id, name="my_tool", duration_ms=300, status_code="ERROR"),
            ]
        )

        rows, total = await async_db.get_span_stats()

        assert total == 1
        assert rows[0]["name"] == "my_tool"
        assert rows[0]["total_calls"] == 2
        assert rows[0]["avg_duration_ms"] == 200.0
        assert rows[0]["max_duration_ms"] == 300
        assert rows[0]["error_count"] == 1
        assert rows[0]["span_type"] == "TOOL"

    @pytest.mark.asyncio
    async def test_async_span_stats_path(self, async_db):
        trace = _make_trace(agent_id="agent-1", session_id="s1")
        await async_db.upsert_trace(trace)
        await async_db.create_span(_make_span(trace.trace_id, name="my_tool", duration_ms=100))
        toolkit = AgentOSTools(db=async_db)

        out = _loads(await toolkit.aget_tool_activity(days=7))

        assert out["tools_most_used"][0]["name"] == "my_tool"

    def test_sync_tool_with_async_db_returns_clear_error(self, async_db):
        toolkit = AgentOSTools(db=async_db)

        out = _loads(toolkit.get_run_activity())

        assert "async" in out["error"]

    @pytest.mark.asyncio
    async def test_async_wrapper_with_sync_db(self, db):
        db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1"))
        toolkit = AgentOSTools(db=db)

        out = _loads(await toolkit.aget_run_activity())

        assert out["agents"][0]["agent_id"] == "agent-1"
