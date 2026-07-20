"""Truncated model output is a lifecycle outcome, not a score.

A response that exhausts the model's output budget comes back incomplete: the run
still reports `RunStatus.completed`, but there is no content to grade. Before this
the engine handed that run to the scorer, and every scorer that reads `run.content`
raised. A truncated attempt is now stopped with its own reason, never scored, and
excluded from the pass rate -- the same category as a timeout.
"""

import asyncio
import copy

import pytest

from agno.agent import Agent
from agno.environments import Environment, EnvironmentRunResult, StopReason, Task, run_rollouts
from agno.environments._engine import arun_batch
from agno.environments._render import build_report
from agno.models.base import Model
from agno.models.response import ModelResponse, ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer, JudgeScorer, ToolCallScorer


def _output(**kwargs):
    kwargs.setdefault("status", RunStatus.completed)
    return RunOutput(**kwargs)


class StubAgent:
    """The engine's streaming contract, small enough to script per input."""

    def __init__(self, respond):
        self._respond = respond

    def deep_copy(self):
        return copy.copy(self)

    async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
        yield self._respond(input)


class CountingScorer:
    """Records every run it is handed, so "never invoked" is assertable."""

    def __init__(self):
        self.seen = []

    async def ascore(self, run, expected=None):
        self.seen.append(run)
        # The unguarded shape from the design note: the 79 shipped cookbook scorers
        # all read run.content like this, and must never be reached on a truncation.
        from agno.scorer import Score

        return Score(value=1.0 if run.content == expected else 0.0, passed=run.content == expected)

    def digest(self):
        return "counting-scorer"


class FakeModel(Model):
    def __init__(self, tag="fake"):
        super().__init__(id=f"fake-{tag}", name=f"fake-{tag}", provider="test")

    def _resp(self):
        return ModelResponse(role="assistant", content="ok")

    def invoke(self, *args, **kwargs):
        return self._resp()

    async def ainvoke(self, *args, **kwargs):
        return self._resp()

    def invoke_stream(self, *args, **kwargs):
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp()

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


# ---------------------------------------------------------------------------
# 1a -- the four acceptance criteria of the design note
# ---------------------------------------------------------------------------


async def test_truncated_output_skips_scorer():
    # A completed run carrying no content is the truncation signature. The scorer is
    # never called on it, and the attempt stays unscored rather than failed.
    scorer = CountingScorer()
    agent = StubAgent(lambda value: _output(content=None))

    results = await arun_batch(agent, ["a"], k=1, scorer=scorer, expected=["a"])

    attempt = results[0][0]
    assert attempt.stop_reason == StopReason.truncated
    assert attempt.score is None
    assert scorer.seen == []


async def test_truncated_excluded_from_pass_rate():
    # Denominator, not a zero: one truncated and one passing attempt is 1.00, not 0.50.
    # Coercing truncation to a failure would report a working agent as half broken.
    contents = iter([None, "a"])
    agent = StubAgent(lambda value: _output(content=next(contents)))
    scorer = CodeScorer(lambda run, expected: run.content == expected)

    results = await arun_batch(agent, ["a"], k=2, scorer=scorer, expected=["a"])

    stop_reasons = [attempt.stop_reason for attempt in results[0]]
    assert stop_reasons == [StopReason.truncated, StopReason.completed]

    env = Environment(
        name="truncation",
        agent=Agent(model=FakeModel()),
        tasks=(Task(input="a", expected="a"),),
        scorer=scorer,
    )
    task_result = _task_result_from(env, results[0])
    assert task_result.n_scored == 1
    assert task_result.n_unscored == 1
    assert task_result.pass_rate == 1.0


def _task_result_from(env, attempts):
    from agno.environments.runner import TaskResult

    return TaskResult(task=env.tasks[0], attempts=tuple(attempts))


async def test_truncated_distinct_in_report():
    # Truncated, errored and timed-out attempts are all unscored, but the report must
    # say which: "your output cap is too low" is a different fix from "your agent is
    # unreliable".
    truncated = await arun_batch(StubAgent(lambda value: _output(content=None)), ["a"], k=1)
    errored = await arun_batch(StubAgent(lambda value: _output(status=RunStatus.error)), ["a"], k=1)

    async def slow_arun(*, input, stream, stream_events, yield_run_output, session_id):
        await asyncio.sleep(5)
        yield _output(content="late")  # pragma: no cover -- cancelled by the timeout

    slow = StubAgent(lambda value: _output(content="late"))
    slow.arun = slow_arun
    timed_out = await arun_batch(slow, ["a"], k=1, timeout_seconds=1)

    # Three unscored attempts, three different reasons -- the distinction the grid's
    # single "unscored" glyph cannot carry.
    assert truncated[0][0].stop_reason == StopReason.truncated
    assert errored[0][0].stop_reason == StopReason.error
    assert timed_out[0][0].stop_reason == StopReason.timeout
    assert all(attempt[0][0].score is None for attempt in (truncated, errored, timed_out))

    env = Environment(
        name="truncation",
        agent=Agent(model=FakeModel()),
        tasks=(Task(input="a"),),
        scorer=CodeScorer(lambda run, expected: True),
    )
    # The report names the reason for all three.
    report = build_report([_task_result_from(env, truncated[0])], only="failed")
    assert "stop=truncated" in report
    assert "the run completed with no content" in report

    errored_report = build_report([_task_result_from(env, errored[0])], only="failed")
    assert "stop=error" in errored_report
    assert "stop=truncated" not in errored_report

    timeout_report = build_report([_task_result_from(env, timed_out[0])], only="failed")
    assert "stop=timeout" in timeout_report
    assert "stop=truncated" not in timeout_report

    # And so does the grid: an unscored count alone cannot tell an operator whether to
    # raise the output cap or go fix the agent.
    grid = str(
        EnvironmentRunResult(
            env_name="truncation",
            k=1,
            env_fingerprint="envfp2:test",
            policy_fingerprint="test",
            task_results=(_task_result_from(env, truncated[0]),),
            duration_seconds=0.1,
        )
    )
    assert "1 truncated" in grid

    errored_grid = str(
        EnvironmentRunResult(
            env_name="truncation",
            k=1,
            env_fingerprint="envfp2:test",
            policy_fingerprint="test",
            task_results=(_task_result_from(env, errored[0]),),
            duration_seconds=0.1,
        )
    )
    assert "truncated" not in errored_grid


async def test_tool_terminated_run_is_not_truncated():
    # A run that ends on stop_after_tool_call never emits a final assistant turn, so
    # its content is legitimately None. ToolCallScorer grades run.tools, not
    # run.content -- calling these truncated would turn a correct pass into no data.
    execution = ToolExecution(tool_call_id="c1", tool_name="submit", stop_after_tool_call=True)
    agent = StubAgent(lambda value: _output(content=None, tools=[execution]))
    scorer = ToolCallScorer(expected_tools=["submit"])

    results = await arun_batch(agent, ["a"], k=1, scorer=scorer)

    attempt = results[0][0]
    assert attempt.stop_reason == StopReason.completed
    assert attempt.score is not None and attempt.score.passed

    # A contentless run WITHOUT that marker is still truncated.
    plain = await arun_batch(StubAgent(lambda value: _output(content=None)), ["a"], k=1, scorer=scorer)
    assert plain[0][0].stop_reason == StopReason.truncated


async def test_completed_with_content_scores_as_before():
    # The regression that matters: a normal completed response is untouched -- scored,
    # counted, and still `completed`. Only `content is None` changes category, so an
    # empty-string answer stays an answer.
    scorer = CountingScorer()
    agent = StubAgent(lambda value: _output(content="a"))

    results = await arun_batch(agent, ["a"], k=2, scorer=scorer, expected=["a"])

    for attempt in results[0]:
        assert attempt.stop_reason == StopReason.completed
        assert attempt.score is not None and attempt.score.passed
        assert attempt.error is None
    assert len(scorer.seen) == 2

    blank = await arun_batch(StubAgent(lambda value: _output(content="")), ["a"], k=1, scorer=scorer, expected=[""])
    assert blank[0][0].stop_reason == StopReason.completed
    assert blank[0][0].score is not None


# ---------------------------------------------------------------------------
# 1b / 1c / 1d -- reproduced against main, then fixed
# ---------------------------------------------------------------------------


def test_environment_rejects_non_scorer():
    # A bare callable used to construct fine and die at score time with an
    # AttributeError naming `ascore` -- after the rollout had been paid for.
    with pytest.raises(TypeError) as excinfo:
        Environment(
            name="bad-scorer",
            agent=Agent(model=FakeModel()),
            tasks=(Task(input="a"),),
            scorer=lambda run, expected: True,
        )

    message = str(excinfo.value)
    assert "must be a Scorer" in message
    assert "CodeScorer" in message

    # An unconstructed scorer CLASS carries the same methods, so a structural check
    # alone would accept it -- the same typo, one keystroke away.
    with pytest.raises(TypeError) as class_exc:
        Environment(
            name="scorer-class",
            agent=Agent(model=FakeModel()),
            tasks=(Task(input="a"),),
            scorer=CodeScorer,
        )
    assert "CodeScorer" in str(class_exc.value)

    # The built-ins still construct.
    Environment(
        name="good-scorer",
        agent=Agent(model=FakeModel()),
        tasks=(Task(input="a"),),
        scorer=CodeScorer(lambda run, expected: True),
    )


def test_judge_binary_digest_ignores_threshold():
    # Binary mode never reads threshold, so two judges that grade identically must
    # fingerprint identically; numeric mode still separates them.
    binary_low = JudgeScorer(model=FakeModel(), criteria="is it good", mode="binary", threshold=3)
    binary_high = JudgeScorer(model=FakeModel(), criteria="is it good", mode="binary", threshold=9)
    assert binary_low.digest() == binary_high.digest()

    numeric_low = JudgeScorer(model=FakeModel(), criteria="is it good", mode="numeric", threshold=3)
    numeric_high = JudgeScorer(model=FakeModel(), criteria="is it good", mode="numeric", threshold=9)
    assert numeric_low.digest() != numeric_high.digest()

    # Mode itself remains part of the identity.
    assert binary_low.digest() != numeric_low.digest()


def test_run_rollouts_rejects_duplicate_tasks():
    # tasks=[t, t] used to run the task twice under one id: two grid rows diff()
    # cannot tell apart, and every passing attempt exported twice.
    task = Task(input="hello", id="dup")
    env = Environment(
        name="dupes",
        agent=Agent(model=FakeModel()),
        tasks=(task,),
        scorer=CodeScorer(lambda run, expected: True),
    )

    with pytest.raises(ValueError) as excinfo:
        run_rollouts(env, k=1, tasks=[task, task])

    message = str(excinfo.value)
    assert "duplicate task" in message
    assert "dup" in message

    # A single selection of the same task is still legal.
    result = run_rollouts(env, k=1, tasks=[task])
    assert len(result.task_results) == 1
