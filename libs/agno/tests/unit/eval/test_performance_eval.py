"""Unit tests for PerformanceEval"""

from unittest.mock import patch

from agno.db.in_memory import InMemoryDb
from agno.eval.performance import PerformanceEval


def _perf_eval(db: InMemoryDb) -> PerformanceEval:
    """Build a minimal PerformanceEval that logs to the given db without telemetry."""
    return PerformanceEval(
        func=lambda: None,
        db=db,
        telemetry=False,
        warmup_runs=0,
        num_iterations=1,
    )


def test_run_logs_distinct_run_id_per_execution():
    """Running the same eval instance twice should store two distinct run_ids."""
    db = InMemoryDb()
    evaluation = _perf_eval(db)

    evaluation.run()
    evaluation.run()

    runs = db.get_eval_runs()
    assert len(runs) == 2
    assert runs[0].run_id != runs[1].run_id
    # The per-execution run_id must not reuse the stable eval definition id.
    assert runs[0].run_id != evaluation.eval_id
    assert runs[1].run_id != evaluation.eval_id


def test_db_and_telemetry_share_same_run_id():
    """A single execution must log the same run_id to both the DB and telemetry."""
    db = InMemoryDb()
    evaluation = PerformanceEval(
        func=lambda: None,
        db=db,
        telemetry=True,
        warmup_runs=0,
        num_iterations=1,
    )

    with patch("agno.api.evals.create_eval_run_telemetry") as mock_create:
        evaluation.run()

    telemetry_run_id = mock_create.call_args[1]["eval_run"].run_id
    db_run_id = db.get_eval_runs()[0].run_id

    assert telemetry_run_id == db_run_id
    assert telemetry_run_id != evaluation.eval_id


async def test_arun_logs_distinct_run_id_per_execution():
    """Async path should also store a distinct run_id per execution."""

    async def sample_func():
        return None

    db = InMemoryDb()
    evaluation = PerformanceEval(
        func=sample_func,
        db=db,
        telemetry=False,
        warmup_runs=0,
        num_iterations=1,
    )

    await evaluation.arun()
    await evaluation.arun()

    runs = db.get_eval_runs()
    assert len(runs) == 2
    assert runs[0].run_id != runs[1].run_id
    assert runs[0].run_id != evaluation.eval_id
    assert runs[1].run_id != evaluation.eval_id
