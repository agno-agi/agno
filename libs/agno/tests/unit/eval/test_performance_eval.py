"""Unit tests for PerformanceEval and PerformanceResult"""

from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.eval.performance import PerformanceEval, PerformanceResult

# ---------------------------------------------------------------------------
# p95 percentile for small samples
# ---------------------------------------------------------------------------


def test_single_sample_p95_matches_sample():
    result = PerformanceResult(run_id="run-1", run_times=[1.0], memory_usages=[10.0])
    assert result.p95_run_time == 1.0
    assert result.p95_memory_usage == 10.0


def test_small_sample_p95_stays_within_observed_range():
    result = PerformanceResult(run_id="run-1", run_times=[1.0, 2.0], memory_usages=[10.0, 20.0])
    assert result.min_run_time <= result.p95_run_time <= result.max_run_time
    assert result.min_memory_usage <= result.p95_memory_usage <= result.max_memory_usage


def test_identical_samples_p95_equals_value():
    result = PerformanceResult(run_id="run-1", run_times=[5.0, 5.0, 5.0])
    assert result.p95_run_time == 5.0


def test_empty_run_times_p95_is_zero():
    result = PerformanceResult(run_id="run-1", run_times=[], memory_usages=[])
    assert result.p95_run_time == 0
    assert result.p95_memory_usage == 0


# ---------------------------------------------------------------------------
# run_id is per execution: one run() call, one row, one id
# ---------------------------------------------------------------------------


def _perf_eval(db: InMemoryDb, telemetry: bool = False) -> PerformanceEval:
    """Build a minimal PerformanceEval that logs to the given db."""
    return PerformanceEval(
        func=lambda: None,
        db=db,
        telemetry=telemetry,
        warmup_runs=0,
        num_iterations=1,
        show_spinner=False,
    )


async def test_arun_logs_distinct_run_id_per_execution():
    """Async path also stores a distinct run_id per execution."""

    async def sample_func():
        return None

    db = InMemoryDb()
    evaluation = PerformanceEval(
        func=sample_func,
        db=db,
        telemetry=False,
        warmup_runs=0,
        num_iterations=1,
        show_spinner=False,
    )

    first = await evaluation.arun()
    second = await evaluation.arun()

    runs = db.get_eval_runs()
    assert len(runs) == 2
    assert first.run_id != second.run_id
    assert {run.run_id for run in runs} == {first.run_id, second.run_id}


def test_positional_construction_binds_run_id_first():
    """run_id is deliberately the first field, so a pre-3.0 positional
    PerformanceResult(run_times, memory_usages) now binds run_times into run_id and shifts
    the rest. Keyword construction is the documented form; this pins the order so it is
    never reshuffled by accident."""
    result = PerformanceResult("run-1", [1.0, 3.0], [10.0, 30.0])

    assert result.run_id == "run-1"
    assert result.run_times == [1.0, 3.0]
    assert result.memory_usages == [10.0, 30.0]


def test_rerun_stores_a_row_and_a_file_per_run(tmp_path):
    """run_id is the evals table primary key and create_eval_run is a plain insert, so a reused
    id made the second write raise and be swallowed. The file sink is keyed the same way, so one
    rerun is enough to cover both. InMemoryDb has no uniqueness and cannot show the failure."""
    db = SqliteDb(db_file=str(tmp_path / "evals.db"))
    evaluation = PerformanceEval(
        func=lambda: None,
        db=db,
        telemetry=False,
        warmup_runs=0,
        num_iterations=1,
        show_spinner=False,
        file_path_to_save_results=str(tmp_path / "{run_id}.json"),
    )

    first = evaluation.run()
    second = evaluation.run()

    assert {run.run_id for run in db.get_eval_runs()} == {first.run_id, second.run_id}
    assert (tmp_path / f"{first.run_id}.json").exists()
    assert (tmp_path / f"{second.run_id}.json").exists()
