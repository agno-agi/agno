"""Unit tests for AccuracyEval"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.eval.accuracy import AccuracyAgentResponse, AccuracyEval
from agno.run.agent import RunOutput
from agno.team import Team


def _mock_evaluator(eval_instance: AccuracyEval, score: int = 8):
    """Helper to mock the evaluator agent to return a numeric accuracy score."""
    evaluator = eval_instance.get_evaluator_agent()
    evaluator.model = MagicMock()
    mock_response = AccuracyAgentResponse(accuracy_score=score, accuracy_reason="Mocked evaluation response.")
    mock_output = RunOutput(content=mock_response)
    evaluator.run = MagicMock(return_value=mock_output)
    evaluator.arun = AsyncMock(return_value=mock_output)
    eval_instance.evaluator_agent = evaluator
    return evaluator


def _mock_evaluator_failure(eval_instance: AccuracyEval):
    """Helper to mock the evaluator agent so every evaluation fails (e.g. judge model unavailable)."""
    evaluator = eval_instance.get_evaluator_agent()
    evaluator.model = MagicMock()
    evaluator.run = MagicMock(side_effect=Exception("Evaluator model unavailable"))
    evaluator.arun = AsyncMock(side_effect=Exception("Evaluator model unavailable"))
    eval_instance.evaluator_agent = evaluator
    return evaluator


def test_basic_evaluation_computes_score():
    """A successful evaluation populates results and computes the score stats."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
    )
    _mock_evaluator(eval, score=8)

    result = eval.run_with_output(output="4", print_results=False, print_summary=False)

    assert result is not None
    assert len(result.results) == 1
    assert result.avg_score == 8
    assert result.min_score == 8
    assert result.max_score == 8


def test_all_iterations_fail_returns_none_stats():
    """Regression for #7672: when every iteration fails, the stat fields default to None
    instead of being left unset (which raised AttributeError)."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
        num_iterations=2,
    )
    _mock_evaluator_failure(eval)

    result = eval.run_with_output(output="4", print_results=False, print_summary=False)

    assert result is not None
    assert len(result.results) == 0
    assert result.avg_score is None
    assert result.mean_score is None
    assert result.min_score is None
    assert result.max_score is None
    assert result.std_dev_score is None


def test_print_summary_does_not_raise_when_all_iterations_fail():
    """print_summary() must not raise AttributeError on an empty result (the bug's crash site)."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
    )
    _mock_evaluator_failure(eval)

    result = eval.run_with_output(output="4", print_results=False, print_summary=False)
    # Should complete without raising AttributeError.
    result.print_summary()


async def test_async_all_iterations_fail_returns_none_stats():
    """Async regression for #7672 via arun_with_output."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
    )
    _mock_evaluator_failure(eval)

    result = await eval.arun_with_output(output="4", print_results=False, print_summary=False)

    assert result is not None
    assert len(result.results) == 0
    assert result.avg_score is None


# ---------------------------------------------------------------------------
# run_id is per execution: one run() call, one row, one id
# ---------------------------------------------------------------------------


async def test_arun_with_output_logs_distinct_run_id_per_execution():
    """Async path also stores a distinct run_id per execution.

    Also guards the db-logging branch for an eval with no agent/team: arun_with_output
    used to raise UnboundLocalError there (its sync twin had the else branch, it did not)."""
    db = InMemoryDb()
    eval = AccuracyEval(input="What is 2 + 2?", expected_output="4", db=db, telemetry=False)
    _mock_evaluator(eval, score=8)

    first = await eval.arun_with_output(output="4", print_results=False, print_summary=False)
    second = await eval.arun_with_output(output="4", print_results=False, print_summary=False)

    runs = db.get_eval_runs()
    assert len(runs) == 2
    assert first.run_id != second.run_id
    assert {run.run_id for run in runs} == {first.run_id, second.run_id}


def test_run_uses_a_fresh_agent_session_per_execution():
    """Each run talks to the agent under test in its own session, keyed by run_id, so a rerun of
    the same eval instance never sees the previous run's conversation as history."""
    agent = Agent()
    agent.run = MagicMock(return_value=RunOutput(content="4"))
    eval = AccuracyEval(agent=agent, input="What is 2 + 2?", expected_output="4", telemetry=False, show_spinner=False)
    _mock_evaluator(eval, score=8)

    first = eval.run(print_results=False, print_summary=False)
    second = eval.run(print_results=False, print_summary=False)

    assert first.run_id != second.run_id
    session_ids = [call.kwargs["session_id"] for call in agent.run.call_args_list]
    assert session_ids == [f"eval_{first.run_id}_1", f"eval_{second.run_id}_1"]


async def test_concurrent_aruns_return_their_own_results():
    """Concurrent runs on one instance each return their own result object, holding only that
    run's iterations and the run_id of that caller's row (self.result aliases the last run)."""
    db = InMemoryDb()
    eval = AccuracyEval(input="What is 2 + 2?", expected_output="4", db=db, telemetry=False)
    _mock_evaluator(eval, score=8)

    first, second = await asyncio.gather(
        eval.arun_with_output(output="4", print_results=False, print_summary=False),
        eval.arun_with_output(output="4", print_results=False, print_summary=False),
    )

    assert first is not second
    assert first.run_id != second.run_id
    assert len(first.results) == 1
    assert len(second.results) == 1
    assert {run.run_id for run in db.get_eval_runs()} == {first.run_id, second.run_id}


async def test_arun_logs_distinct_run_id_per_execution():
    """Async twin of the primary path."""
    db = InMemoryDb()
    agent = Agent()
    agent.arun = AsyncMock(return_value=RunOutput(content="4"))
    eval = AccuracyEval(
        agent=agent, input="What is 2 + 2?", expected_output="4", db=db, telemetry=False, show_spinner=False
    )
    _mock_evaluator(eval, score=8)

    first = await eval.arun(print_results=False, print_summary=False)
    second = await eval.arun(print_results=False, print_summary=False)

    runs = db.get_eval_runs()
    assert len(runs) == 2
    assert first.run_id != second.run_id
    assert {run.run_id for run in runs} == {first.run_id, second.run_id}


def test_team_subject_logs_distinct_run_id_per_execution():
    """A team subject takes the elif branch on the way to the same per-run row."""
    db = InMemoryDb()
    team = Team(members=[Agent(id="member")])
    team.run = MagicMock(return_value=RunOutput(content="4"))
    eval = AccuracyEval(
        team=team, input="What is 2 + 2?", expected_output="4", db=db, telemetry=False, show_spinner=False
    )
    _mock_evaluator(eval, score=8)

    first = eval.run(print_results=False, print_summary=False)
    second = eval.run(print_results=False, print_summary=False)

    runs = db.get_eval_runs()
    assert len(runs) == 2
    assert {run.run_id for run in runs} == {first.run_id, second.run_id}
    assert {run.team_id for run in runs} == {team.id}


def test_result_is_published_only_once_the_run_completes():
    """self.result is a snapshot of the last COMPLETED run: a run that raises part-way
    must not leave a partial result (with its confident stats) on the eval object."""
    db = InMemoryDb()
    agent = Agent()
    agent.run = MagicMock(side_effect=[RunOutput(content="4"), RuntimeError("agent unavailable")])
    eval = AccuracyEval(
        agent=agent,
        input="What is 2 + 2?",
        expected_output="4",
        num_iterations=2,
        db=db,
        telemetry=False,
        show_spinner=False,
    )
    _mock_evaluator(eval, score=8)

    with pytest.raises(RuntimeError):
        eval.run(print_results=False, print_summary=False)

    assert eval.result is None


def test_rerun_stores_a_row_and_a_file_per_run(tmp_path):
    """run_id is the evals table primary key and create_eval_run is a plain insert, so a reused
    id made the second write raise and be swallowed. The file sink is keyed the same way, so one
    rerun is enough to cover both. InMemoryDb has no uniqueness and cannot show the failure."""
    db = SqliteDb(db_file=str(tmp_path / "evals.db"))
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
        db=db,
        telemetry=False,
        file_path_to_save_results=str(tmp_path / "{run_id}.json"),
    )
    _mock_evaluator(eval, score=8)

    first = eval.run_with_output(output="4", print_results=False, print_summary=False)
    second = eval.run_with_output(output="4", print_results=False, print_summary=False)

    assert {run.run_id for run in db.get_eval_runs()} == {first.run_id, second.run_id}
    assert (tmp_path / f"{first.run_id}.json").exists()
    assert (tmp_path / f"{second.run_id}.json").exists()
