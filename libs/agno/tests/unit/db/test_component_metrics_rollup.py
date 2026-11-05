"""Unit tests for the component metrics rollup helpers.

``calculate_date_component_metrics`` turns one day's stored sessions and runs into one row of
agno_component_metrics per owner and agent, team or workflow. The helpers around it build the rows of a day or month
for agno_aggregate_metrics, and decide which rebuilt rows to write.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import agno
from agno.db.postgres import PostgresDb
from agno.db.postgres.utils import build_component_metrics_run
from agno.db.utils import (
    METRICS_COMPONENT_TYPES,
    METRICS_DAY_GRACE_SECONDS,
    METRICS_FIELDS,
    METRICS_READ_FIELDS,
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_FIELDS,
    add_metrics_month_totals,
    add_metrics_totals,
    aggregate_metrics_row_to_write,
    aggregate_metrics_rows_to_write,
    build_aggregate_metrics_month_rows,
    build_aggregate_metrics_row,
    build_aggregate_metrics_rows,
    build_component_metrics_totals,
    build_metrics_by_owner,
    build_metrics_from_aggregate_metrics,
    calculate_date_component_metrics,
    component_metrics_rows_to_write,
    empty_metrics_totals,
    get_months_to_calculate_metrics_for,
    list_metrics_models,
    merge_metrics_totals,
    metrics_day_completed,
    metrics_day_ranges,
    metrics_day_to_reopen,
    metrics_days_since_last_calculation,
    metrics_full_months,
    metrics_month_end,
    metrics_nested_run_ids,
    metrics_refresh_status,
    metrics_remote_member_team_session_ids,
    resolve_metrics_fields,
)
from agno.metrics import BaseMetrics
from agno.run.base import RunStatus

TARGET_DATE = date(2026, 1, 1)

COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value
REGENERATED = RunStatus.regenerated.value

# The keys that differ between two builds of the same day.
EPHEMERAL = {"created_at", "updated_at"}

# The row of the metrics refreshes table while a refresh holds its lock.
RUNNING_REFRESH = {
    "locked_by": "worker",
    "locked_at": 400,
    "started_at": 100,
    "finished_at": 50,
    "status": "running",
    "error": None,
    "fingerprint": None,
}


def _session(user_id="alice", session_type="agent", component_id="agent-1"):
    """Build a stored session the way the sessions query returns it."""
    return {"session_type": session_type, "user_id": user_id, f"{session_type}_id": component_id}


def _tool_call(tool_name, duration=None, error=None, toolkit=None, tool_call_id=None, **hitl):
    """Build a tool call the way the runs query returns it, with the id a stored run keeps and its HITL fields when
    given."""
    tool_call = {
        "toolkit": toolkit,
        "tool_name": tool_name,
        "tool_call_error": error,
        "metrics": {"duration": duration},
        **hitl,
    }
    if tool_call_id:
        tool_call["tool_call_id"] = tool_call_id
    return tool_call


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
    tools=None,
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
    if tools is not None:
        call["tools"] = tools
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
        for row in calculate_date_component_metrics(TARGET_DATE, list(sessions), list(runs), set(stored_run_ids), [])
    }


def _only_row(sessions=(), runs=()):
    rows = list(_rows(sessions, runs).values())
    assert len(rows) == 1
    return rows[0]


def _stable(row):
    return {key: value for key, value in row.items() if key not in EPHEMERAL}


def _day_rows(runs, sessions=(), day=TARGET_DATE):
    return calculate_date_component_metrics(day, list(sessions), list(runs), set(), [])


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
    """Sessions and runs of one owner for one component share a row, and each run adds one to that row alone."""
    rows = _rows(
        sessions=[_session("alice"), _session("alice"), _session("bob"), _session("alice", "team", "team-1")],
        runs=[
            _run("run-1", user_id="alice"),
            _run("run-2", user_id="alice"),
            _run("run-3", user_id="alice", run_type="team", component_id="team-1"),
            _run("run-4", user_id="bob"),
        ],
    )

    assert set(rows) == {("alice", "agent", "agent-1"), ("bob", "agent", "agent-1"), ("alice", "team", "team-1")}
    assert rows[("alice", "agent", "agent-1")]["sessions_count"] == 2
    assert {key: row["runs_count"] for key, row in rows.items()} == {
        ("alice", "agent", "agent-1"): 2,
        ("alice", "team", "team-1"): 1,
        ("bob", "agent", "agent-1"): 1,
    }


def test_session_without_user_lands_under_empty_string():
    """A session with no user_id is counted under the "" owner."""
    row = _only_row(sessions=[_session(None)])

    assert row["user_id"] == ""
    assert row["sessions_count"] == 1


def test_session_compaction_metrics_are_counted_on_the_session_row():
    """A manual compaction no run carries keeps its usage in the session's compaction metrics, which count on the
    session's row beside its runs."""
    session = {
        **_session("alice"),
        "compaction_metrics": {"input_tokens": 700, "output_tokens": 24, "total_tokens": 724},
    }
    row = _only_row(sessions=[session], runs=[_run("run-1", user_id="alice", tokens={"total_tokens": 10})])

    assert (row["total_tokens"], row["runs_count"]) == (734, 1)


def test_only_the_id_matching_the_component_type_is_used():
    """A team session that also names an agent is counted under the team alone."""
    session = {**_session("alice", "team", "team-1"), "agent_id": "agent-1"}
    row = _only_row(sessions=[session])

    assert (row["component_type"], row["component_id"]) == ("team", "team-1")


def test_component_types_are_the_session_types():
    """A row is counted under an agent, a team or a workflow; a session of any other type is skipped."""
    assert METRICS_COMPONENT_TYPES == ("agent", "team", "workflow")
    assert _rows(sessions=[{"session_type": "agents", "user_id": "alice"}, _session("alice")]) == {
        ("alice", "agent", "agent-1"): _only_row(sessions=[_session("alice")])
    }


def test_additional_metrics_of_the_runs_are_added_up():
    """The rest a run reports beside its tokens, such as eval_duration, is added up on its row."""
    row = _only_row(
        runs=[
            _run("run-1", tokens={"additional_metrics": {"eval_duration": 1.5}}),
            _run("run-2", tokens={"additional_metrics": {"eval_duration": 2.0}}),
        ]
    )

    assert row["additional_metrics"] == {"eval_duration": 3.5}


def test_row_shape():
    """A row carries the columns the upsert expects, keyed by aggregation period, date, owner, component and parent."""
    row = _only_row(runs=[_run()])

    assert tuple(
        row[column]
        for column in ("aggregation_period", "date", "user_id", "component_type", "component_id", "parent_component_id")
    ) == (
        "daily",
        TARGET_DATE,
        "alice",
        "agent",
        "agent-1",
        "",
    )
    assert row["additional_metrics"] == {}
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 1}}}
    assert "id" not in row
    assert "completed" not in row
    assert set(METRICS_FIELDS) <= set(row)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


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


def test_every_run_names_the_component_that_started_the_whole_run_as_its_root():
    """A member of a nested team names the outermost team as its root, and a run no run started names itself."""
    rows = calculate_date_component_metrics(
        TARGET_DATE,
        [_session("alice", "team", "outer-team")],
        [
            _run("inner-run", run_type="team", component_id="inner-team", parent_run_id="outer-run"),
            _run("member-run", component_id="member-1", parent_run_id="inner-run"),
        ],
        set(),
        [{"run_id": "outer-run", "run_type": "team", "team_id": "outer-team", "parent_run_id": None}],
    )

    assert [(row["component_id"], row["parent_component_id"], row["root_component_id"]) for row in rows] == [
        ("member-1", "inner-team", "outer-team"),
        ("inner-team", "outer-team", "outer-team"),
        ("outer-team", "", "outer-team"),
    ]


def test_harness_state_session_is_not_counted_but_an_agent_with_team_metadata_is():
    """A harness agent's own session for a team's session is named after it; an agent whose own metadata names a
    team is still counted."""
    state_session = {
        **_session("alice", "agent", "claude"),
        "session_id": "team-session:claude",
        "metadata": {"team_id": "team-1"},
    }
    own_session = {**_session("alice", "agent", "agent-1"), "session_id": "s-1", "metadata": {"team_id": "acme"}}

    rows = calculate_date_component_metrics(TARGET_DATE, [state_session, own_session], [], set(), [])

    assert [(row["component_id"], row["sessions_count"]) for row in rows] == [("agent-1", 1)]


def test_remote_member_run_and_session_are_counted_under_the_team_on_a_shared_database():
    """A remote member's AgentOS stores its run with no parent, in a session named after the team's session; on a
    shared database the team's run names the parent, so the team's run is the one root run and session."""
    member = {
        **_model_call(run_id="remote-run", agent_id="external-agent"),
        "session_id": "team-session:remote-agent",
        "parent_run_id": "team-run",
    }
    team_run = {
        **_run("team-run", run_type="team", component_id="team-1", member_responses=[member]),
        "session_id": "team-session",
    }
    remote_run = {**_run("remote-run", component_id="remote-agent"), "session_id": "team-session:remote-agent"}
    sessions = [
        {**_session("alice", "team", "team-1"), "session_id": "team-session"},
        {**_session("alice", "agent", "remote-agent"), "session_id": "team-session:remote-agent"},
    ]

    rows = calculate_date_component_metrics(TARGET_DATE, sessions, [team_run, remote_run], {"remote-run"}, [])

    assert [
        (row["component_id"], row["parent_component_id"], row["root_component_id"], row["sessions_count"])
        for row in rows
    ] == [("remote-agent", "team-1", "team-1", 0), ("team-1", "", "team-1", 1)]
    total = build_aggregate_metrics_row(rows, "daily", TARGET_DATE, True)
    assert (total["root_runs_count"], total["agent_sessions_count"], total["team_sessions_count"]) == (1, 0, 1)


def test_remote_member_run_after_midnight_is_counted_under_the_team_run_of_the_day_before():
    """A remote member's run no run of its day names asks for its team's session, whose run of the day before names
    the parent, so the member run is no root run and its session no session of its own."""
    member = {
        **_model_call(run_id="remote-run", agent_id="external-agent"),
        "session_id": "team-session:remote-agent",
        "parent_run_id": "team-run",
    }
    team_run = {
        **_run("team-run", run_type="team", component_id="team-1", member_responses=[member]),
        "session_id": "team-session",
    }
    remote_run = {**_run("remote-run", component_id="remote-agent"), "session_id": "team-session:remote-agent"}
    sessions = [{**_session("alice", "agent", "remote-agent"), "session_id": "team-session:remote-agent"}]

    assert metrics_remote_member_team_session_ids([remote_run]) == {"team-session"}
    assert metrics_remote_member_team_session_ids([team_run, remote_run]) == set()
    rows = calculate_date_component_metrics(TARGET_DATE, sessions, [remote_run], set(), [team_run])

    assert [
        (row["component_id"], row["parent_component_id"], row["root_component_id"], row["sessions_count"])
        for row in rows
    ] == [("remote-agent", "team-1", "team-1", 0)]


def test_sandboxed_member_record_of_a_member_run_of_another_day_is_not_counted():
    """A sandboxed member's own record repeats a member run stored on any day, so only the member run counts."""
    record = _run("member-run.sandbox", component_id="member-1")

    assert metrics_nested_run_ids([record]) == {"member-run"}
    assert calculate_date_component_metrics(TARGET_DATE, [], [record], {"member-run"}, []) == []


def test_run_with_a_bad_value_is_skipped_and_the_day_is_kept():
    """One run with tokens stored as text never stops the rest of its day from being counted."""
    rows = _day_rows([_run("run-1", tokens={"total_tokens": "many"}), _run("run-2", tokens={"total_tokens": 7})])

    assert [(row["runs_count"], row["total_tokens"]) for row in rows] == [(1, 7)]


def test_member_run_and_the_same_agent_alone_are_two_rows():
    """The same agent alone and as a team's member is two rows told apart by parent_component_id; the total holds."""
    runs = [
        _run("team-run", run_type="team", component_id="team-1", tokens={"total_tokens": 300}),
        _run("member-run", component_id="member-1", parent_run_id="team-run", tokens={"total_tokens": 500}),
        _run("alone-run", component_id="member-1", tokens={"total_tokens": 120}),
    ]
    rows = {(row["component_id"], row["parent_component_id"]): row["total_tokens"] for row in _day_rows(runs)}

    assert rows == {("team-1", ""): 300, ("member-1", "team-1"): 500, ("member-1", ""): 120}
    total = build_aggregate_metrics_row(_day_rows(runs), "daily", TARGET_DATE, True)
    assert (total["total_tokens"], total["agent_runs_count"], total["team_runs_count"]) == (920, 2, 1)
    # The member run was started by the team run
    assert total["root_runs_count"] == 2


def test_a_team_run_with_one_member_is_one_root_run():
    """A team run with one member is one agent run, one team run, and one run no other run started."""
    runs = [
        _run("team-run", run_type="team", component_id="team-1"),
        _run("member-run", component_id="member-1", parent_run_id="team-run"),
    ]

    total = build_aggregate_metrics_row(_day_rows(runs), "daily", TARGET_DATE, True)

    assert (total["agent_runs_count"], total["team_runs_count"], total["root_runs_count"]) == (1, 1, 1)


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
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}


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
    assert rows[("alice", "team", "inner-team")]["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}


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


def test_messages_a_forked_run_copied_are_not_model_calls():
    """A forked run's first messages are copies of the run it was forked from, which counts them."""
    run = _run(call_durations=(0.9, 0.2, 0.3))
    run["run_data"]["forked_from_message_index"] = 1
    row = _only_row(runs=[run])

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


def test_every_token_count_is_kept_under_its_own_name():
    """Every token count a model call reports is kept under the name of its BaseMetrics field: the cache and audio
    counts as keys of token_details, the others in a column each. The audio total is not kept: a read adds it up."""
    row = _only_row(
        runs=[
            _run(
                "run-1", tokens={"input_tokens": 5, "output_tokens": 0, "reasoning_tokens": 0, "cache_read_tokens": 3}
            ),
            _run("run-2", tokens={"audio_input_tokens": 200, "audio_output_tokens": 50, "audio_total_tokens": 250}),
            _run("run-3", tokens={"audio_output_tokens": 30, "audio_total_tokens": 30}),
        ]
    )

    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (5, 0, 0)
    assert row["reasoning_tokens"] == 0
    assert row["token_details"] == {"cache_read_tokens": 3, "audio_input_tokens": 200, "audio_output_tokens": 80}
    assert "audio_total_tokens" not in row
    assert set(METRICS_TOKEN_FIELDS) == {
        field for field in BaseMetrics.__dataclass_fields__ if field.endswith("_tokens")
    }


def test_cost_counts_only_the_runs_that_reported_one():
    """The cost of the runs that reported one is kept in token_details with how many runs did, and each model's own
    cost beside its count."""
    run = _run("run-1", tokens={"cost": 0.0123})
    run["run_data"]["metrics"]["details"] = {"model": [{"id": "gpt-5", "provider": "OpenAI", "cost": 0.0123}]}
    row = _only_row(runs=[run, _run("run-2")])

    assert row["token_details"] == {"cost": 0.0123, "cost_runs_count": 1}
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2, "cost": 0.0123}}}


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


def test_timing_counted_in_the_right_bucket():
    """A timing is counted under the smallest bound it does not exceed."""
    row = _only_row(runs=[_run(duration=1.234)])

    assert row["duration_buckets"] == {"le_1500": 1}


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

    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}


def test_every_model_a_run_used_is_a_model_entry():
    """A run counts each model its details name, such as its output model and its eval model, beside its own."""
    run = _run()
    run["run_data"]["metrics"]["details"] = {
        "model": [{"id": "gpt-5", "provider": "OpenAI"}],
        "output_model": [{"id": "gpt-5-mini", "provider": "OpenAI"}],
        "eval_model": [{"id": "claude-sonnet-4-5", "provider": "Anthropic"}],
    }
    row = _only_row(runs=[run])

    assert row["model_metrics"] == {
        "Anthropic": {"claude-sonnet-4-5": {"count": 1}},
        "OpenAI": {"gpt-5": {"count": 1}, "gpt-5-mini": {"count": 1}},
    }


def test_every_model_of_the_run_models_class_has_the_run_models_label():
    """A model of the same class as the run's own model is labelled by the run's provider, as the run's own model is,
    not by the provider name details keep for the class."""
    run = _run(provider="OpenAI")
    run["run_data"]["metrics"]["details"] = {
        "model": [{"id": "gpt-5", "provider": "OpenAI Responses"}],
        "output_model": [{"id": "gpt-5-mini", "provider": "OpenAI Responses"}],
    }
    row = _only_row(runs=[run])

    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 1}, "gpt-5-mini": {"count": 1}}}


def test_a_model_of_another_class_is_labelled_by_its_provider():
    """A model of another class than the run's own model, such as an OpenAIResponses output model on an OpenAIChat
    run, is labelled by its provider without the class name, so one model id has one label."""
    run = _run(model="gpt-5", provider="OpenAI")
    run["run_data"]["metrics"]["details"] = {
        "model": [{"id": "gpt-5", "provider": "OpenAI Chat"}],
        "output_model": [{"id": "gpt-5-nano", "provider": "OpenAI Responses"}],
    }
    row = _only_row(runs=[run])

    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 1}, "gpt-5-nano": {"count": 1}}}


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

    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 1}, "gpt-5-mini": {"count": 1}}}


def test_workflow_agent_run_counts_on_the_workflow_row():
    """A workflow agent's run is nested inside the workflow's run as the run itself, and its calls count there."""
    run = _run(run_type="workflow", component_id="wf-1", model=None)
    run["run_data"]["workflow_agent_run"] = _model_call(tokens={"total_tokens": 7}, call_durations=(0.4,))
    row = _only_row(runs=[run])

    assert (row["total_tokens"], row["model_calls_count"], row["total_model_call_ms"]) == (7, 1, 400)


def test_a_run_that_reports_no_usage_still_counts_its_model():
    """A run that reports no usage, as an external agent's run does, counts its model once, as agno_metrics did."""
    run = _run(model="claude-sonnet-4-5", provider="Anthropic", details=False)
    run["run_data"]["metrics"] = None
    row = _only_row(runs=[run])

    assert row["model_metrics"] == {"Anthropic": {"claude-sonnet-4-5": {"count": 1}}}
    assert row["total_tokens"] == 0


def test_a_run_that_names_no_model_still_counts_its_usage():
    """A run that reports usage but names no model, such as an external agent's, counts its usage but no model."""
    member = _model_call(model=None, tokens={"total_tokens": 100}, agent_id="external-agent", run_id="member-run")
    row = _only_row(
        runs=[_run(run_type="team", component_id="team-1", tokens={"total_tokens": 15}, member_responses=[member])]
    )

    assert row["total_tokens"] == 115
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 1}}}


def test_an_errored_run_whose_model_never_answered_still_counts_its_model():
    """A run whose model failed before answering reports no details, and still counts its model once."""
    row = _only_row(runs=[_run(status=ERROR, details=False, tokens={"input_tokens": 3})])

    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 1}}}
    assert row["input_tokens"] == 3


def test_model_metrics_are_listed_sorted_deterministically():
    """model_metrics, counted per provider and model, lists sorted by model and provider whatever order the runs
    arrived in."""
    runs = [
        _run("run-1", model="gpt-5", provider="OpenAI"),
        _run("run-2", model="claude", provider="Anthropic"),
        _run("run-3", model="claude", provider="Anthropic", component_id="agent-0"),
    ]
    forward = _rows(runs=runs)
    backward = _rows(runs=list(reversed(runs)))

    models = list_metrics_models(forward[("alice", "agent", "agent-1")]["model_metrics"])
    ids = [(m["model_id"], m["model_provider"]) for m in models]
    assert ids == [("claude", "Anthropic"), ("gpt-5", "OpenAI")]
    for key, row in forward.items():
        assert row["model_metrics"] == backward[key]["model_metrics"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_tool_calls_count_per_toolkit_and_tool():
    """Each tool call adds a call to its tool under its toolkit, a failure when it errored, and its timing when it
    recorded one; an entry that names no tool is not a tool call."""
    first = _run(
        run_id="run-1",
        tools=[
            _tool_call("search", duration=0.4),
            _tool_call("search", duration=1.2, error=True),
            _tool_call("create_issue", duration=0.05, toolkit="github"),
            _tool_call(None, duration=9.0),
            "not a tool call",
        ],
    )
    second = _run(run_id="run-2", tools=[_tool_call("search", duration=0.1)])

    row = _only_row(runs=[first, second])

    assert row["tool_metrics"] == {
        "": {
            "search": {
                "count": 3,
                "failed_count": 1,
                "total_ms": 1700,
                "max_ms": 1200,
                "buckets": {"le_100": 1, "le_400": 1, "le_1200": 1},
            }
        },
        "github": {
            "create_issue": {"count": 1, "failed_count": 0, "total_ms": 50, "max_ms": 50, "buckets": {"le_50": 1}}
        },
    }


def test_a_stored_member_counts_its_tool_calls_on_its_own_row_only():
    """A member run stored as a run of its own counts its tool calls on its row, never again on its team's."""
    member_call = _model_call(run_id="member-run", agent_id="agent-1", tools=[_tool_call("search", duration=0.2)])
    team_run = _run(
        run_id="team-run",
        run_type="team",
        component_id="team-1",
        member_responses=[member_call],
        tools=[_tool_call("delegate_task_to_member", duration=0.3)],
    )
    member_run = _run(run_id="member-run", parent_run_id="team-run", tools=[_tool_call("search", duration=0.2)])

    rows = _rows(runs=[team_run, member_run])

    assert set(rows[("alice", "team", "team-1")]["tool_metrics"][""]) == {"delegate_task_to_member"}
    assert rows[("alice", "agent", "agent-1")]["tool_metrics"][""]["search"]["count"] == 1


def test_tool_calls_a_forked_run_copied_are_not_counted():
    """A forked run's first messages are copies of the run it was forked from, which counts the tool calls they
    answer."""
    run = _run(
        tools=[
            _tool_call("search", duration=0.9, tool_call_id="copied-call"),
            _tool_call("search", duration=0.2, tool_call_id="new-call"),
        ]
    )
    run["run_data"]["messages"] = [
        {"role": "tool", "tool_call_id": "copied-call"},
        {"role": "tool", "tool_call_id": "new-call"},
    ]
    run["run_data"]["forked_from_message_index"] = 1
    row = _only_row(runs=[run])

    assert row["tool_metrics"] == {
        "": {"search": {"count": 1, "failed_count": 0, "total_ms": 200, "max_ms": 200, "buckets": {"le_200": 1}}}
    }


def test_a_tool_call_the_user_rejected_is_not_counted():
    """A tool call the user rejected is marked as an error but never ran, so it is no call and no failure."""
    run = _run(
        tools=[
            _tool_call("delete_file", error=True, confirmed=False),
            _tool_call("delete_file", duration=0.2, confirmed=True),
        ]
    )
    row = _only_row(runs=[run])

    assert row["tool_metrics"] == {
        "": {"delete_file": {"count": 1, "failed_count": 0, "total_ms": 200, "max_ms": 200, "buckets": {"le_200": 1}}}
    }


def test_a_tool_call_still_paused_is_not_counted():
    """A tool call waiting on a confirmation, a user's input or an external execution has not run yet."""
    run = _run(
        tools=[
            _tool_call("delete_file", requires_confirmation=True),
            _tool_call("get_user_input", requires_user_input=True),
            _tool_call("send_email", external_execution_required=True),
            _tool_call("send_email", duration=0.2, external_execution_required=False),
        ]
    )
    row = _only_row(runs=[run])

    assert row["tool_metrics"] == {
        "": {"send_email": {"count": 1, "failed_count": 0, "total_ms": 200, "max_ms": 200, "buckets": {"le_200": 1}}}
    }


def test_a_run_with_no_model_counts_its_tool_calls():
    """A run that records no model, such as an adapter's, counts no model call but still counts its tool calls."""
    run = _run(model=None, tools=[_tool_call("search", duration=0.2)])
    row = _only_row(runs=[run])

    assert row["model_metrics"] == {}
    assert row["tool_metrics"] == {
        "": {"search": {"count": 1, "failed_count": 0, "total_ms": 200, "max_ms": 200, "buckets": {"le_200": 1}}}
    }


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------


def test_rebuild_yields_identical_rows_and_writes_nothing():
    """Two builds of the same inputs differ only in their timestamps, so a rebuild returns no rows and no stale keys."""
    runs = [_run("run-1", duration=1.0, call_durations=(0.2,)), _run("run-2", status=ERROR)]
    first = calculate_date_component_metrics(TARGET_DATE, [_session()], runs, set(), [])
    second = calculate_date_component_metrics(TARGET_DATE, [_session()], runs, set(), [])

    assert [_stable(row) for row in first] == [_stable(row) for row in second]
    assert component_metrics_rows_to_write(second, first) == ([], [])


def test_only_new_changed_and_stale_rows_are_returned():
    """A new or changed row is returned to be written, a stored row the rebuild no longer produces is stale, and an
    unchanged row is left alone."""
    new_rows = _day_rows([_run("run-1")])
    assert component_metrics_rows_to_write(new_rows, []) == (new_rows, [])

    stored = _day_rows([_run("run-1", user_id="alice"), _run("run-2", user_id="bob")])
    # Bob's row is returned by its owner, component and parent for deletion
    rebuilt = _day_rows([_run("run-1", user_id="alice")])
    assert component_metrics_rows_to_write(rebuilt, stored) == ([], [("bob", "agent", "agent-1", "", "agent-1")])

    # Only Alice's row moved, so Bob's row is left alone
    rebuilt = _day_rows([_run("run-1", user_id="alice"), _run("run-2", user_id="bob"), _run("run-3", user_id="alice")])
    changed, stale = component_metrics_rows_to_write(rebuilt, stored)
    assert [row["user_id"] for row in changed] == ["alice"]
    assert stale == []


def test_rows_to_write_come_in_key_order():
    """Rows are written in key order, so no two writers lock rows in opposite orders."""
    rebuilt = _day_rows([_run("run-1", user_id="bob"), _run("run-2", user_id="alice")])

    changed, _ = component_metrics_rows_to_write(list(reversed(rebuilt)), [])

    assert [row["user_id"] for row in changed] == ["alice", "bob"]


# ---------------------------------------------------------------------------
# Aggregate metrics rows
# ---------------------------------------------------------------------------


def test_aggregate_metrics_rows_are_the_everyone_row_then_one_row_per_user():
    """Alice's two rows and Bob's one are totalled into the everyone row of the day, with no component, the runs
    with no user included; each user gets a row of their own runs."""
    rows = _day_rows(
        sessions=[_session("alice"), _session("alice", "team", "team-1"), _session("bob")],
        runs=[
            _run("run-1", user_id="alice", tokens={"total_tokens": 10}, duration=1.0),
            _run("run-2", "team", "team-1", user_id="alice", tokens={"total_tokens": 20}, duration=3.0),
            _run("run-3", user_id="bob", status=ERROR, details=False),
        ],
    )

    day = build_aggregate_metrics_row(rows, "daily", TARGET_DATE, completed=True)

    assert (day["aggregation_period"], day["date"], day["completed"]) == ("daily", TARGET_DATE, True)
    assert day["user_id"] == ""
    assert "component_type" not in day
    assert (day["agent_sessions_count"], day["team_sessions_count"], day["workflow_sessions_count"]) == (2, 1, 0)
    assert (day["agent_runs_count"], day["team_runs_count"], day["workflow_runs_count"], day["root_runs_count"]) == (
        2,
        1,
        0,
        3,
    )
    assert "sessions_count" not in day and "runs_count" not in day
    assert day["status_metrics"] == {COMPLETED: 2, ERROR: 1}
    assert day["total_tokens"] == 30
    assert (day["duration_runs_count"], day["total_duration_ms"], day["max_duration_ms"]) == (2, 4000, 3000)
    assert day["duration_buckets"] == {"le_1000": 1, "le_3000": 1}
    assert day["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 3}}}
    assert day["metrics_version"] == agno.__version__
    assert day["users_count"] == 2

    rows = _day_rows(
        runs=[
            _run("run-1", user_id="alice", tokens={"total_tokens": 10}),
            _run("run-2", user_id="bob", tokens={"total_tokens": 20}),
            _run("run-3", user_id="", tokens={"total_tokens": 5}),
        ],
    )

    everyone, alice, bob = build_aggregate_metrics_rows(rows, "daily", TARGET_DATE, completed=True)

    assert (everyone["user_id"], everyone["total_tokens"], everyone["users_count"]) == ("", 35, 2)
    assert (alice["user_id"], alice["total_tokens"], alice["users_count"]) == ("alice", 10, 1)
    assert (bob["user_id"], bob["total_tokens"], bob["users_count"]) == ("bob", 20, 1)


def test_aggregate_metrics_rows_to_write_keep_the_everyone_row_apart():
    """The everyone row goes through the version check; a user row is written when new or changed, and a stored
    user row the day no longer has is stale."""
    aggregate_metrics_rows = build_aggregate_metrics_rows(
        _day_rows([_run("run-1", user_id="alice")]), "daily", TARGET_DATE, False
    )
    stored = [{**row, "version": 3} for row in aggregate_metrics_rows] + [
        {**aggregate_metrics_rows[1], "user_id": "carol"}
    ]

    everyone_row, changed_rows, stale_user_ids = aggregate_metrics_rows_to_write(
        aggregate_metrics_rows, stored, rows_changed=True
    )

    assert everyone_row is aggregate_metrics_rows[0]
    assert changed_rows == []
    assert stale_user_ids == ["carol"]


def test_get_metrics_rows_add_up_the_audio_total():
    """The audio total an aggregate metrics row reads with is the sum of the audio counts it keeps."""
    [everyone] = build_aggregate_metrics_rows(
        _day_rows([_run("run-1", user_id="", tokens={"audio_input_tokens": 200, "audio_output_tokens": 50})]),
        "daily",
        TARGET_DATE,
        False,
    )

    [metric] = build_metrics_from_aggregate_metrics([everyone])

    token_metrics = metric["token_metrics"]
    assert (token_metrics["audio_input_tokens"], token_metrics["audio_output_tokens"]) == (200, 50)
    assert token_metrics["audio_total_tokens"] == 250


def test_days_since_the_last_calculation_are_rebuilt():
    """The days before yesterday from the day before the last calculation finished are picked, so a day written
    while it was today, with no calculation until it was older, still gets its rows."""
    finished_at = int(datetime(2026, 1, 1, 12, tzinfo=timezone.utc).timestamp())

    assert metrics_days_since_last_calculation(finished_at, date(2026, 1, 4)) == [
        date(2025, 12, 31),
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert metrics_days_since_last_calculation(finished_at, date(2026, 1, 1)) == [date(2025, 12, 31)]


def test_month_aggregate_metrics_row_counts_its_users_once():
    """A user active on several days and components is one user of the month, as agno_metrics never counted it."""
    month_start = date(2026, 1, 1)
    per_owner: dict = {}
    for day in [date(2026, 1, 3), date(2026, 1, 9)]:
        add_metrics_month_totals(
            per_owner,
            calculate_date_component_metrics(
                day,
                [],
                [
                    _run("run-a", user_id="alice"),
                    _run("run-t", "team", "team-1", user_id="alice"),
                    _run("run-u", user_id=""),
                ],
                set(),
                [],
            ),
        )

    month = build_aggregate_metrics_month_rows(month_start, per_owner)[0]

    assert (month["root_runs_count"], month["agent_runs_count"], month["team_runs_count"]) == (6, 4, 2)
    assert month["users_count"] == 1


def test_day_without_rows_gets_a_total_row_of_zeros():
    """A day picked without traffic, such as a quiet yesterday, has no rows and an everyone row of zeros, so it is
    never rebuilt again once completed."""
    assert calculate_date_component_metrics(TARGET_DATE, [], [], set(), []) == []

    day = build_aggregate_metrics_row([], "daily", TARGET_DATE, completed=True)

    totals_fields = [field for field in METRICS_FIELDS if field not in ["sessions_count", "runs_count"]]
    assert {field: day[field] for field in totals_fields} == empty_metrics_totals(totals_fields)
    assert day["root_runs_count"] == 0
    assert day["max_duration_ms"] is None
    assert day["completed"] is True


def test_today_and_yesterday_are_still_open():
    """A run of yesterday can still be written today, so yesterday is completed a day later."""
    today = (datetime.now(timezone.utc) - timedelta(seconds=METRICS_DAY_GRACE_SECONDS)).date()

    assert metrics_day_completed(today) is False
    assert metrics_day_completed(today - timedelta(days=1)) is False
    assert metrics_day_completed(today - timedelta(days=2)) is True


def test_only_a_write_to_a_day_before_yesterday_reopens_it():
    """Today and yesterday are rebuilt by every refresh anyway, so a write to them reopens nothing."""
    today = datetime.now(timezone.utc).date()

    def created_at(day):
        return int(datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()) + 3600

    assert metrics_day_to_reopen(created_at(today)) is None
    assert metrics_day_to_reopen(created_at(today - timedelta(days=1))) is None
    assert metrics_day_to_reopen(created_at(today - timedelta(days=2))) == today - timedelta(days=2)
    assert metrics_day_to_reopen(None) is None


def test_a_day_a_write_stops_reopening_at_midnight_is_completed_after_the_grace(monkeypatch):
    """A write checked before midnight can commit after it, so the day it stops reopening is completed only
    METRICS_DAY_GRACE_SECONDS later, and a calculation in between rebuilds the day with that write."""
    midnight = datetime(2026, 11, 2, tzinfo=timezone.utc)
    day = midnight.date() - timedelta(days=2)

    class _FrozenDatetime(datetime):
        frozen = midnight + timedelta(seconds=1)

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return cls.frozen if tz is None else cls.frozen.astimezone(tz)

    monkeypatch.setattr("agno.db.utils.datetime", _FrozenDatetime)

    assert metrics_day_completed(day) is False
    assert metrics_day_to_reopen(int(midnight.timestamp()) - 86400 - 1) == day
    _FrozenDatetime.frozen = midnight + timedelta(seconds=METRICS_DAY_GRACE_SECONDS)
    assert metrics_day_completed(day) is True


def test_refresh_status_is_read_from_the_refreshes_row():
    """The row is running while its lock holds, then completed or failed; a refresh that never ran reads None."""
    assert metrics_refresh_status(None, 200) is None
    assert metrics_refresh_status(RUNNING_REFRESH, 200)["status"] == "running"
    failed = {**RUNNING_REFRESH, "locked_by": None, "locked_at": None, "status": "failed", "error": "boom"}
    assert metrics_refresh_status(failed, 200) == {
        "status": "failed",
        "started_at": 100,
        "finished_at": None,
        "error": "boom",
    }
    completed = {**RUNNING_REFRESH, "locked_by": None, "locked_at": None, "status": "completed", "finished_at": 150}
    assert metrics_refresh_status(completed, 200)["finished_at"] == 150


def test_refresh_whose_lock_went_stale_reads_failed():
    """A refresh whose process stopped before it finished reads failed, not the finish of the refresh before it."""
    status = metrics_refresh_status(RUNNING_REFRESH, 400)

    assert (status["status"], status["finished_at"]) == ("failed", None)
    assert status["error"] == METRICS_STOPPED_ERROR


def test_get_metrics_rows_keep_the_shape_of_agno_metrics():
    """Each user's day is one row with the old counts by type and token_metrics, and the unowned row counts no user;
    an aggregate metrics row reads in the same shape, the everyone row with no user."""

    def _totals(user_id, component_type, sessions_count, runs_count, total_tokens, created_at, updated_at):
        tokens = {**{field: 0 for field in METRICS_TOKEN_FIELDS}, "total_tokens": total_tokens, "cost": None}
        return _Row(
            date=TARGET_DATE,
            user_id=user_id,
            component_type=component_type,
            sessions_count=sessions_count,
            runs_count=runs_count,
            created_at=created_at,
            updated_at=updated_at,
            **tokens,
        )

    rows = [
        _totals("alice", "team", 1, 1, 30, 10, 20),
        _totals("alice", "agent", 0, 2, 12, 5, 25),
        _totals("", "agent", 1, 1, 0, 5, 5),
    ]
    model_rows = [
        _Row(date=TARGET_DATE, user_id="alice", model_id="gpt-5", model_provider="OpenAI", count=3, cost=None)
    ]

    unowned, alice = build_metrics_by_owner(rows, model_rows)

    assert (alice["user_id"], alice["users_count"], unowned["user_id"], unowned["users_count"]) == ("alice", 1, None, 0)
    assert (alice["team_runs_count"], alice["agent_runs_count"], alice["team_sessions_count"]) == (1, 2, 1)
    assert alice["token_metrics"]["total_tokens"] == 42
    assert alice["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3, "cost": None}]
    assert (alice["created_at"], alice["updated_at"]) == (5, 25)
    assert set(alice) >= {
        "id",
        "date",
        "aggregation_period",
        "completed",
        "agent_sessions_count",
        "workflow_runs_count",
    }

    everyone, alice_row = build_aggregate_metrics_rows(
        _day_rows([_run("run-1", user_id="alice", tokens={"total_tokens": 10})]), "daily", TARGET_DATE, False
    )

    everyone_metric, alice_metric = build_metrics_from_aggregate_metrics([everyone, alice_row])

    assert (everyone_metric["id"], everyone_metric["user_id"], everyone_metric["users_count"]) == (
        f"{TARGET_DATE.isoformat()}_daily",
        None,
        1,
    )
    assert (alice_metric["user_id"], alice_metric["agent_runs_count"]) == ("alice", 1)
    assert alice_metric["token_metrics"]["total_tokens"] == 10


def test_aggregate_metrics_row_is_written_when_new_changed_or_its_day_completes():
    """A new aggregate metrics row, one whose day had a row written or deleted, or the same numbers marked completed are
    written so its version moves and a later refresh starts after the day."""
    rows = _day_rows([_run("run-1")])
    total = build_aggregate_metrics_row(rows, "daily", TARGET_DATE, completed=False)
    stored = {**total, "version": 4, "created_at": 1, "updated_at": 1}

    assert aggregate_metrics_row_to_write(total, None, rows_changed=False) is total
    assert aggregate_metrics_row_to_write(total, stored, rows_changed=True) is total
    # The stamps and the version are not compared.
    assert aggregate_metrics_row_to_write(total, stored, rows_changed=False) is None

    completed = build_aggregate_metrics_row(rows, "daily", TARGET_DATE, completed=True)
    stored = {**completed, "completed": False, "version": 1}
    assert aggregate_metrics_row_to_write(completed, stored, rows_changed=False) is completed


# ---------------------------------------------------------------------------
# Month rows
# ---------------------------------------------------------------------------


def test_month_rows_total_the_days_of_the_month():
    """A month of completed days gets an aggregate metrics row per user and an everyone row, dated its first day."""
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

    per_owner: dict = {}
    add_metrics_month_totals(per_owner, stored_rows[:1])
    add_metrics_month_totals(per_owner, stored_rows[1:])
    month_rows = build_aggregate_metrics_month_rows(date(2026, 1, 1), per_owner)

    assert [(row["aggregation_period"], row["date"], row["user_id"]) for row in month_rows] == [
        ("monthly", date(2026, 1, 1), ""),
        ("monthly", date(2026, 1, 1), "alice"),
        ("monthly", date(2026, 1, 1), "bob"),
    ]
    month, alice, bob = month_rows
    assert (alice["agent_runs_count"], alice["team_runs_count"], bob["agent_runs_count"]) == (2, 1, 1)
    assert alice["total_duration_ms"] == 6000
    assert month["root_runs_count"] == 4
    assert month["max_duration_ms"] == 5000
    assert month["duration_buckets"] == {"le_1000": 1, "le_5000": 1}
    assert month["completed"] is True


def test_every_month_holding_a_rebuilt_day_is_rebuilt():
    """A rebuilt day changes its month, whenever the month ended, so each month is returned once."""
    days = [date(2025, 3, 10), date(2026, 1, 31), date(2026, 1, 3), date(2026, 2, 1)]

    assert get_months_to_calculate_metrics_for(days) == [date(2025, 3, 1), date(2026, 1, 1), date(2026, 2, 1)]
    assert get_months_to_calculate_metrics_for([]) == []


def test_month_end_and_the_full_months_wholly_inside_the_range():
    assert metrics_month_end(date(2026, 1, 1)) == date(2026, 1, 31)
    assert metrics_month_end(date(2024, 2, 1)) == date(2024, 2, 29)
    assert metrics_month_end(date(2025, 12, 1)) == date(2025, 12, 31)
    assert metrics_month_end(date(9999, 12, 1)) == date(9999, 12, 31)
    assert metrics_full_months(date(2026, 1, 1), date(2026, 3, 31)) == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]
    assert metrics_full_months(date(2026, 1, 2), date(2026, 3, 30)) == [date(2026, 2, 1)]
    assert metrics_full_months(date(2026, 1, 10), date(2026, 2, 20)) == []
    assert metrics_full_months(date(9999, 12, 1), date(9999, 12, 31)) == [date(9999, 12, 1)]


# ---------------------------------------------------------------------------
# Days of a read
# ---------------------------------------------------------------------------


def test_days_of_a_month_read_from_its_rows_are_not_read():
    """February is read from its month rows, so only the days of January and March are read; without month rows
    every day is read."""
    assert metrics_day_ranges(date(2026, 1, 30), date(2026, 3, 2), [date(2026, 2, 1)]) == [
        (date(2026, 1, 30), date(2026, 1, 31)),
        (date(2026, 3, 1), date(2026, 3, 2)),
    ]
    assert metrics_day_ranges(date(2026, 2, 1), date(2026, 2, 28), []) == [(date(2026, 2, 1), date(2026, 2, 28))]


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def test_merge_metrics_totals():
    """The totals of several dates merge into one set of totals, with every asked field present."""
    totals = [
        {"date": date(2026, 1, 1), "runs_count": 2, "max_duration_ms": 10, "model_metrics": {}},
        {
            "date": date(2026, 1, 2),
            "runs_count": 3,
            "max_duration_ms": 30,
            "duration_buckets": {"le_10": 1},
            "model_metrics": {"OpenAI": {"gpt-5": {"count": 3}}},
            "tool_metrics": {
                "": {
                    "search": {"count": 2, "failed_count": 1, "total_ms": 500, "max_ms": 400, "buckets": {"le_400": 2}}
                }
            },
        },
    ]
    fields = ["runs_count", "max_duration_ms", "duration_buckets", "model_metrics", "tool_metrics", "status_metrics"]

    assert merge_metrics_totals(totals, fields) == {
        "runs_count": 5,
        "max_duration_ms": 30,
        "duration_buckets": {"le_10": 1},
        "model_metrics": {"OpenAI": {"gpt-5": {"count": 3}}},
        "tool_metrics": {
            "": {"search": {"count": 2, "failed_count": 1, "total_ms": 500, "max_ms": 400, "buckets": {"le_400": 2}}}
        },
        "status_metrics": {},
    }
    assert merge_metrics_totals(
        [], ["sessions_count", "max_time_to_first_token_ms", "model_metrics", "tool_metrics"]
    ) == {
        "sessions_count": 0,
        "max_time_to_first_token_ms": None,
        "model_metrics": {},
        "tool_metrics": {},
    }
    assert merge_metrics_totals(
        [{"cost": None, "cost_runs_count": 0}, {"cost": 0.0123, "cost_runs_count": 1}, {"cost": None}],
        ["cost", "cost_runs_count"],
    ) == {"cost": 0.0123, "cost_runs_count": 1}
    assert merge_metrics_totals([{"cost": None, "cost_runs_count": 0}], ["cost", "cost_runs_count"]) == {
        "cost": None,
        "cost_runs_count": 0,
    }


def test_add_metrics_totals():
    """Counts and maps are summed, a maximum keeps the larger value, and models and tools of the same name add up; a
    missing value or a None maximum adds nothing."""
    total = {
        "total_duration_ms": 10,
        "max_duration_ms": 30,
        "duration_buckets": {"le_10": 1},
        "model_metrics": {"OpenAI": {"gpt-5": {"count": 1}}},
        "tool_metrics": {
            "": {"search": {"count": 2, "failed_count": 1, "total_ms": 500, "max_ms": 400, "buckets": {"le_400": 2}}}
        },
    }
    fields = ["total_duration_ms", "max_duration_ms", "duration_buckets", "model_metrics", "tool_metrics"]
    tool_metrics = total["tool_metrics"]

    add_metrics_totals(
        total,
        {
            "total_duration_ms": 5,
            "max_duration_ms": 20,
            "duration_buckets": {"le_10": 2, "le_12": 1},
            "model_metrics": {"OpenAI": {"gpt-5": {"count": 2}}, "Anthropic": {"claude": {"count": 1}}},
            "tool_metrics": {
                "": {
                    "search": {"count": 1, "failed_count": 0, "total_ms": 900, "max_ms": 900, "buckets": {"le_1000": 1}}
                },
                "github": {
                    "create_issue": {"count": 1, "failed_count": 0, "total_ms": 0, "max_ms": None, "buckets": {}}
                },
            },
        },
        fields,
    )

    assert total == {
        "total_duration_ms": 15,
        "max_duration_ms": 30,
        "duration_buckets": {"le_10": 3, "le_12": 1},
        "model_metrics": {"OpenAI": {"gpt-5": {"count": 3}}, "Anthropic": {"claude": {"count": 1}}},
        "tool_metrics": {
            "": {
                "search": {
                    "count": 3,
                    "failed_count": 1,
                    "total_ms": 1400,
                    "max_ms": 900,
                    "buckets": {"le_400": 2, "le_1000": 1},
                }
            },
            "github": {"create_issue": {"count": 1, "failed_count": 0, "total_ms": 0, "max_ms": None, "buckets": {}}},
        },
    }

    partial = {"runs_count": 1, "max_duration_ms": None}
    add_metrics_totals(partial, {"max_duration_ms": None}, ["runs_count", "max_duration_ms"])
    assert partial == {"runs_count": 1, "max_duration_ms": None}
    # Adding up never changes the maps added into
    assert tool_metrics[""]["search"]["count"] == 2


def test_resolve_fields_defaults_to_everything_and_rejects_unknown():
    assert resolve_metrics_fields(None) == list(METRICS_READ_FIELDS)
    assert {"sessions_count", "total_tokens", "status_metrics", "duration_buckets", "model_metrics"} <= set(
        METRICS_READ_FIELDS
    )
    # The audio token counts are read one by one from token_details
    assert {"audio_input_tokens", "audio_output_tokens", "audio_total_tokens"} <= set(METRICS_READ_FIELDS)
    assert "token_details" not in METRICS_READ_FIELDS
    assert resolve_metrics_fields(["duration_buckets", "root_runs_count"]) == ["duration_buckets", "root_runs_count"]
    with pytest.raises(ValueError, match="token_metrics"):
        resolve_metrics_fields(["root_runs_count", "token_metrics"])


# ---------------------------------------------------------------------------
# Postgres row shaping
# ---------------------------------------------------------------------------


def test_build_component_metrics_run_rebuilds_the_stored_run_shape():
    """The columns the runs query picks are put back into the run_data shape the rollup reads."""
    run = build_component_metrics_run(
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
            tools=[_tool_call("search", duration=0.4)],
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
        "tools": [_tool_call("search", duration=0.4)],
    }
    row = _only_row(runs=[run])
    assert row["model_calls_count"] == 2
    assert row["tool_metrics"] == {
        "": {"search": {"count": 1, "failed_count": 0, "total_ms": 400, "max_ms": 400, "buckets": {"le_400": 1}}}
    }

    # No call durations store no messages
    run = build_component_metrics_run(
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
            tools=None,
            nested_runs=None,
        )
    )

    assert run["run_data"]["messages"] == []
    assert _only_row(runs=[run])["runs_count"] == 1


def test_build_component_metrics_run_nests_the_nested_runs_again():
    """The nested runs the runs query reads flat are put back inside the run each one is nested in."""

    def nested_row(depth, key, run_id, call_durations=(), tools=None, **ids):
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
            "tools": tools,
        }

    run = build_component_metrics_run(
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
            tools=None,
            nested_runs=[
                nested_row(1, "step_executor_runs", "team-run", team_id="team-1"),
                nested_row(
                    2,
                    "member_responses",
                    "member-run",
                    call_durations=[0.2],
                    tools=[_tool_call("search", error=True)],
                    agent_id="agent-1",
                ),
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
    assert metrics_nested_run_ids([run]) == {"team-run", "member-run", "unnamed-run", "agent-run", "other-run"}
    row = _only_row(runs=[run])
    assert row["input_tokens"] == 50
    assert row["model_calls_count"] == 1
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 5}}}
    # A nested run's tool call counts on the row of the run it is nested in, untimed when it recorded no duration
    assert row["tool_metrics"] == {
        "": {"search": {"count": 1, "failed_count": 1, "total_ms": 0, "max_ms": None, "buckets": {}}}
    }


def test_build_component_metrics_totals_assembles_each_query():
    """The totals query fills the columns; the count map, model and tool queries fill the maps, the model list and
    the tools."""
    fields = [
        "runs_count",
        "total_tokens",
        "max_duration_ms",
        "max_time_to_first_token_ms",
        "duration_buckets",
        "model_metrics",
        "tool_metrics",
    ]
    aggregate_metrics_row = {
        "date": date(2026, 1, 1),
        "updated_at": 10,
        "runs_count": 3,
        "total_tokens": 12,
        "max_duration_ms": 900,
        "max_time_to_first_token_ms": None,
    }
    rows_by_query = {
        "totals": [
            _Row(**aggregate_metrics_row),
            _Row(**{**aggregate_metrics_row, "date": date(2025, 12, 31), "updated_at": 4}),
        ],
        "count_maps": [_Row(date=date(2026, 1, 1), field="duration_buckets", key="le_1000", count=3)],
        "model_metrics": [
            _Row(date=date(2026, 1, 1), model_id="gpt-5-mini", model_provider="", count=1, cost=None),
            _Row(date=date(2026, 1, 1), model_id="gpt-5", model_provider="OpenAI", count=3, cost=None),
        ],
        "tool_metrics": [
            _Row(
                date=date(2026, 1, 1),
                tool_metrics={
                    "": {
                        "search": {
                            "count": 2,
                            "failed_count": 1,
                            "total_ms": 500,
                            "max_ms": 400,
                            "buckets": {"le_400": 2},
                        }
                    }
                },
            ),
            _Row(
                date=date(2026, 1, 1),
                tool_metrics={
                    "": {
                        "search": {
                            "count": 1,
                            "failed_count": 0,
                            "total_ms": 900,
                            "max_ms": 900,
                            "buckets": {"le_1000": 1},
                        }
                    }
                },
            ),
        ],
    }

    totals, latest = build_component_metrics_totals(fields, rows_by_query)

    assert latest == 10
    assert [total["date"] for total in totals] == [date(2025, 12, 31), date(2026, 1, 1)]
    assert totals[1] == {
        "date": date(2026, 1, 1),
        "runs_count": 3,
        "total_tokens": 12,
        "max_duration_ms": 900,
        "max_time_to_first_token_ms": None,
        "duration_buckets": {"le_1000": 3},
        "model_metrics": {"OpenAI": {"gpt-5": {"count": 3}}, "": {"gpt-5-mini": {"count": 1}}},
        "tool_metrics": {
            "": {
                "search": {
                    "count": 3,
                    "failed_count": 1,
                    "total_ms": 1400,
                    "max_ms": 900,
                    "buckets": {"le_400": 2, "le_1000": 1},
                }
            }
        },
    }
    assert totals[0]["duration_buckets"] == {}
    assert totals[0]["model_metrics"] == {}
    assert totals[0]["tool_metrics"] == {}


def test_build_component_metrics_totals_keeps_each_cost():
    """The totals query fills the cost and the runs that reported one; the model query fills each model's cost."""
    fields = ["runs_count", "cost", "cost_runs_count", "model_metrics"]
    aggregate_metrics_row = {
        "date": date(2026, 1, 1),
        "updated_at": 10,
        "runs_count": 3,
        "cost": 0.02,
        "cost_runs_count": 2,
    }
    rows_by_query = {
        "totals": [
            _Row(**aggregate_metrics_row),
            _Row(**{**aggregate_metrics_row, "date": date(2025, 12, 31), "cost": None, "cost_runs_count": 0}),
        ],
        "model_metrics": [
            _Row(date=date(2026, 1, 1), model_id="gpt-5-mini", model_provider="", count=1, cost=None),
            _Row(date=date(2026, 1, 1), model_id="gpt-5", model_provider="OpenAI", count=3, cost=0.01),
        ],
    }

    totals, latest = build_component_metrics_totals(fields, rows_by_query)

    assert latest == 10
    assert totals[1] == {
        "date": date(2026, 1, 1),
        "runs_count": 3,
        "cost": 0.02,
        "cost_runs_count": 2,
        "model_metrics": {"OpenAI": {"gpt-5": {"count": 3, "cost": 0.01}}, "": {"gpt-5-mini": {"count": 1}}},
    }
    assert totals[0]["cost"] is None
    assert totals[0]["cost_runs_count"] == 0
    assert list_metrics_models(totals[1]["model_metrics"]) == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3, "cost": 0.01},
        {"model_id": "gpt-5-mini", "model_provider": "", "count": 1, "cost": None},
    ]


# ---------------------------------------------------------------------------
# Refresh on read
# ---------------------------------------------------------------------------


def test_a_read_never_calculates_when_calculation_is_turned_off(monkeypatch):
    """The metrics_calculation_enabled switch of AgentOS also stops the refresh on read of a database no AgentOS
    runs."""
    monkeypatch.setenv("METRICS_CALCULATION_ENABLED", "false")
    db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost/ai")

    with patch.object(PostgresDb, "_get_table", return_value=None):
        with patch.object(PostgresDb, "calculate_metrics_dates") as calculate:
            db.get_metrics()

    calculate.assert_not_called()
