"""Unit tests for the OS metrics rollup helpers.

``calculate_date_os_metrics`` turns one day's stored sessions and runs into one row of agno_os_metrics per owner
and agent, team or workflow. The helpers around it build the total row of a day or month for
agno_os_metrics_totals, decide which rebuilt rows to write, and read a percentile back out of the bucket counts.
"""

import statistics
from datetime import date, datetime, timedelta, timezone

import pytest

from agno.db.postgres.utils import build_os_metrics_run, build_os_metrics_totals
from agno.db.utils import (
    _OS_METRICS_BUCKET_BOUNDS_MS,
    OS_METRICS_BUCKETS_VERSION,
    OS_METRICS_COMPONENT_TYPES,
    OS_METRICS_FIELDS,
    OS_METRICS_KEY_COLUMNS,
    OS_METRICS_TOKEN_FIELDS,
    add_month_os_metrics,
    add_os_metrics_totals,
    build_os_metrics_totals_row,
    calculate_date_os_metrics,
    calculate_month_os_metrics,
    empty_os_metrics_totals,
    get_months_to_calculate_os_metrics_for,
    merge_os_metrics_totals,
    os_metrics_day_completed,
    os_metrics_day_ranges,
    os_metrics_days_to_read,
    os_metrics_full_months,
    os_metrics_month_end,
    os_metrics_nested_run_ids,
    os_metrics_percentile,
    os_metrics_rows_to_write,
    os_metrics_totals_row_to_write,
    os_metrics_versions,
    resolve_os_metrics_fields,
)
from agno.run.base import RunStatus

TARGET_DATE = date(2026, 1, 1)

COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value
REGENERATED = RunStatus.regenerated.value

# The keys that differ between two builds of the same day.
EPHEMERAL = {"created_at", "updated_at"}


def _session(user_id="alice", session_type="agent", component_id="agent-1"):
    """Build a stored session the way the sessions query returns it."""
    return {"session_type": session_type, "user_id": user_id, f"{session_type}_id": component_id}


def _model_call(
    model="gpt-5",
    provider="OpenAI",
    tokens=None,
    call_durations=(),
    details=True,
    agent_id=None,
    team_id=None,
    step_executor_runs=None,
    member_responses=None,
    run_id=None,
    history_durations=(),
):
    """Build the run_data of one model call: the run's own, a workflow step's or a team member's."""
    metrics = dict(tokens or {})
    if details:
        metrics["details"] = {"gpt-5": {}}
    call = {
        "model": model,
        "model_provider": provider,
        "metrics": metrics,
        "messages": [
            *({"role": "assistant", "metrics": {"duration": seconds}} for seconds in call_durations),
            *(
                {"role": "assistant", "from_history": True, "metrics": {"duration": seconds}}
                for seconds in history_durations
            ),
        ],
    }
    if run_id:
        call["run_id"] = run_id
    if agent_id:
        call["agent_id"] = agent_id
    if team_id:
        call["team_id"] = team_id
    if step_executor_runs is not None:
        call["step_executor_runs"] = step_executor_runs
    if member_responses is not None:
        call["member_responses"] = member_responses
    return call


def _run(
    run_id="run-1",
    run_type="agent",
    component_id="agent-1",
    user_id="alice",
    status=COMPLETED,
    parent_run_id=None,
    duration=None,
    time_to_first_token=None,
    **call_kwargs,
):
    """Build a stored run the way the runs query returns it, with its own model call."""
    run_data = _model_call(**call_kwargs)
    if duration is not None:
        run_data["metrics"]["duration"] = duration
    if time_to_first_token is not None:
        run_data["metrics"]["time_to_first_token"] = time_to_first_token
    return {
        "run_id": run_id,
        "run_type": run_type,
        f"{run_type}_id": component_id,
        "user_id": user_id,
        "parent_run_id": parent_run_id,
        "status": status,
        "run_data": run_data,
    }


def _rows(sessions=(), runs=(), stored_run_ids=frozenset()):
    """Build the day's rows keyed by (user_id, component_type, component_id)."""
    return {
        (row["user_id"], row["component_type"], row["component_id"]): row
        for row in calculate_date_os_metrics(TARGET_DATE, list(sessions), list(runs), set(stored_run_ids))
    }


def _only_row(sessions=(), runs=()):
    rows = list(_rows(sessions, runs).values())
    assert len(rows) == 1
    return rows[0]


def _stable(row):
    return {key: value for key, value in row.items() if key not in EPHEMERAL}


def _day_rows(runs, sessions=(), day=TARGET_DATE):
    return calculate_date_os_metrics(day, list(sessions), list(runs), set())


class _Row:
    """A SQLAlchemy result row: attributes plus a _mapping."""

    def __init__(self, **values):
        self._mapping = values
        for name, value in values.items():
            setattr(self, name, value)


# ---------------------------------------------------------------------------
# Rows: one per owner and component
# ---------------------------------------------------------------------------


def test_one_row_per_user_and_component():
    """Sessions and runs of one owner for one component share a row; any other pair gets its own."""
    rows = _rows(
        sessions=[_session("alice"), _session("alice"), _session("bob"), _session("alice", "team", "team-1")],
        runs=[_run("run-1", user_id="alice"), _run("run-2", user_id="alice")],
    )

    assert set(rows) == {("alice", "agent", "agent-1"), ("bob", "agent", "agent-1"), ("alice", "team", "team-1")}
    assert rows[("alice", "agent", "agent-1")]["sessions_count"] == 2
    assert rows[("alice", "agent", "agent-1")]["runs_count"] == 2
    assert rows[("bob", "agent", "agent-1")]["runs_count"] == 0


def test_session_without_user_lands_under_empty_string():
    """A session with no user_id is counted under the "" owner."""
    row = _only_row(sessions=[_session(None)])

    assert row["user_id"] == ""
    assert row["sessions_count"] == 1


def test_only_the_id_matching_the_component_type_is_used():
    """A team session that also names an agent is counted under the team alone."""
    session = {**_session("alice", "team", "team-1"), "agent_id": "agent-1"}
    row = _only_row(sessions=[session])

    assert (row["component_type"], row["component_id"]) == ("team", "team-1")


def test_component_types_are_the_session_types():
    """A row is counted under an agent, a team or a workflow; a session of any other type is skipped."""
    assert OS_METRICS_COMPONENT_TYPES == ("agent", "team", "workflow")
    assert _rows(sessions=[{"session_type": "agents", "user_id": "alice"}, _session("alice")]) == {
        ("alice", "agent", "agent-1"): _only_row(sessions=[_session("alice")])
    }


def test_row_shape():
    """A row carries the columns the upsert expects, keyed by aggregation period, date, owner, component and parent."""
    row = _only_row(runs=[_run()])

    assert tuple(row[column] for column in OS_METRICS_KEY_COLUMNS) == (
        "daily",
        TARGET_DATE,
        "alice",
        "agent",
        "agent-1",
        "",
    )
    assert row["additional_metrics"] == {}
    assert row["buckets_version"] == OS_METRICS_BUCKETS_VERSION
    assert row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1}]
    assert "id" not in row
    assert "completed" not in row
    assert set(OS_METRICS_FIELDS) <= set(row)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_every_run_counted_once_in_its_own_row():
    """Each run adds one to runs_count of its owner's row for its component and to no other."""
    rows = _rows(
        runs=[
            _run("run-1", user_id="alice"),
            _run("run-2", user_id="alice", run_type="team", component_id="team-1"),
            _run("run-3", user_id="bob"),
        ]
    )

    assert {key: row["runs_count"] for key, row in rows.items()} == {
        ("alice", "agent", "agent-1"): 1,
        ("alice", "team", "team-1"): 1,
        ("bob", "agent", "agent-1"): 1,
    }


def test_team_member_run_counts_under_the_member_agent():
    """A member's run is stored as its own agent run and counted under that agent, not the team."""
    rows = _rows(
        runs=[
            _run("team-run", run_type="team", component_id="team-1"),
            _run("member-run", component_id="member-1", parent_run_id="team-run"),
        ]
    )

    assert rows[("alice", "team", "team-1")]["runs_count"] == 1
    assert rows[("alice", "agent", "member-1")]["runs_count"] == 1
    assert rows[("alice", "agent", "member-1")]["parent_component_id"] == "team-1"


def test_member_run_and_the_same_agent_alone_are_two_rows():
    """The same agent alone and as a team's member is two rows told apart by parent_component_id; the total holds."""
    runs = [
        _run("team-run", run_type="team", component_id="team-1", tokens={"total_tokens": 300}),
        _run("member-run", component_id="member-1", parent_run_id="team-run", tokens={"total_tokens": 500}),
        _run("alone-run", component_id="member-1", tokens={"total_tokens": 120}),
    ]
    rows = {(row["component_id"], row["parent_component_id"]): row["total_tokens"] for row in _day_rows(runs)}

    assert rows == {("team-1", ""): 300, ("member-1", "team-1"): 500, ("member-1", ""): 120}
    total = build_os_metrics_totals_row(_day_rows(runs), "daily", TARGET_DATE, True)
    assert (total["total_tokens"], total["runs_count"]) == (920, 3)


def test_regenerated_run_is_not_a_run_but_its_calls_count():
    """A regenerated run is neither a run nor a status of the day, but the tokens and calls it spent are."""
    row = _only_row(
        runs=[
            _run("run-1"),
            _run("run-2", status=REGENERATED, tokens={"input_tokens": 100}, duration=1.0, call_durations=(0.5,)),
        ]
    )

    assert row["runs_count"] == 1
    assert row["status_metrics"] == {COMPLETED: 1}
    assert row["input_tokens"] == 100
    assert row["model_calls_count"] == 1
    assert row["duration_runs_count"] == 0
    assert row["model_metrics"][0]["count"] == 2


def test_nested_team_members_are_walked_from_member_responses():
    """A member of a team inside a team is stored nowhere else, so its calls come from the inner team's members."""
    inner_member = _model_call(tokens={"input_tokens": 1}, agent_id="inner-a", run_id="inner-a-run")
    runs = [
        _run("outer-run", run_type="team", component_id="outer-team", tokens={"input_tokens": 100}),
        _run(
            "inner-run",
            run_type="team",
            component_id="inner-team",
            parent_run_id="outer-run",
            tokens={"input_tokens": 10},
            member_responses=[inner_member],
        ),
    ]
    rows = _rows(runs=runs)

    assert rows[("alice", "team", "inner-team")]["input_tokens"] == 11
    assert rows[("alice", "team", "inner-team")]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}
    ]


def test_nested_run_stored_on_its_own_is_not_walked_again():
    """A team member stored as a run of its own is counted there, not again from the team's member_responses."""
    member = _model_call(tokens={"input_tokens": 1}, agent_id="member-1", run_id="member-run")
    rows = _rows(
        runs=[
            _run("team-run", run_type="team", component_id="team-1", member_responses=[member]),
            _run("member-run", component_id="member-1", parent_run_id="team-run", tokens={"input_tokens": 1}),
        ]
    )

    assert rows[("alice", "team", "team-1")]["input_tokens"] == 0
    assert rows[("alice", "agent", "member-1")]["input_tokens"] == 1


def test_member_stored_on_another_day_is_not_walked():
    """A member that ended after midnight is a row of the next day, so the parent's day skips it."""
    member = _model_call(tokens={"input_tokens": 100}, agent_id="member-1", run_id="member-run")
    parent_day = _rows(
        runs=[
            _run(
                "team-run",
                run_type="team",
                component_id="team-1",
                tokens={"input_tokens": 50},
                member_responses=[member],
            )
        ],
        stored_run_ids={"member-run"},
    )

    assert parent_day[("alice", "team", "team-1")]["input_tokens"] == 50
    assert ("alice", "agent", "member-1") not in parent_day


def test_nested_run_ids_are_collected_at_every_depth():
    inner = _model_call(agent_id="inner-a", run_id="inner-run")
    step_team = _model_call(team_id="team-1", run_id="team-run", member_responses=[inner])
    runs = [_run(run_type="workflow", component_id="wf-1", model=None, step_executor_runs=[step_team]), _run("plain")]

    assert os_metrics_nested_run_ids(runs) == {"team-run", "inner-run"}


def test_nested_run_reachable_twice_is_walked_once():
    """A workflow team step lists its members flat beside the team run that also holds them."""
    member = _model_call(tokens={"input_tokens": 1}, agent_id="member-1", run_id="member-run")
    step_team = _model_call(tokens={"input_tokens": 10}, team_id="team-1", run_id="team-run", member_responses=[member])
    row = _only_row(
        runs=[_run(run_type="workflow", component_id="wf-1", model=None, step_executor_runs=[step_team, member])]
    )

    assert row["input_tokens"] == 11


def test_history_messages_are_not_model_calls():
    """An assistant message carried over from an earlier run keeps that run's duration and is not counted."""
    row = _only_row(runs=[_run(call_durations=(0.2, 0.3), history_durations=(0.9,))])

    assert row["model_calls_count"] == 2
    assert row["total_model_call_ms"] == 500


def test_status_metrics_keyed_by_status():
    """status_metrics counts runs by their stored status."""
    row = _only_row(runs=[_run("run-1"), _run("run-2"), _run("run-3", status=ERROR)])

    assert row["status_metrics"] == {COMPLETED: 2, ERROR: 1}


def test_error_run_adds_no_duration():
    """Only a completed run's duration and time to first token are counted."""
    row = _only_row(runs=[_run("run-1", status=ERROR, duration=2.0, time_to_first_token=0.5)])

    assert row["runs_count"] == 1
    assert (row["duration_runs_count"], row["time_to_first_token_runs_count"]) == (0, 0)
    assert (row["max_duration_ms"], row["max_time_to_first_token_ms"]) == (None, None)
    assert row["duration_buckets"] == row["time_to_first_token_buckets"] == {}


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_tokens_summed_from_every_model_call():
    """Tokens add up across the run's own call, each workflow step's run and the step members' runs."""
    step_member = _model_call(tokens={"input_tokens": 1}, agent_id="member-1")
    step_team = _model_call(tokens={"input_tokens": 10}, team_id="team-1", member_responses=[step_member])
    step_agent = _model_call(tokens={"input_tokens": 100}, agent_id="agent-1")
    workflow_run = _run(
        run_type="workflow",
        component_id="wf-1",
        model=None,
        step_executor_runs=[step_agent, step_team],
    )
    row = _only_row(
        runs=[workflow_run, _run("run-2", run_type="workflow", component_id="wf-1", tokens={"input_tokens": 1000})]
    )

    assert row["input_tokens"] == 1111


def test_rarer_tokens_are_kept_apart_and_zeros_are_not_stored():
    """Input, output and total tokens have columns of their own; a rarer count of zero is left out."""
    row = _only_row(
        runs=[_run(tokens={"input_tokens": 5, "output_tokens": 0, "reasoning_tokens": 0, "cache_read_tokens": 3})]
    )

    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (5, 0, 0)
    assert row["additional_token_metrics"] == {"cache_read_tokens": 3}
    assert OS_METRICS_TOKEN_FIELDS[:3] == ("input_tokens", "output_tokens", "total_tokens")


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------


def test_timings_count_total_max():
    """Each timing keeps a count, a total and a maximum in milliseconds."""
    row = _only_row(
        runs=[
            _run("run-1", duration=1.0, time_to_first_token=0.2, call_durations=(0.3, 0.7)),
            _run("run-2", duration=3.0, time_to_first_token=0.1, call_durations=(0.5,)),
        ]
    )

    assert (row["duration_runs_count"], row["total_duration_ms"], row["max_duration_ms"]) == (2, 4000, 3000)
    assert (
        row["time_to_first_token_runs_count"],
        row["total_time_to_first_token_ms"],
        row["max_time_to_first_token_ms"],
    ) == (2, 300, 200)
    assert (row["model_calls_count"], row["total_model_call_ms"], row["max_model_call_ms"]) == (3, 1500, 700)


@pytest.mark.parametrize(
    ("milliseconds", "bucket"),
    [
        (0, "le_10"),
        (10, "le_10"),
        (11, "le_12"),
        (100, "le_100"),
        (1234, "le_1500"),
        (8_000_000, "le_8000000"),
        (8_000_001, "gt_8000000"),
    ],
)
def test_timing_counted_in_the_right_bucket(milliseconds, bucket):
    """A timing is counted under the smallest bound it does not exceed, or gt_ past the last one."""
    row = _only_row(runs=[_run(duration=milliseconds / 1000)])

    assert row["duration_buckets"] == {bucket: 1}


def test_bucket_bounds():
    """The bounds run 10, 12, 15, ... 80 through six decades, ending at 8,000,000 ms."""
    assert _OS_METRICS_BUCKET_BOUNDS_MS[:10] == (10, 12, 15, 20, 25, 30, 40, 50, 60, 80)
    assert _OS_METRICS_BUCKET_BOUNDS_MS[-1] == 8_000_000
    assert list(_OS_METRICS_BUCKET_BOUNDS_MS) == sorted(_OS_METRICS_BUCKET_BOUNDS_MS)


def test_every_timing_gets_its_own_buckets():
    """Duration, time to first token and model calls are each bucketed apart."""
    row = _only_row(runs=[_run(duration=0.01, time_to_first_token=0.02, call_durations=(0.03, 0.03))])

    assert row["duration_buckets"] == {"le_10": 1}
    assert row["time_to_first_token_buckets"] == {"le_20": 1}
    assert row["model_call_buckets"] == {"le_30": 2}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_model_entry_counts_the_runs_it_served():
    """A model entry names its model and provider, and counts the runs it served."""
    row = _only_row(runs=[_run("run-1", call_durations=(0.3, 0.7)), _run("run-2", call_durations=(0.5,))])

    assert row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}]


def test_workflow_step_models_count_on_the_workflow_row():
    """A workflow step's model call is counted on the workflow's row, one entry per model."""
    row = _only_row(
        runs=[
            _run(
                run_type="workflow",
                component_id="wf-1",
                model=None,
                step_executor_runs=[_model_call(agent_id="step-agent"), _model_call(model="gpt-5-mini")],
            )
        ]
    )

    assert row["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1},
        {"model_id": "gpt-5-mini", "model_provider": "OpenAI", "count": 1},
    ]


def test_model_call_without_details_is_not_a_model_entry():
    """A model that failed before answering reports no details and is not counted as serving the run."""
    row = _only_row(runs=[_run(details=False, tokens={"input_tokens": 3})])

    assert row["model_metrics"] == []
    assert row["input_tokens"] == 3


def test_model_metrics_sorted_deterministically():
    """model_metrics is sorted by model and provider whatever order the runs arrived in."""
    runs = [
        _run("run-1", model="gpt-5", provider="OpenAI"),
        _run("run-2", model="claude", provider="Anthropic"),
        _run("run-3", model="claude", provider="Anthropic", component_id="agent-0"),
    ]
    forward = _rows(runs=runs)
    backward = _rows(runs=list(reversed(runs)))

    ids = [(m["model_id"], m["model_provider"]) for m in forward[("alice", "agent", "agent-1")]["model_metrics"]]
    assert ids == [("claude", "Anthropic"), ("gpt-5", "OpenAI")]
    for key, row in forward.items():
        assert row["model_metrics"] == backward[key]["model_metrics"]


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------


def test_rebuild_yields_identical_rows():
    """Two builds of the same inputs differ only in their timestamps."""
    runs = [_run("run-1", duration=1.0, call_durations=(0.2,)), _run("run-2", status=ERROR)]
    first = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())
    second = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())

    assert [_stable(row) for row in first] == [_stable(row) for row in second]


def test_unchanged_rebuild_writes_nothing():
    """A rebuild equal to the stored rows returns no rows to write and no stale keys."""
    runs = [_run("run-1", duration=1.0, call_durations=(0.2,))]
    stored = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())
    rebuilt = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())

    assert os_metrics_rows_to_write(rebuilt, stored) == ([], [])


def test_changed_number_is_written():
    """A row whose numbers moved is returned to be written."""
    stored = _day_rows([_run("run-1")])
    rebuilt = _day_rows([_run("run-1"), _run("run-2")])

    changed, stale = os_metrics_rows_to_write(rebuilt, stored)

    assert [row["runs_count"] for row in changed] == [2]
    assert stale == []


def test_new_row_is_written():
    """A row the stored set does not have is returned to be written."""
    rebuilt = _day_rows([_run("run-1")])

    changed, stale = os_metrics_rows_to_write(rebuilt, [])

    assert changed == rebuilt
    assert stale == []


def test_stored_row_missing_from_rebuild_is_stale():
    """A stored row the rebuild no longer produces is returned by its owner, component and parent for deletion."""
    stored = _day_rows([_run("run-1", user_id="alice"), _run("run-2", user_id="bob")])
    rebuilt = _day_rows([_run("run-1", user_id="alice")])

    changed, stale = os_metrics_rows_to_write(rebuilt, stored)

    assert changed == []
    assert stale == [("bob", "agent", "agent-1", "")]


def test_only_read_rows_can_be_stale():
    """A row that was not read is never returned as stale, so a row written since is kept."""
    rebuilt = _day_rows([_run("run-1", user_id="alice")])
    read = _day_rows([_run("run-1", user_id="alice")])

    assert os_metrics_rows_to_write(rebuilt, read) == ([], [])


def test_changed_row_is_written_alone():
    """Only Alice's row moved, so Bob's row is left alone."""
    stored = _day_rows([_run("run-1", user_id="alice"), _run("run-2", user_id="bob")])
    rebuilt = _day_rows([_run("run-1", user_id="alice"), _run("run-2", user_id="bob"), _run("run-3", user_id="alice")])

    changed, stale = os_metrics_rows_to_write(rebuilt, stored)

    assert [row["user_id"] for row in changed] == ["alice"]
    assert stale == []


def test_rows_to_write_come_in_key_order():
    """Rows are written in key order, so no two writers lock rows in opposite orders."""
    rebuilt = _day_rows([_run("run-1", user_id="bob"), _run("run-2", user_id="alice")])

    changed, _ = os_metrics_rows_to_write(list(reversed(rebuilt)), [])

    assert [row["user_id"] for row in changed] == ["alice", "bob"]


# ---------------------------------------------------------------------------
# Total rows
# ---------------------------------------------------------------------------


def test_total_row_totals_every_owner():
    """Alice's two rows and Bob's one are totalled into one row of the day, with no owner and no component."""
    rows = _day_rows(
        sessions=[_session("alice"), _session("alice", "team", "team-1"), _session("bob")],
        runs=[
            _run("run-1", user_id="alice", tokens={"total_tokens": 10}, duration=1.0),
            _run("run-2", "team", "team-1", user_id="alice", tokens={"total_tokens": 20}, duration=3.0),
            _run("run-3", user_id="bob", status=ERROR, details=False),
        ],
    )

    day = build_os_metrics_totals_row(rows, "daily", TARGET_DATE, completed=True)

    assert (day["aggregation_period"], day["date"], day["completed"]) == ("daily", TARGET_DATE, True)
    assert "user_id" not in day
    assert "component_type" not in day
    assert day["sessions_count"] == 3
    assert day["runs_count"] == 3
    assert day["status_metrics"] == {COMPLETED: 2, ERROR: 1}
    assert day["total_tokens"] == 30
    assert (day["duration_runs_count"], day["total_duration_ms"], day["max_duration_ms"]) == (2, 4000, 3000)
    assert day["duration_buckets"] == {"le_1000": 1, "le_3000": 1}
    assert day["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}]
    assert day["buckets_version"] == OS_METRICS_BUCKETS_VERSION


def test_day_without_rows_gets_a_total_row_of_zeros():
    """A day without traffic has no rows but still a total row, so it is never rebuilt again once completed."""
    assert calculate_date_os_metrics(TARGET_DATE, [], [], set()) == []

    day = build_os_metrics_totals_row([], "daily", TARGET_DATE, completed=True)

    assert {field: day[field] for field in OS_METRICS_FIELDS} == empty_os_metrics_totals()
    assert day["runs_count"] == 0
    assert day["max_duration_ms"] is None
    assert day["completed"] is True


def test_total_row_of_an_unknown_aggregation_period_is_refused():
    with pytest.raises(ValueError, match="week"):
        build_os_metrics_totals_row([], "week", TARGET_DATE, completed=True)


def test_today_and_yesterday_are_still_open():
    """A run of yesterday can still be written today, so yesterday is completed a day later."""
    today = datetime.now(timezone.utc).date()

    assert os_metrics_day_completed(today) is False
    assert os_metrics_day_completed(today - timedelta(days=1)) is False
    assert os_metrics_day_completed(today - timedelta(days=2)) is True


def test_total_row_is_written_when_new_or_its_rows_changed():
    """A new total row, or one whose day had a row written or deleted, is written so its version moves."""
    rows = _day_rows([_run("run-1")])
    total = build_os_metrics_totals_row(rows, "daily", TARGET_DATE, completed=False)
    stored = {**total, "version": 4, "created_at": 1, "updated_at": 1}

    assert os_metrics_totals_row_to_write(total, None, rows_changed=False) is total
    assert os_metrics_totals_row_to_write(total, stored, rows_changed=True) is total
    # The stamps and the version are not compared.
    assert os_metrics_totals_row_to_write(total, stored, rows_changed=False) is None


def test_total_row_is_written_when_its_day_completes():
    """The same numbers marked completed are written, so a later refresh starts after the day."""
    total = build_os_metrics_totals_row(_day_rows([_run("run-1")]), "daily", TARGET_DATE, completed=True)
    stored = {**total, "completed": False, "version": 1}

    assert os_metrics_totals_row_to_write(total, stored, rows_changed=False) is total


# ---------------------------------------------------------------------------
# Month rows
# ---------------------------------------------------------------------------


def test_month_rows_total_the_days_of_the_month():
    """A month of completed days gets a row per owner and component dated its first day, and a total row of them."""
    stored_rows = [
        *_day_rows([_run("run-1", user_id="alice", duration=1.0)], day=date(2026, 1, 1)),
        *_day_rows(
            [
                _run("run-2", user_id="alice", duration=5.0),
                _run("run-3", user_id="bob"),
                _run("run-4", "team", "team-1", user_id="alice"),
            ],
            day=date(2026, 1, 15),
        ),
    ]

    per_owner = {}
    add_month_os_metrics(per_owner, stored_rows[:1])
    add_month_os_metrics(per_owner, stored_rows[1:])
    month_rows = calculate_month_os_metrics(date(2026, 1, 1), per_owner)

    assert [
        (row["aggregation_period"], row["user_id"], row["component_type"], row["component_id"]) for row in month_rows
    ] == [
        ("monthly", "alice", "agent", "agent-1"),
        ("monthly", "alice", "team", "team-1"),
        ("monthly", "bob", "agent", "agent-1"),
    ]
    alice_agent, alice_team, bob_agent = month_rows
    assert (alice_agent["runs_count"], alice_team["runs_count"], bob_agent["runs_count"]) == (2, 1, 1)
    assert alice_agent["total_duration_ms"] == 6000
    for row in month_rows:
        assert row["date"] == date(2026, 1, 1)

    month = build_os_metrics_totals_row(month_rows, "monthly", date(2026, 1, 1), completed=True)
    assert month["runs_count"] == 4
    assert month["max_duration_ms"] == 5000
    assert month["duration_buckets"] == {"le_1000": 1, "le_5000": 1}


def test_month_without_rows_gets_no_month_rows():
    assert calculate_month_os_metrics(date(2026, 1, 1), {}) == []


def test_month_is_calculated_once_its_last_day_is_completed():
    """A month is completed once the latest completed day is at or after its last day."""
    day_starts = [date(2026, 1, 3), date(2026, 1, 31), date(2026, 2, 1), date(2026, 2, 27)]

    assert get_months_to_calculate_os_metrics_for(day_starts, [], date(2026, 1, 30)) == []
    assert get_months_to_calculate_os_metrics_for(day_starts, [], date(2026, 1, 31)) == [date(2026, 1, 1)]
    assert get_months_to_calculate_os_metrics_for(day_starts, [], date(2026, 2, 27)) == [date(2026, 1, 1)]
    assert get_months_to_calculate_os_metrics_for(day_starts, [], None) == []


def test_month_without_month_rows_is_calculated_by_a_later_rebuild():
    """Every completed month with no month rows is returned, however long ago its days were rebuilt."""
    day_starts = [date(2025, 3, 10), date(2025, 4, 2), date(2025, 4, 20), date(2025, 6, 1)]

    assert get_months_to_calculate_os_metrics_for(day_starts, [date(2025, 4, 1)], date(2025, 7, 15)) == [
        date(2025, 3, 1),
        date(2025, 6, 1),
    ]


def test_month_end():
    assert os_metrics_month_end(date(2026, 1, 1)) == date(2026, 1, 31)
    assert os_metrics_month_end(date(2024, 2, 1)) == date(2024, 2, 29)
    assert os_metrics_month_end(date(2025, 12, 1)) == date(2025, 12, 31)
    assert os_metrics_month_end(date(9999, 12, 1)) == date(9999, 12, 31)


def test_full_months_are_the_months_wholly_inside_the_range():
    assert os_metrics_full_months(date(2026, 1, 1), date(2026, 3, 31)) == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]
    assert os_metrics_full_months(date(2026, 1, 2), date(2026, 3, 30)) == [date(2026, 2, 1)]
    assert os_metrics_full_months(date(2026, 1, 10), date(2026, 2, 20)) == []
    assert os_metrics_full_months(date(9999, 12, 1), date(9999, 12, 31)) == [date(9999, 12, 1)]


# ---------------------------------------------------------------------------
# Days of a read
# ---------------------------------------------------------------------------


def test_days_of_a_month_read_from_its_rows_are_not_read():
    """February is read from its month rows, so only the days of January and March are read."""
    days = os_metrics_days_to_read(date(2026, 1, 30), date(2026, 3, 2), [date(2026, 2, 1)])

    assert days == [date(2026, 1, 30), date(2026, 1, 31), date(2026, 3, 1), date(2026, 3, 2)]
    assert os_metrics_day_ranges(days) == [
        (date(2026, 1, 30), date(2026, 1, 31)),
        (date(2026, 3, 1), date(2026, 3, 2)),
    ]


def test_every_day_is_read_without_month_rows():
    assert len(os_metrics_days_to_read(date(2026, 2, 1), date(2026, 2, 28), [])) == 28


def test_versions_are_keyed_by_aggregation_period_and_date():
    rows = [
        _Row(aggregation_period="daily", date=date(2026, 1, 2), version=3),
        _Row(aggregation_period="monthly", date=date(2026, 1, 1), version=1),
    ]

    assert os_metrics_versions(rows) == {"daily 2026-01-02": 3, "monthly 2026-01-01": 1}


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def test_merge_os_metrics_totals():
    """The totals of several dates merge into one set of totals, with every asked field present."""
    totals = [
        {"date": date(2026, 1, 1), "runs_count": 2, "max_duration_ms": 10, "model_metrics": []},
        {
            "date": date(2026, 1, 2),
            "runs_count": 3,
            "max_duration_ms": 30,
            "duration_buckets": {"le_10": 1},
            "model_metrics": [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3}],
        },
    ]
    fields = ["runs_count", "max_duration_ms", "duration_buckets", "model_metrics", "status_metrics"]

    assert merge_os_metrics_totals(totals, fields) == {
        "runs_count": 5,
        "max_duration_ms": 30,
        "duration_buckets": {"le_10": 1},
        "model_metrics": [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3}],
        "status_metrics": {},
    }
    assert merge_os_metrics_totals([], ["sessions_count", "max_time_to_first_token_ms", "model_metrics"]) == {
        "sessions_count": 0,
        "max_time_to_first_token_ms": None,
        "model_metrics": [],
    }


def test_add_os_metrics_totals():
    """Counts and maps are summed, a maximum keeps the larger value, and models of the same name add up."""
    total = {
        "total_duration_ms": 10,
        "max_duration_ms": 30,
        "duration_buckets": {"le_10": 1},
        "model_metrics": [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1}],
    }
    fields = ["total_duration_ms", "max_duration_ms", "duration_buckets", "model_metrics"]

    add_os_metrics_totals(
        total,
        {
            "total_duration_ms": 5,
            "max_duration_ms": 20,
            "duration_buckets": {"le_10": 2, "le_12": 1},
            "model_metrics": [
                {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2},
                {"model_id": "claude", "model_provider": "Anthropic", "count": 1},
            ],
        },
        fields,
    )

    assert total == {
        "total_duration_ms": 15,
        "max_duration_ms": 30,
        "duration_buckets": {"le_10": 3, "le_12": 1},
        "model_metrics": [
            {"model_id": "claude", "model_provider": "Anthropic", "count": 1},
            {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3},
        ],
    }


def test_add_os_metrics_totals_tolerates_none():
    """A missing value or a None maximum adds nothing."""
    total = {"runs_count": 1, "max_duration_ms": None}

    add_os_metrics_totals(total, {"max_duration_ms": None}, ["runs_count", "max_duration_ms"])

    assert total == {"runs_count": 1, "max_duration_ms": None}


def test_percentile_none_for_empty():
    assert os_metrics_percentile({}, 0.5) is None
    assert os_metrics_percentile({"le_10": 0}, 0.5) is None


def test_percentile_exact_bound_for_a_single_bucket():
    """Everything in one bucket reads as that bucket's bound when the whole fraction is asked for."""
    assert os_metrics_percentile({"le_100": 7}, 1.0) == 100


def test_percentile_interpolates_inside_a_bucket():
    """Half the timings in le_100 and half in le_120: the median sits at the top of le_100, p75 halfway into le_120."""
    buckets = {"le_100": 2, "le_120": 2}

    assert os_metrics_percentile(buckets, 0.5) == 100
    assert os_metrics_percentile(buckets, 0.75) == 110


def test_percentile_of_a_single_timing_is_that_timing():
    """One run of 1000 ms fills le_1000; read alone it would be 900, but the row's max says exactly 1000."""
    assert os_metrics_percentile({"le_1000": 1}, 0.5) == 900
    assert os_metrics_percentile({"le_1000": 1}, 0.5, max_ms=1000) == 1000
    assert os_metrics_percentile({"le_1000": 1}, 0.95, max_ms=1000) == 1000


def test_percentile_never_exceeds_the_slowest_timing():
    """One run of 1709 ms fills the 2000 ms bucket; without the maximum it would read as 1750 and 1975."""
    assert os_metrics_percentile({"le_2000": 1}, 0.5) == 1750
    assert os_metrics_percentile({"le_2000": 1}, 0.5, max_ms=1709) == 1709
    assert os_metrics_percentile({"le_2000": 1}, 0.95, max_ms=1709) == 1709
    assert os_metrics_percentile({"le_100": 2, "le_120": 2}, 0.5, max_ms=115) == 100


def test_percentile_past_the_end_reads_as_the_slowest_timing():
    """Timings past the last bound read as the slowest timing recorded, else as the last bound."""
    overflow = {f"gt_{_OS_METRICS_BUCKET_BOUNDS_MS[-1]}": 2}

    assert os_metrics_percentile(overflow, 0.5) == _OS_METRICS_BUCKET_BOUNDS_MS[-1]
    assert os_metrics_percentile(overflow, 0.5, max_ms=10_000_000) == 10_000_000
    assert os_metrics_percentile(overflow, 0.95, max_ms=10_000_000) == 10_000_000


def test_percentile_within_one_bucket_of_true_median():
    """A median read from the buckets is within the width of the bucket the true median falls in."""
    milliseconds = [(i * 7919) % 5000 + 15 for i in range(200)]
    runs = [_run(f"run-{i}", duration=ms / 1000) for i, ms in enumerate(milliseconds)]
    buckets = _only_row(runs=runs)["duration_buckets"]
    true_median = statistics.median(milliseconds)
    upper = next(bound for bound in _OS_METRICS_BUCKET_BOUNDS_MS if true_median <= bound)
    lower = max((bound for bound in _OS_METRICS_BUCKET_BOUNDS_MS if bound < upper), default=0)

    assert sum(buckets.values()) == 200
    assert abs(os_metrics_percentile(buckets, 0.5) - true_median) <= upper - lower


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------


def test_resolve_fields_defaults_to_everything():
    assert resolve_os_metrics_fields(None) == list(OS_METRICS_FIELDS)
    assert {"sessions_count", "total_tokens", "status_metrics", "duration_buckets", "model_metrics"} <= set(
        OS_METRICS_FIELDS
    )


def test_resolve_fields_accepts_columns_and_rejects_unknown():
    assert resolve_os_metrics_fields(["duration_buckets", "runs_count"]) == ["duration_buckets", "runs_count"]
    with pytest.raises(ValueError, match="token_metrics"):
        resolve_os_metrics_fields(["runs_count", "token_metrics"])


# ---------------------------------------------------------------------------
# Postgres row shaping
# ---------------------------------------------------------------------------


def test_build_os_metrics_run_rebuilds_the_stored_run_shape():
    """The columns the runs query picks are put back into the run_data shape the rollup reads."""
    run = build_os_metrics_run(
        _Row(
            run_id="run-1",
            run_type="agent",
            agent_id="agent-1",
            team_id=None,
            workflow_id=None,
            user_id="alice",
            status=COMPLETED,
            metrics={"duration": 1.0, "details": {"gpt-5": {}}},
            model="gpt-5",
            model_provider="OpenAI",
            call_durations=[0.2, 0.3],
            nested_runs=None,
        )
    )

    assert run["run_data"] == {
        "metrics": {"duration": 1.0, "details": {"gpt-5": {}}},
        "model": "gpt-5",
        "model_provider": "OpenAI",
        "messages": [
            {"role": "assistant", "metrics": {"duration": 0.2}},
            {"role": "assistant", "metrics": {"duration": 0.3}},
        ],
    }
    row = _only_row(runs=[run])
    assert row["model_calls_count"] == 2


def test_build_os_metrics_run_without_calls():
    """No call durations store no messages."""
    run = build_os_metrics_run(
        _Row(
            run_id="run-1",
            run_type="agent",
            agent_id="agent-1",
            user_id=None,
            status=COMPLETED,
            metrics=None,
            model=None,
            model_provider=None,
            call_durations=None,
            nested_runs=None,
        )
    )

    assert run["run_data"]["messages"] == []
    assert _only_row(runs=[run])["runs_count"] == 1


def test_build_os_metrics_run_nests_the_nested_runs_again():
    """The nested runs the runs query reads flat are put back inside the run each one is nested in."""

    def nested_row(depth, key, run_id, call_durations=(), **ids):
        return {
            "depth": depth,
            "key": key,
            "run_id": run_id,
            "agent_id": ids.get("agent_id"),
            "team_id": ids.get("team_id"),
            "metrics": {"input_tokens": 10, "details": {"gpt-5": {}}},
            "model": "gpt-5",
            "model_provider": "OpenAI",
            "call_durations": list(call_durations),
        }

    run = build_os_metrics_run(
        _Row(
            run_id="run-1",
            run_type="workflow",
            workflow_id="wf-1",
            user_id="alice",
            status=COMPLETED,
            metrics=None,
            model=None,
            model_provider=None,
            call_durations=[],
            nested_runs=[
                nested_row(1, "step_executor_runs", "team-run", team_id="team-1"),
                nested_row(2, "member_responses", "member-run", call_durations=[0.2], agent_id="agent-1"),
                nested_row(3, "member_responses", "unnamed-run"),
                nested_row(1, "step_executor_runs", "agent-run", agent_id="agent-2"),
                nested_row(1, "member_responses", "other-run", agent_id="agent-3"),
            ],
        )
    )

    step_team, step_agent = run["run_data"]["step_executor_runs"]
    assert [step_team["run_id"], step_agent["run_id"]] == ["team-run", "agent-run"]
    assert [nested_run["run_id"] for nested_run in run["run_data"]["member_responses"]] == ["other-run"]
    (member,) = step_team["member_responses"]
    assert member["messages"] == [{"role": "assistant", "metrics": {"duration": 0.2}}]
    assert [nested_run["run_id"] for nested_run in member["member_responses"]] == ["unnamed-run"]
    assert "member_responses" not in step_agent
    assert os_metrics_nested_run_ids([run]) == {"team-run", "member-run", "unnamed-run", "agent-run", "other-run"}
    row = _only_row(runs=[run])
    assert row["input_tokens"] == 50
    assert row["model_calls_count"] == 1
    assert row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 5}]


def test_build_os_metrics_totals_assembles_each_query():
    """The totals query fills the columns; the count map and model queries fill the maps and the model list."""
    fields = [
        "runs_count",
        "total_tokens",
        "max_duration_ms",
        "max_time_to_first_token_ms",
        "duration_buckets",
        "model_metrics",
    ]
    totals_row = {
        "date": date(2026, 1, 1),
        "updated_at": 10,
        "runs_count": 3,
        "total_tokens": 12,
        "max_duration_ms": 900,
        "max_time_to_first_token_ms": None,
    }
    rows_by_query = {
        "totals": [_Row(**totals_row), _Row(**{**totals_row, "date": date(2025, 12, 31), "updated_at": 4})],
        "count_maps": [_Row(date=date(2026, 1, 1), field="duration_buckets", key="le_1000", count=3)],
        "model_metrics": [
            _Row(date=date(2026, 1, 1), model_id="gpt-5-mini", model_provider="", count=1),
            _Row(date=date(2026, 1, 1), model_id="gpt-5", model_provider="OpenAI", count=3),
        ],
    }

    totals, latest = build_os_metrics_totals(fields, rows_by_query)

    assert latest == 10
    assert [total["date"] for total in totals] == [date(2025, 12, 31), date(2026, 1, 1)]
    assert totals[1] == {
        "date": date(2026, 1, 1),
        "runs_count": 3,
        "total_tokens": 12,
        "max_duration_ms": 900,
        "max_time_to_first_token_ms": None,
        "duration_buckets": {"le_1000": 3},
        "model_metrics": [
            {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3},
            {"model_id": "gpt-5-mini", "model_provider": "", "count": 1},
        ],
    }
    assert totals[0]["duration_buckets"] == {}
    assert totals[0]["model_metrics"] == []
