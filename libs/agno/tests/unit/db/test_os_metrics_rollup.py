"""Unit tests for the OS metrics rollup helpers.

``calculate_date_os_metrics`` turns one day's stored sessions and runs into one row per owner and agent, team or
workflow. The helpers around it key each row by owner and component, decide which rebuilt rows to write, and read a percentile
back out of the bucket counts.
"""

import statistics
from datetime import date

import pytest

from agno.db.postgres.utils import build_os_metrics_run, build_os_metrics_totals
from agno.db.utils import (
    _OS_METRICS_BUCKET_BOUNDS_MS,
    _OS_METRICS_TOKEN_FIELDS,
    OS_METRICS_FIXED_KEYS,
    _os_metrics_row_key,
    calculate_date_os_metrics,
    merge_os_metrics_json,
    merge_os_model_metrics,
    os_metrics_nested_run_ids,
    os_metrics_percentile,
    os_metrics_rows_to_write,
    resolve_os_metrics_fields,
)
from agno.run.base import RunStatus

# A past day, so every row it builds is complete
TARGET_DATE = date(2026, 1, 1)

COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value
REGENERATED = RunStatus.regenerated.value

# The keys that differ between two builds of the same day
EPHEMERAL = {"id", "created_at", "updated_at"}


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
    """Build the day's rows keyed by (user_id, agent_id, team_id, workflow_id)."""
    return {
        (row["user_id"], row["agent_id"], row["team_id"], row["workflow_id"]): row
        for row in calculate_date_os_metrics(TARGET_DATE, list(sessions), list(runs), set(stored_run_ids))
    }


def _only_row(sessions=(), runs=()):
    rows = list(_rows(sessions, runs).values())
    assert len(rows) == 1
    return rows[0]


def _stable(row):
    return {key: value for key, value in row.items() if key not in EPHEMERAL}


# Rows: one per owner and component


def test_one_row_per_user_and_component():
    """Sessions and runs of one owner for one component share a row; any other pair gets its own."""
    rows = _rows(
        sessions=[_session("alice"), _session("alice"), _session("bob"), _session("alice", "team", "team-1")],
        runs=[_run("run-1", user_id="alice"), _run("run-2", user_id="alice")],
    )

    assert set(rows) == {("alice", "agent-1", "", ""), ("bob", "agent-1", "", ""), ("alice", "", "team-1", "")}
    assert rows[("alice", "agent-1", "", "")]["sessions_count"] == 2
    assert rows[("alice", "agent-1", "", "")]["runs_count"] == 2
    assert rows[("bob", "agent-1", "", "")]["runs_count"] == 0


def test_session_without_user_lands_under_empty_string():
    """A session with no user_id is counted under the "" owner."""
    row = _only_row(sessions=[_session(None)])

    assert row["user_id"] == ""
    assert row["sessions_count"] == 1


def test_only_the_id_matching_the_component_type_is_set():
    """A team session that also names an agent is counted under the team alone."""
    session = {**_session("alice", "team", "team-1"), "agent_id": "agent-1"}
    row = _only_row(sessions=[session])

    assert (row["agent_id"], row["team_id"], row["workflow_id"]) == ("", "team-1", "")


def test_row_shape():
    """A row carries the columns the upsert expects, keyed by its owner and component within the day."""
    row = _only_row(runs=[_run()])

    assert _os_metrics_row_key(row) == ("alice", "agent-1", "", "")
    assert len(row["id"]) == 36
    assert row["date"] == TARGET_DATE
    assert row["aggregation_period"] == "daily"
    assert row["completed"] is True
    assert row["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "agent_id": "agent-1", "count": 1}
    ]


# Runs


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
        ("alice", "agent-1", "", ""): 1,
        ("alice", "", "team-1", ""): 1,
        ("bob", "agent-1", "", ""): 1,
    }


def test_team_member_run_counts_under_the_member_agent():
    """A member's run is stored as its own agent run and counted under that agent, not the team."""
    rows = _rows(
        runs=[
            _run("team-run", run_type="team", component_id="team-1"),
            _run("member-run", component_id="member-1", parent_run_id="team-run"),
        ]
    )

    assert rows[("alice", "", "team-1", "")]["runs_count"] == 1
    assert rows[("alice", "member-1", "", "")]["runs_count"] == 1


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
    assert row["token_metrics"] == {"input_tokens": 100}
    assert row["duration_metrics"]["model_calls_count"] == 1
    assert "duration_runs_count" not in row["duration_metrics"]
    assert row["model_metrics"][0]["count"] == 2


def test_nested_team_members_are_walked_from_member_responses():
    """A member of a team inside a team is stored nowhere else, so its calls come from the inner team's members."""
    inner_member = _model_call(tokens={"input_tokens": 1}, agent_id="inner-a", run_id="inner-a-run")
    inner_team = _model_call(tokens={"input_tokens": 10}, team_id="inner-team", member_responses=[inner_member])
    runs = [
        _run("outer-run", run_type="team", component_id="outer-team", tokens={"input_tokens": 100}),
        _run(
            "inner-run",
            run_type="team",
            component_id="inner-team",
            parent_run_id="outer-run",
            tokens={"input_tokens": 10},
            member_responses=inner_team["member_responses"],
        ),
    ]
    rows = _rows(runs=runs)

    assert rows[("alice", "", "inner-team", "")]["token_metrics"] == {"input_tokens": 11}
    assert [m["agent_id"] for m in rows[("alice", "", "inner-team", "")]["model_metrics"] if "agent_id" in m] == [
        "inner-a"
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

    assert rows[("alice", "", "team-1", "")]["token_metrics"] == {}
    assert rows[("alice", "member-1", "", "")]["token_metrics"] == {"input_tokens": 1}


def test_member_stored_on_another_day_is_not_walked():
    """A member that ended after midnight is a row of the next day: the parent's day skips it, the next day counts it."""
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

    assert parent_day[("alice", "", "team-1", "")]["token_metrics"] == {"input_tokens": 50}
    assert ("alice", "member-1", "", "") not in parent_day


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

    assert row["token_metrics"] == {"input_tokens": 11}


def test_history_messages_are_not_model_calls():
    """An assistant message carried over from an earlier run keeps that run's duration and is not counted."""
    row = _only_row(runs=[_run(call_durations=(0.2, 0.3), history_durations=(0.9,))])

    assert row["duration_metrics"]["model_calls_count"] == 2
    assert row["duration_metrics"]["total_model_call_ms"] == 500


def test_status_metrics_keyed_by_status():
    """status_metrics counts runs by their stored status."""
    row = _only_row(runs=[_run("run-1"), _run("run-2"), _run("run-3", status=ERROR)])

    assert row["status_metrics"] == {COMPLETED: 2, ERROR: 1}


def test_error_run_adds_no_duration():
    """Only a completed run's duration and time to first token are counted."""
    row = _only_row(runs=[_run("run-1", status=ERROR, duration=2.0, time_to_first_token=0.5)])

    assert row["runs_count"] == 1
    assert row["duration_metrics"] == {}


# Tokens


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

    assert row["token_metrics"] == {"input_tokens": 1111}


def test_zero_token_keys_are_not_stored():
    """A token count of zero is left out of token_metrics rather than stored as 0."""
    row = _only_row(runs=[_run(tokens={"input_tokens": 5, "output_tokens": 0, "reasoning_tokens": 0})])

    assert row["token_metrics"] == {"input_tokens": 5}


# Durations


def test_duration_metrics_count_total_max():
    """duration_metrics keeps count, total and max in milliseconds for each timing."""
    row = _only_row(
        runs=[
            _run("run-1", duration=1.0, time_to_first_token=0.2, call_durations=(0.3, 0.7)),
            _run("run-2", duration=3.0, time_to_first_token=0.1, call_durations=(0.5,)),
        ]
    )
    metrics = row["duration_metrics"]

    assert metrics["duration_runs_count"] == 2
    assert metrics["total_duration_ms"] == 4000
    assert metrics["max_duration_ms"] == 3000
    assert metrics["time_to_first_token_runs_count"] == 2
    assert metrics["total_time_to_first_token_ms"] == 300
    assert metrics["max_time_to_first_token_ms"] == 200
    assert metrics["model_calls_count"] == 3
    assert metrics["total_model_call_ms"] == 1500
    assert metrics["max_model_call_ms"] == 700


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

    assert row["duration_metrics"]["duration_ms_buckets"] == {bucket: 1}


def test_bucket_bounds():
    """The bounds run 10, 12, 15, ... 80 through six decades, ending at 8,000,000 ms."""
    assert _OS_METRICS_BUCKET_BOUNDS_MS[:10] == (10, 12, 15, 20, 25, 30, 40, 50, 60, 80)
    assert _OS_METRICS_BUCKET_BOUNDS_MS[-1] == 8_000_000
    assert list(_OS_METRICS_BUCKET_BOUNDS_MS) == sorted(_OS_METRICS_BUCKET_BOUNDS_MS)


def test_every_timing_gets_its_own_buckets():
    """Duration, time to first token and model calls are each bucketed apart."""
    row = _only_row(runs=[_run(duration=0.01, time_to_first_token=0.02, call_durations=(0.03, 0.03))])
    metrics = row["duration_metrics"]

    assert metrics["duration_ms_buckets"] == {"le_10": 1}
    assert metrics["time_to_first_token_ms_buckets"] == {"le_20": 1}
    assert metrics["model_call_ms_buckets"] == {"le_30": 2}


# Models


def test_model_entry_carries_caller_and_run_count():
    """A model entry names its model, provider and caller, and counts the runs it served."""
    row = _only_row(runs=[_run("run-1", call_durations=(0.3, 0.7)), _run("run-2", call_durations=(0.5,))])

    assert row["model_metrics"] == [
        {
            "model_id": "gpt-5",
            "model_provider": "OpenAI",
            "agent_id": "agent-1",
            "count": 2,
        }
    ]


def test_workflow_step_model_carries_the_step_agent():
    """A workflow step's model call is credited to the step's agent; a step naming none falls back to the workflow."""
    named_step = _model_call(agent_id="step-agent")
    unnamed_step = _model_call(model="gpt-5-mini")
    row = _only_row(
        runs=[_run(run_type="workflow", component_id="wf-1", model=None, step_executor_runs=[named_step, unnamed_step])]
    )

    assert row["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "agent_id": "step-agent", "count": 1},
        {"model_id": "gpt-5-mini", "model_provider": "OpenAI", "workflow_id": "wf-1", "count": 1},
    ]


def test_model_call_without_details_is_not_a_model_entry():
    """A model that failed before answering reports no details and is not counted as serving the run."""
    row = _only_row(runs=[_run(details=False, tokens={"input_tokens": 3})])

    assert row["model_metrics"] == []
    assert row["token_metrics"] == {"input_tokens": 3}


def test_model_metrics_sorted_deterministically():
    """model_metrics is sorted by model, provider and caller whatever order the runs arrived in."""
    runs = [
        _run("run-1", model="gpt-5", provider="OpenAI"),
        _run("run-2", model="claude", provider="Anthropic"),
        _run("run-3", model="claude", provider="Anthropic", component_id="agent-0"),
    ]
    forward = _rows(runs=runs)
    backward = _rows(runs=list(reversed(runs)))

    ids = [(m["model_id"], m["model_provider"]) for m in forward[("alice", "agent-1", "", "")]["model_metrics"]]
    assert ids == [("claude", "Anthropic"), ("gpt-5", "OpenAI")]
    for key, row in forward.items():
        assert row["model_metrics"] == backward[key]["model_metrics"]


# Ids and rewrite


def test_rebuild_yields_identical_rows():
    """Two builds of the same inputs differ only in their timestamps."""
    runs = [_run("run-1", duration=1.0, call_durations=(0.2,)), _run("run-2", status=ERROR)]
    first = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())
    second = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())

    assert [_stable(row) for row in first] == [_stable(row) for row in second]


def test_unchanged_rebuild_writes_nothing():
    """A rebuild equal to the stored rows returns no rows to write and no stale ids."""
    runs = [_run("run-1", duration=1.0, call_durations=(0.2,))]
    stored = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())
    rebuilt = calculate_date_os_metrics(TARGET_DATE, [_session()], runs, set())

    assert os_metrics_rows_to_write(rebuilt, stored) == ([], [])


def test_changed_number_is_written():
    """A row whose numbers moved is returned to be written."""
    stored = calculate_date_os_metrics(TARGET_DATE, [], [_run("run-1")], set())
    rebuilt = calculate_date_os_metrics(TARGET_DATE, [], [_run("run-1"), _run("run-2")], set())

    changed, stale = os_metrics_rows_to_write(rebuilt, stored)

    assert [_os_metrics_row_key(row) for row in changed] == [_os_metrics_row_key(stored[0])]
    assert changed[0]["runs_count"] == 2
    assert stale == []


def test_new_row_is_written():
    """A row the stored set does not have is returned to be written."""
    rebuilt = calculate_date_os_metrics(TARGET_DATE, [], [_run("run-1")], set())

    changed, stale = os_metrics_rows_to_write(rebuilt, [])

    assert changed == rebuilt
    assert stale == []


def test_stored_row_missing_from_rebuild_is_stale():
    """A stored row the rebuild no longer produces is returned by id for deletion."""
    stored = calculate_date_os_metrics(
        TARGET_DATE, [], [_run("run-1", user_id="alice"), _run("run-2", user_id="bob")], set()
    )
    rebuilt = calculate_date_os_metrics(TARGET_DATE, [], [_run("run-1", user_id="alice")], set())
    bob_id = next(row["id"] for row in stored if row["user_id"] == "bob")

    changed, stale = os_metrics_rows_to_write(rebuilt, stored)

    assert changed == []
    assert stale == [bob_id]


def test_only_read_rows_can_be_stale():
    """A row that was not read is never returned as stale, so a row written since is kept."""
    rebuilt = calculate_date_os_metrics(TARGET_DATE, [], [_run("run-1", user_id="alice")], set())
    read = calculate_date_os_metrics(TARGET_DATE, [], [_run("run-1", user_id="alice")], set())

    changed, stale = os_metrics_rows_to_write(rebuilt, read)

    assert (changed, stale) == ([], [])
    assert set(stale) <= {row["id"] for row in read}


# Totals


def test_merge_os_metrics_json():
    """A max_ key keeps the larger value, a nested object merges key by key, every other key is summed."""
    total = {"total_duration_ms": 10, "max_duration_ms": 30, "duration_ms_buckets": {"le_10": 1}}

    merge_os_metrics_json(
        total,
        {"total_duration_ms": 5, "max_duration_ms": 20, "duration_ms_buckets": {"le_10": 2, "le_12": 1}, "new": 1},
    )

    assert total == {
        "total_duration_ms": 15,
        "max_duration_ms": 30,
        "duration_ms_buckets": {"le_10": 3, "le_12": 1},
        "new": 1,
    }


def test_merge_os_metrics_json_tolerates_none():
    """A missing object or a None value adds nothing."""
    total = {"a": 1}

    merge_os_metrics_json(total, None)
    merge_os_metrics_json(total, {"a": None, "max_b": None})

    assert total == {"a": 1, "max_b": 0}


def test_merge_os_model_metrics():
    """Entries of the same model and caller add up their counts; a different caller is its own entry."""
    target = [{"model_id": "gpt-5", "model_provider": "OpenAI", "agent_id": "a", "count": 1}]

    merge_os_model_metrics(
        target,
        [
            {
                "model_id": "gpt-5",
                "model_provider": "OpenAI",
                "agent_id": "a",
                "count": 2,
            },
            {"model_id": "gpt-5", "model_provider": "OpenAI", "team_id": "t", "count": 1},
        ],
    )

    assert target == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "agent_id": "a", "count": 3},
        {"model_id": "gpt-5", "model_provider": "OpenAI", "team_id": "t", "count": 1},
    ]


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
    buckets = _only_row(runs=runs)["duration_metrics"]["duration_ms_buckets"]
    true_median = statistics.median(milliseconds)
    upper = next(bound for bound in _OS_METRICS_BUCKET_BOUNDS_MS if true_median <= bound)
    lower = max((bound for bound in _OS_METRICS_BUCKET_BOUNDS_MS if bound < upper), default=0)

    assert sum(buckets.values()) == 200
    assert abs(os_metrics_percentile(buckets, 0.5) - true_median) <= upper - lower


# Field validation


def test_resolve_fields_defaults_to_everything():
    assert resolve_os_metrics_fields(None) == [
        "sessions_count",
        "runs_count",
        "status_metrics",
        "token_metrics",
        "duration_metrics",
        "model_metrics",
        "duration_buckets",
    ]


def test_resolve_fields_accepts_buckets_and_rejects_unknown():
    assert resolve_os_metrics_fields(["duration_buckets", "runs_count"]) == ["duration_buckets", "runs_count"]
    with pytest.raises(ValueError, match="nope"):
        resolve_os_metrics_fields(["runs_count", "nope"])


def test_fixed_keys_cover_every_status():
    """status_metrics can be totaled by every RunStatus value; the token and duration keys match the row."""
    assert set(OS_METRICS_FIXED_KEYS["status_metrics"]) == {status.value for status in RunStatus}
    assert OS_METRICS_FIXED_KEYS["token_metrics"] == _OS_METRICS_TOKEN_FIELDS
    assert "max_duration_ms" in OS_METRICS_FIXED_KEYS["duration_metrics"]


# Postgres row shaping


class _Row:
    """A SQLAlchemy result row: attributes plus a _mapping."""

    def __init__(self, **values):
        self._mapping = values
        for name, value in values.items():
            setattr(self, name, value)


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
            parent_run_id=None,
            status=COMPLETED,
            metrics={"duration": 1.0, "details": {"gpt-5": {}}},
            model="gpt-5",
            model_provider="OpenAI",
            call_durations=[0.2, 0.3],
            step_executor_runs=None,
            member_responses=None,
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
        "step_executor_runs": None,
        "member_responses": None,
    }
    row = _only_row(runs=[run])
    assert row["duration_metrics"]["model_calls_count"] == 2


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
            step_executor_runs=None,
            member_responses=None,
        )
    )

    assert run["run_data"]["messages"] == []
    assert _only_row(runs=[run])["runs_count"] == 1


def test_build_os_metrics_totals_assembles_each_query():
    """The totals query fills the columns; the bucket and model queries fill the unpacked keys."""
    fields = ["runs_count", "token_metrics", "duration_metrics", "duration_buckets", "model_metrics"]
    token_metrics = {key: None for key in OS_METRICS_FIXED_KEYS["token_metrics"]}
    token_metrics["input_tokens"] = 12
    duration_metrics = {key: None for key in OS_METRICS_FIXED_KEYS["duration_metrics"]}
    duration_metrics["max_duration_ms"] = 900
    totals_row = {
        "date": date(2026, 1, 1),
        "updated_at": 10,
        "runs_count": 3,
        "token_metrics": token_metrics,
        "duration_metrics": duration_metrics,
    }
    rows_by_query = {
        "totals": [_Row(**totals_row), _Row(**{**totals_row, "date": date(2025, 12, 31), "updated_at": 4})],
        "duration_buckets": [
            _Row(date=date(2026, 1, 1), bucket_field="duration_ms_buckets", bucket="le_1000", count=3)
        ],
        "model_metrics": [
            _Row(
                date=date(2026, 1, 1),
                model_id="gpt-5",
                model_provider="OpenAI",
                model_agent_id="agent-1",
                model_team_id="",
                model_workflow_id="",
                count=3,
            ),
            _Row(
                date=date(2026, 1, 1),
                model_id="gpt-5-mini",
                model_provider="",
                model_agent_id="",
                model_team_id="",
                model_workflow_id="wf-1",
                count=1,
            ),
        ],
    }

    totals, latest = build_os_metrics_totals(fields, rows_by_query)

    assert latest == 10
    assert [total["date"] for total in totals] == [date(2025, 12, 31), date(2026, 1, 1)]
    assert totals[1] == {
        "date": date(2026, 1, 1),
        "runs_count": 3,
        "token_metrics": {"input_tokens": 12},
        "duration_metrics": {"max_duration_ms": 900},
        "duration_buckets": {"duration_ms_buckets": {"le_1000": 3}},
        "model_metrics": [
            {"model_id": "gpt-5", "model_provider": "OpenAI", "agent_id": "agent-1", "count": 3},
            {"model_id": "gpt-5-mini", "model_provider": "", "workflow_id": "wf-1", "count": 1},
        ],
    }
    assert totals[0]["duration_buckets"] == {}
    assert totals[0]["model_metrics"] == []
