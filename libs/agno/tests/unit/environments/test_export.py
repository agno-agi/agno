"""Unit tests for the conversational-SFT exporter and its vendored oracle."""

import hashlib
import json

from agno.environments import (
    Environment,
    EnvironmentRunResult,
    StopReason,
    Task,
    TaskResult,
    arun_rollouts,
    ato_sft_jsonl,
    to_sft_jsonl,
)
from agno.environments._engine import AttemptResult
from agno.environments.exporters._validate import validate_sft_jsonl
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer, Score


def _conversational_run(answer, *, question="What is 2+2?", tools=None, history_noise=True):
    messages = [
        Message(role="system", content="Answer with a number."),
        Message(role="user", content=question),
        Message(role="assistant", content=answer),
    ]
    if history_noise:
        messages.insert(1, Message(role="user", content="earlier turn", from_history=True))
    return RunOutput(content=answer, status=RunStatus.completed, messages=messages, tools=tools)


def _attempt(run, *, passed=True, value=None, limit_hit=False, unscored=False):
    return AttemptResult(
        run=run,
        score=None
        if unscored
        else Score(value=value if value is not None else (1.0 if passed else 0.0), passed=passed),
        stop_reason=StopReason.completed,
        duration_seconds=0.1,
        tool_call_limit_hit=limit_hit,
    )


def _result(*task_rows, env_fingerprint="env-fp", policy_fingerprint="policy-fp"):
    task_results = tuple(
        TaskResult(task=Task(input=f"q{index}", id=f"t{index + 1}"), attempts=tuple(attempts))
        for index, attempts in enumerate(task_rows)
    )
    return EnvironmentRunResult(
        env_name="export-env",
        k=max((len(attempts) for attempts in task_rows), default=0),
        env_fingerprint=env_fingerprint,
        policy_fingerprint=policy_fingerprint,
        task_results=task_results,
        duration_seconds=1.0,
    )


async def test_ato_sft_jsonl_matches_sync(tmp_path):
    result = _result([_attempt(_conversational_run("4"))])
    sync_path = tmp_path / "sync.jsonl"
    async_path = tmp_path / "async.jsonl"
    sync_report = to_sft_jsonl(result, sync_path)
    async_report = await ato_sft_jsonl(result, async_path)
    assert async_report == sync_report
    assert async_path.read_text(encoding="utf-8") == sync_path.read_text(encoding="utf-8")


def test_export_passes_vendored_validator(tmp_path):
    result = _result(
        [_attempt(_conversational_run("4")), _attempt(_conversational_run("four"))],
        [_attempt(_conversational_run("9"))],
    )
    path = tmp_path / "train.jsonl"
    report = to_sft_jsonl(result, path)

    assert report.n_written == 3
    assert validate_sft_jsonl(path) == 3

    # The 320-conversation cap, still validator-clean.
    many = _result([_attempt(_conversational_run(f"answer {index}")) for index in range(400)])
    capped_path = tmp_path / "capped.jsonl"
    capped_report = to_sft_jsonl(many, capped_path)
    assert capped_report.n_written == 320
    assert capped_report.n_dropped_over_cap == 80
    assert validate_sft_jsonl(capped_path) == 320

    # The 1 MiB cap: ~300 KiB per row means only 3 fit.
    big = _result([_attempt(_conversational_run("x" * 300_000)) for _ in range(5)])
    big_path = tmp_path / "big.jsonl"
    big_report = to_sft_jsonl(big, big_path)
    assert big_report.n_written == 3
    assert big_report.n_dropped_over_cap == 2
    assert validate_sft_jsonl(big_path) == 3


def test_export_default_excludes_failed_attempts(tmp_path):
    # learning_zone() selects TASKS with both passed and failed attempts -- by
    # construction they contain failures, and the flagship's last line must not
    # write wrong answers into a supervised file.
    result = _result(
        [
            _attempt(_conversational_run("4"), passed=True),
            _attempt(_conversational_run("5 (wrong)"), passed=False),
        ]
    )
    zone = result.learning_zone()
    assert len(zone.task_results) == 1  # mixed pass/fail: in the zone

    path = tmp_path / "train.jsonl"
    report = to_sft_jsonl(zone, path)

    assert report.n_written == 1
    assert report.n_skipped_failed == 1
    contents = path.read_text(encoding="utf-8")
    assert "wrong" not in contents
    assert '"content": "4"' in contents


def test_export_skips_tool_call_runs(tmp_path):
    # The intersection format has no tool representation: emitting the final answer
    # without the tool trace that produced it would train answering WITHOUT the
    # tools the model actually used.
    with_tools = _conversational_run("42", tools=[ToolExecution(tool_name="search")])
    result = _result([_attempt(with_tools), _attempt(_conversational_run("plain"))])

    report = to_sft_jsonl(result, tmp_path / "train.jsonl")

    assert report.n_written == 1
    assert report.n_skipped_tool_runs == 1


def test_export_skips_limit_hit(tmp_path):
    result = _result(
        [
            _attempt(_conversational_run("under duress"), limit_hit=True),
            _attempt(_conversational_run("fine")),
        ]
    )
    report = to_sft_jsonl(result, tmp_path / "train.jsonl")

    assert report.n_written == 1
    assert report.n_skipped_limit_hit == 1


def test_export_assistant_content_is_raw(tmp_path):
    # Byte-for-byte what the model emitted -- never a serialization of run.content.
    raw = 'The answer is:\n  {"value": 4}—done éè'
    result = _result([_attempt(_conversational_run(raw))])
    path = tmp_path / "train.jsonl"
    to_sft_jsonl(result, path)

    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["messages"][-1]["role"] == "assistant"
    assert row["messages"][-1]["content"] == raw

    # A run whose content is only a pydantic object with no message string is
    # skipped and counted: str() is a repr and model_dump_json() re-orders -- both
    # produce text the model never generated.
    from pydantic import BaseModel

    class Answer(BaseModel):
        value: int

    structured = RunOutput(
        content=Answer(value=4),
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="What is 2+2?"),
            Message(role="assistant", content=None),
        ],
    )
    report = to_sft_jsonl(_result([_attempt(structured)]), tmp_path / "structured.jsonl")
    assert report.n_written == 0
    assert report.n_skipped_no_text == 1


async def test_export_is_deterministic(tmp_path):
    # Task order, attempt order within: deterministic under any concurrency.
    def scorer_fn(run, expected):
        return run.content == expected

    class ConversationalStub:
        def __init__(self):
            self.model = None

        async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
            yield _conversational_run(f"echo:{input}", question=input, history_noise=False)

    env = Environment(
        name="deterministic",
        tasks=(
            Task(input="one", expected="echo:one"),
            Task(input="two", expected="echo:two"),
            Task(input="three", expected="echo:three"),
        ),
        scorer=CodeScorer(scorer_fn),
        agent=lambda: ConversationalStub(),
    )
    result = await arun_rollouts(env, k=4, concurrency=4)

    first, second = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    to_sft_jsonl(result, first)
    to_sft_jsonl(result, second)
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(second.read_bytes()).hexdigest()

    # Emitted order is task order: t1's rows precede t2's regardless of completion.
    rows = [json.loads(line) for line in first.read_text(encoding="utf-8").strip().split("\n")]
    questions = [row["messages"][1]["content"] for row in rows if row["messages"][1]["role"] == "user"]
    assert questions == ["one"] * 4 + ["two"] * 4 + ["three"] * 4


def test_export_emits_common_core_only(tmp_path):
    # The portability guarantee: the strictest consumer REJECTS files with unknown
    # keys -- it does not drop them -- so one helpful key breaks every consumer.
    result = _result([_attempt(_conversational_run("4"))])
    path = tmp_path / "train.jsonl"
    to_sft_jsonl(result, path)

    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        row = json.loads(line)
        assert set(row) == {"messages"}
        for message in row["messages"]:
            assert set(message) == {"role", "content"}


def test_export_counters_sum(tmp_path):
    result = _result(
        [
            _attempt(_conversational_run("good")),
            _attempt(_conversational_run("bad"), passed=False),
            _attempt(_conversational_run("limit"), limit_hit=True),
            _attempt(_conversational_run("tools", tools=[ToolExecution(tool_name="t")])),
            _attempt(RunOutput(content="no messages", status=RunStatus.completed)),
            _attempt(_conversational_run("unscored"), unscored=True),
        ]
    )
    report = to_sft_jsonl(result, tmp_path / "train.jsonl")

    candidates = sum(
        1 for task_result in result.task_results for attempt in task_result.attempts if attempt.score is not None
    )
    total = (
        report.n_written
        + report.n_skipped_failed
        + report.n_skipped_tool_runs
        + report.n_skipped_limit_hit
        + report.n_skipped_no_text
        + report.n_dropped_over_cap
    )
    assert candidates == 5  # the unscored attempt is not a candidate
    assert total == candidates
    assert report.n_written == 1
    assert report.n_skipped_failed == 1
    assert report.n_skipped_limit_hit == 1
    assert report.n_skipped_tool_runs == 1
    assert report.n_skipped_no_text == 1


def test_sidecar_written(tmp_path):
    result = _result(
        [_attempt(_conversational_run("4"), value=1.0)],
        [_attempt(_conversational_run("9"), value=0.75)],
    )
    path = tmp_path / "train.jsonl"
    to_sft_jsonl(result, path, only_passed=True)

    sidecar = json.loads((tmp_path / "train.jsonl.meta.json").read_text(encoding="utf-8"))
    assert sidecar["env_fingerprint"] == "env-fp"
    assert sidecar["policy_fingerprint"] == "policy-fp"
    assert sidecar["options"] == {"only_passed": True}
    assert sidecar["report"]["n_written"] == 2
    # Per-line provenance, in emitted order.
    assert sidecar["lines"] == [
        {"task_id": "t1", "attempt_index": 0, "score": 1.0},
        {"task_id": "t2", "attempt_index": 0, "score": 0.75},
    ]


def test_root_reexports():
    # The flagship's import path: straight off the package root.
    from agno.environments import ExportReport as RootExportReport
    from agno.environments import to_sft_jsonl as root_to_sft_jsonl
    from agno.environments.exporters import ExportReport
    from agno.environments.exporters import to_sft_jsonl as exporters_to_sft_jsonl

    assert root_to_sft_jsonl is exporters_to_sft_jsonl
    assert RootExportReport is ExportReport


def test_export_skip_order_limit_hit_before_tool_runs(tmp_path):
    # A real limit-hit run is tool-bearing (successful executions before the refusal),
    # so checks (2) and (3) overlap: first-match-wins must attribute it to limit_hit.
    tool_bearing_limit_hit = _attempt(
        _conversational_run("under duress", tools=[ToolExecution(tool_name="search")]),
        limit_hit=True,
    )
    report = to_sft_jsonl(_result([tool_bearing_limit_hit]), tmp_path / "train.jsonl")

    assert report.n_written == 0
    assert report.n_skipped_limit_hit == 1
    assert report.n_skipped_tool_runs == 0


def test_export_skip_order_failed_before_limit_hit(tmp_path):
    # A failed, limit-hit, tool-bearing attempt increments exactly one counter: (1).
    overlapping = _attempt(
        _conversational_run("wrong", tools=[ToolExecution(tool_name="search")]),
        passed=False,
        limit_hit=True,
    )
    report = to_sft_jsonl(_result([overlapping]), tmp_path / "train.jsonl")

    assert report.n_written == 0
    assert report.n_skipped_failed == 1
    assert report.n_skipped_limit_hit == 0
    assert report.n_skipped_tool_runs == 0


def test_export_only_passed_false_writes_failed_attempts(tmp_path):
    # The explicit override: failed scored attempts are written, unscored attempts
    # remain non-candidates, and the sidecar records the option.
    result = _result(
        [
            _attempt(_conversational_run("4")),
            _attempt(_conversational_run("five"), passed=False),
            _attempt(_conversational_run("ignored"), unscored=True),
        ]
    )
    path = tmp_path / "train.jsonl"
    report = to_sft_jsonl(result, path, only_passed=False)

    assert report.n_written == 2
    assert report.n_skipped_failed == 0
    sidecar = json.loads((tmp_path / "train.jsonl.meta.json").read_text(encoding="utf-8"))
    assert sidecar["options"]["only_passed"] is False


def test_export_creates_missing_parent_dirs(tmp_path):
    # A fresh checkout has no data/generated/ dir; the exporter must create the
    # parent path rather than FileNotFoundError (C9: parent directories are created).
    result = _result([_attempt(_conversational_run("4"), passed=True)])
    nested = tmp_path / "data" / "generated" / "train.jsonl"
    assert not nested.parent.exists()
    report = to_sft_jsonl(result, nested)
    assert nested.exists()
    assert report.n_written == 1
