"""Unit tests for the eval suite runner (agno.eval.suite)."""

import asyncio
import json
from dataclasses import fields
from types import SimpleNamespace

import pytest

from agno.eval import suite
from agno.eval.suite import Case, SuiteResult, acli, arun_cases, cli, run_cases
from agno.models.response import ToolExecution
from agno.run.agent import RunErrorEvent, RunOutput, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.base import RunStatus


class StubAgent:
    """Stands in for Agent: arun yields scripted events, then the final RunOutput.

    Mirrors the real streaming contract: in-run failures do NOT raise - the stream
    yields a RunErrorEvent and ends without the final RunOutput (emit_output=False).
    A raising `error` models pre-stream failures (e.g. input validation).
    """

    def __init__(self, *, id="stub-agent", events=(), output=None, error=None, delay=0.0, emit_output=True):
        self.id = id
        self._events = list(events)
        self._output = output if output is not None else RunOutput(content="stub response")
        self._error = error
        self._delay = delay
        self._emit_output = emit_output
        self.run_count = 0
        self.session_ids = []
        self.loops = []

    async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
        self.run_count += 1
        self.session_ids.append(session_id)
        self.loops.append(asyncio.get_running_loop())
        if self._error is not None:
            raise self._error
        if self._delay:
            await asyncio.sleep(self._delay)
        for event in self._events:
            yield event
        if self._emit_output:
            yield self._output


def _install_fake_evals(
    monkeypatch,
    *,
    judge_passed=True,
    judge_reason="meets the criteria",
    judge_error=None,
    judge_delay=0.0,
    reliability_status="PASSED",
    reliability_error=None,
):
    """Replace AgentAsJudgeEval/ReliabilityEval in the suite module with fakes.

    Returns (judge_instances, reliability_instances) capturing constructor kwargs.
    """
    judge_instances = []
    reliability_instances = []

    class FakeJudgeEval:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            judge_instances.append(self)

        async def arun(self, *, input, output):
            self.input = input
            self.output = output
            if judge_delay:
                await asyncio.sleep(judge_delay)
            if judge_error is not None:
                raise judge_error
            return SimpleNamespace(results=[SimpleNamespace(passed=judge_passed, reason=judge_reason)])

    class FakeReliabilityEval:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            reliability_instances.append(self)

        async def arun(self):
            if reliability_error is not None:
                raise reliability_error
            return SimpleNamespace(eval_status=reliability_status)

    monkeypatch.setattr(suite, "AgentAsJudgeEval", FakeJudgeEval)
    monkeypatch.setattr(suite, "ReliabilityEval", FakeReliabilityEval)
    return judge_instances, reliability_instances


def _make_case(agent=None, **kwargs):
    defaults = {
        "name": "sample_case",
        "input": "What is the capital of France?",
        "criteria": "Mentions Paris.",
    }
    defaults.update(kwargs)
    return Case(agent=agent if agent is not None else StubAgent(), **defaults)


# ---------------------------------------------------------------------------
# Case construction (check 1)
# ---------------------------------------------------------------------------


def test_case_without_checks_raises():
    with pytest.raises(ValueError, match="has no checks"):
        Case(name="x", agent=StubAgent(), input="q")


def test_case_with_either_check_constructs():
    _make_case(criteria="Mentions Paris.")
    _make_case(criteria=None, expected_tool_calls=("search_web",))


def test_agent_is_the_last_required_field():
    # agent must stay last of the required fields so it can gain a default later
    # (team/workflow alternatives) without a non-default-after-default TypeError.
    assert [f.name for f in fields(Case)[:3]] == ["name", "input", "agent"]


# ---------------------------------------------------------------------------
# Selection (check 2)
# ---------------------------------------------------------------------------


def test_tag_selection_filters_cases(monkeypatch):
    _install_fake_evals(monkeypatch)
    smoke_agent, release_agent = StubAgent(), StubAgent()
    cases = [
        _make_case(agent=smoke_agent, name="smoke_case", tags=("smoke",)),
        _make_case(agent=release_agent, name="release_case", tags=("release",)),
    ]

    result = asyncio.run(arun_cases(cases, tag="smoke"))

    assert [r.name for r in result.results] == ["smoke_case"]
    assert smoke_agent.run_count == 1
    assert release_agent.run_count == 0


def test_name_selection_filters_cases(monkeypatch):
    _install_fake_evals(monkeypatch)
    cases = [_make_case(name="first"), _make_case(name="second")]

    result = run_cases(cases, name="second")

    assert [r.name for r in result.results] == ["second"]


def test_unknown_tag_returns_empty_suite(monkeypatch):
    _install_fake_evals(monkeypatch)
    agent = StubAgent()

    result = asyncio.run(arun_cases([_make_case(agent=agent, tags=("smoke",))], tag="nope"))

    assert isinstance(result, SuiteResult)
    assert result.results == []
    assert agent.run_count == 0


# ---------------------------------------------------------------------------
# Agent errors (check 3) and run status handling
# ---------------------------------------------------------------------------


def test_agent_error_is_captured_and_suite_continues(monkeypatch):
    _install_fake_evals(monkeypatch)
    failing_agent = StubAgent(error=RuntimeError("model exploded"))
    ok_agent = StubAgent()
    cases = [
        _make_case(agent=failing_agent, name="broken"),
        _make_case(agent=ok_agent, name="fine"),
    ]

    result = run_cases(cases)

    broken, fine = result.results
    assert broken.error is not None
    assert broken.error.startswith("RuntimeError")
    assert broken.passed is False
    assert fine.name == "fine"
    assert fine.passed is True
    assert ok_agent.run_count == 1


def test_streamed_run_error_event_is_recorded(monkeypatch):
    # The real streaming path never raises on in-run failure: it yields a
    # RunErrorEvent and ends without the final RunOutput.
    judge_instances, _ = _install_fake_evals(monkeypatch)
    failing_agent = StubAgent(events=[RunErrorEvent(content="rate limited by provider")], emit_output=False)
    typed_agent = StubAgent(events=[RunErrorEvent(content="boom", error_type="ModelProviderError")], emit_output=False)
    ok_agent = StubAgent()
    cases = [
        _make_case(agent=failing_agent, name="stream_error"),
        _make_case(agent=typed_agent, name="typed_error"),
        _make_case(agent=ok_agent, name="fine"),
    ]

    result = run_cases(cases)

    stream_error, typed_error, fine = result.results
    assert stream_error.error == "agent: rate limited by provider"
    assert stream_error.passed is False
    assert typed_error.error == "agent: ModelProviderError: boom"
    assert fine.passed is True
    assert len(judge_instances) == 1  # only the successful case was judged


def test_paused_run_is_not_judged(monkeypatch):
    judge_instances, _ = _install_fake_evals(monkeypatch)
    paused_output = RunOutput(content="I have tools to execute, but I need confirmation.", status=RunStatus.paused)

    result = run_cases([_make_case(agent=StubAgent(output=paused_output))]).results[0]

    assert result.error == "agent: run paused awaiting user input"
    assert result.passed is False
    assert result.judge_passed is None
    assert judge_instances == []
    # Evidence fields are still populated for the post-mortem
    assert result.response is paused_output
    assert result.output == "I have tools to execute, but I need confirmation."


def test_cancelled_run_is_not_judged(monkeypatch):
    judge_instances, reliability_instances = _install_fake_evals(monkeypatch)
    cancelled_output = RunOutput(content="Run cancelled by user.", status=RunStatus.cancelled)
    case = _make_case(agent=StubAgent(output=cancelled_output), expected_tool_calls=("search_web",))

    result = run_cases([case]).results[0]

    assert result.error == "agent: run cancelled"
    assert result.passed is False
    assert result.judge_passed is None
    assert result.reliability_passed is None
    assert judge_instances == []
    assert reliability_instances == []


# ---------------------------------------------------------------------------
# Timeouts and lifecycle hooks (checks 4, 5, 6, 13)
# ---------------------------------------------------------------------------


def test_timeout_sets_flags_and_teardown_still_runs(monkeypatch):
    _install_fake_evals(monkeypatch)
    teardown_calls = []
    case = _make_case(
        agent=StubAgent(delay=5.0),
        timeout_seconds=1,
        teardown=lambda context, result: teardown_calls.append((context, result)),
    )

    result = run_cases([case]).results[0]

    assert result.timed_out is True
    assert result.error == "timeout: exceeded 1s"
    assert result.passed is False
    assert len(teardown_calls) == 1
    assert teardown_calls[0][1].timed_out is True


def test_timeout_covers_the_judge_check(monkeypatch):
    _install_fake_evals(monkeypatch, judge_delay=5.0)
    teardown_calls = []
    case = _make_case(
        timeout_seconds=1,
        teardown=lambda context, result: teardown_calls.append((context, result)),
    )

    result = run_cases([case]).results[0]

    assert result.timed_out is True
    assert result.error == "timeout: exceeded 1s"
    assert len(teardown_calls) == 1


def test_setup_context_is_threaded_to_teardown(monkeypatch):
    _install_fake_evals(monkeypatch)
    sentinel = object()
    received = []
    case = _make_case(
        setup=lambda: sentinel,
        teardown=lambda context, result: received.append(context),
    )

    run_cases([case])

    assert received == [sentinel]


def test_async_hooks_are_awaited(monkeypatch):
    _install_fake_evals(monkeypatch)
    received = []

    async def setup():
        return "async-context"

    async def teardown(context, result):
        received.append((context, result.name))

    result = run_cases([_make_case(setup=setup, teardown=teardown)]).results[0]

    assert received == [("async-context", "sample_case")]
    assert result.passed is True


def test_async_callable_object_hooks_are_awaited(monkeypatch):
    # iscoroutinefunction is False for instances with async __call__ - the
    # returned coroutine must still be awaited, not dropped.
    _install_fake_evals(monkeypatch)
    received = []

    class AsyncSetup:
        async def __call__(self):
            return "object-context"

    class AsyncTeardown:
        async def __call__(self, context, result):
            received.append((context, result.name))

    result = run_cases([_make_case(setup=AsyncSetup(), teardown=AsyncTeardown())]).results[0]

    assert received == [("object-context", "sample_case")]
    assert result.passed is True


def test_sync_hook_returning_coroutine_is_awaited(monkeypatch):
    _install_fake_evals(monkeypatch)
    received = []

    async def async_cleanup(context, result):
        received.append(result.name)

    result = run_cases([_make_case(teardown=lambda context, result: async_cleanup(context, result))]).results[0]

    assert received == ["sample_case"]
    assert result.passed is True


def test_teardown_error_fails_case_but_suite_continues(monkeypatch):
    _install_fake_evals(monkeypatch)

    def bad_teardown(context, result):
        raise OSError("could not delete")

    cases = [
        _make_case(name="leaky", teardown=bad_teardown),
        _make_case(name="clean"),
    ]

    result = run_cases(cases)

    leaky, clean = result.results
    assert leaky.judge_passed is True
    assert leaky.error is not None
    assert "cleanup: OSError: could not delete" in leaky.error
    assert leaky.passed is False
    assert clean.passed is True


def test_setup_error_skips_body_and_teardown(monkeypatch):
    _install_fake_evals(monkeypatch)
    agent = StubAgent()
    teardown_calls = []

    def bad_setup():
        raise KeyError("missing fixture")

    case = _make_case(agent=agent, setup=bad_setup, teardown=lambda c, r: teardown_calls.append(c))

    result = run_cases([case]).results[0]

    assert result.error is not None
    assert result.error.startswith("setup: KeyError")
    assert result.passed is False
    assert agent.run_count == 0
    assert teardown_calls == []


# ---------------------------------------------------------------------------
# Check configuration patterns (check 7)
# ---------------------------------------------------------------------------


def test_judge_only_case(monkeypatch):
    _install_fake_evals(monkeypatch)

    result = run_cases([_make_case()]).results[0]

    assert result.judge_passed is True
    assert result.reliability_passed is None
    assert result.passed is True


def test_reliability_only_case(monkeypatch):
    _install_fake_evals(monkeypatch)
    case = _make_case(criteria=None, expected_tool_calls=("search_web",))

    result = run_cases([case]).results[0]

    assert result.judge_passed is None
    assert result.reliability_passed is True
    assert result.passed is True


def test_both_checks_case(monkeypatch):
    _install_fake_evals(monkeypatch, reliability_status="FAILED")
    case = _make_case(expected_tool_calls=("search_web",))

    result = run_cases([case]).results[0]

    assert result.judge_passed is True
    assert result.reliability_passed is False
    assert result.passed is False


def test_judge_error_becomes_case_error(monkeypatch):
    _install_fake_evals(monkeypatch, judge_error=ValueError("judge broke"))

    result = run_cases([_make_case()]).results[0]

    assert result.error is not None
    assert result.error.startswith("judge: ValueError")
    assert result.passed is False


def test_reliability_error_becomes_case_error(monkeypatch):
    _install_fake_evals(monkeypatch, reliability_error=ValueError("no messages"))
    case = _make_case(criteria=None, expected_tool_calls=("search_web",))

    result = run_cases([case]).results[0]

    assert result.error is not None
    assert result.error.startswith("reliability: ValueError")
    assert result.passed is False


# ---------------------------------------------------------------------------
# db and judge model propagation (checks 8, 12)
# ---------------------------------------------------------------------------


def test_db_propagates_to_both_evals(monkeypatch):
    judge_instances, reliability_instances = _install_fake_evals(monkeypatch)
    db = object()
    case = _make_case(expected_tool_calls=("search_web",))

    run_cases([case], db=db)

    assert judge_instances[0].kwargs["db"] is db
    assert reliability_instances[0].kwargs["db"] is db


def test_suite_disables_eval_spinners(monkeypatch):
    judge_instances, reliability_instances = _install_fake_evals(monkeypatch)

    run_cases([_make_case(expected_tool_calls=("search_web",))])

    assert judge_instances[0].kwargs["show_spinner"] is False
    assert reliability_instances[0].kwargs["show_spinner"] is False


def test_judge_model_resolution_order(monkeypatch):
    judge_instances, _ = _install_fake_evals(monkeypatch)
    case_model = object()
    suite_model = object()

    run_cases([_make_case(name="case_level", judge_model=case_model)], judge_model=suite_model)
    run_cases([_make_case(name="suite_level")], judge_model=suite_model)
    run_cases([_make_case(name="default")])

    assert judge_instances[0].kwargs["model"] is case_model
    assert judge_instances[1].kwargs["model"] is suite_model
    assert judge_instances[2].kwargs["model"] is None


def test_reliability_kwargs_forwarded(monkeypatch):
    _, reliability_instances = _install_fake_evals(monkeypatch)
    output = RunOutput(content="done")
    case = _make_case(
        agent=StubAgent(output=output),
        criteria=None,
        expected_tool_calls=("search_web", "summarize"),
        allow_additional_tool_calls=False,
    )

    run_cases([case])

    kwargs = reliability_instances[0].kwargs
    assert kwargs["agent_response"] is output
    assert kwargs["expected_tool_calls"] == ["search_web", "summarize"]
    assert kwargs["allow_additional_tool_calls"] is False


# ---------------------------------------------------------------------------
# JSON payload contract (check 9)
# ---------------------------------------------------------------------------


def test_to_dict_matches_contract(monkeypatch):
    _install_fake_evals(monkeypatch)
    output = RunOutput(content="Paris.", tools=[ToolExecution(tool_name="search_web")])
    case = _make_case(
        agent=StubAgent(id="geo-agent", output=output),
        name="capital_of_france",
        tags=("smoke", "release"),
        expected_tool_calls=("search_web",),
    )

    payload = run_cases([case]).to_dict()

    assert payload["summary"] == {"total": 1, "passed": 1, "failed": 0, "status": "PASS"}
    case_payload = payload["cases"][0]
    assert list(case_payload.keys()) == [
        "name",
        "agent_id",
        "tags",
        "session_id",
        "duration_seconds",
        "judge_passed",
        "judge_reason",
        "reliability_passed",
        "output",
        "tools_called",
        "timed_out",
        "passed",
        "error",
    ]
    assert case_payload["name"] == "capital_of_france"
    assert case_payload["agent_id"] == "geo-agent"
    assert case_payload["tags"] == ["smoke", "release"]
    assert case_payload["session_id"].startswith("eval-capital_of_france-")
    assert isinstance(case_payload["duration_seconds"], float)
    assert case_payload["judge_passed"] is True
    assert case_payload["judge_reason"] == "meets the criteria"
    assert case_payload["reliability_passed"] is True
    assert case_payload["output"] == "Paris."
    assert case_payload["tools_called"] == ["search_web"]
    assert case_payload["timed_out"] is False
    assert case_payload["passed"] is True
    assert case_payload["error"] is None
    json.dumps(payload)


def test_failed_suite_summary(monkeypatch):
    _install_fake_evals(monkeypatch, judge_passed=False)
    payload = run_cases([_make_case(name="a"), _make_case(name="b")]).to_dict()

    assert payload["summary"] == {"total": 2, "passed": 0, "failed": 2, "status": "FAIL"}


# ---------------------------------------------------------------------------
# Runner silence and single event loop (checks 10, 11)
# ---------------------------------------------------------------------------


def test_runner_writes_nothing_to_console(monkeypatch, capsys):
    _install_fake_evals(monkeypatch)
    case = _make_case(
        agent=StubAgent(events=[ToolCallStartedEvent(tool=ToolExecution(tool_name="search_web"))]),
        expected_tool_calls=("search_web",),
    )

    run_cases([case])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_run_cases_enters_asyncio_run_once(monkeypatch):
    _install_fake_evals(monkeypatch)
    calls = []
    original_run = asyncio.run

    def counting_run(coro, **kwargs):
        calls.append(1)
        return original_run(coro, **kwargs)

    monkeypatch.setattr(suite.asyncio, "run", counting_run)

    run_cases([_make_case(name="a"), _make_case(name="b"), _make_case(name="c")])

    assert len(calls) == 1


def test_all_cases_share_one_event_loop(monkeypatch):
    _install_fake_evals(monkeypatch)
    agent = StubAgent()
    cases = [_make_case(agent=agent, name="a"), _make_case(agent=agent, name="b")]

    run_cases(cases)

    assert len(agent.loops) == 2
    assert agent.loops[0] is agent.loops[1]


# ---------------------------------------------------------------------------
# Presentation hooks (check 14)
# ---------------------------------------------------------------------------


def test_on_run_event_receives_scripted_events_not_run_output(monkeypatch):
    _install_fake_evals(monkeypatch)
    started = ToolCallStartedEvent(tool=ToolExecution(tool_name="search_web"))
    completed = ToolCallCompletedEvent(tool=ToolExecution(tool_name="search_web"))
    case = _make_case(agent=StubAgent(events=[started, completed]))
    received = []

    run_cases([case], on_run_event=lambda c, e: received.append((c, e)))

    assert [event for _, event in received] == [started, completed]
    assert all(received_case is case for received_case, _ in received)
    assert not any(isinstance(event, RunOutput) for _, event in received)


def test_case_start_and_end_hooks(monkeypatch):
    _install_fake_evals(monkeypatch)
    cases = [_make_case(name="a"), _make_case(name="b")]
    started, ended = [], []

    run_cases(cases, on_case_start=lambda c: started.append(c.name), on_case_end=lambda r: ended.append(r.name))

    assert started == ["a", "b"]
    assert ended == ["a", "b"]


def test_on_run_event_error_recorded_once_and_checks_still_run(monkeypatch):
    # A presentation-hook bug must not read as an agent failure or abort the case.
    _install_fake_evals(monkeypatch)
    events = [
        ToolCallStartedEvent(tool=ToolExecution(tool_name="a")),
        ToolCallStartedEvent(tool=ToolExecution(tool_name="b")),
    ]
    forwarded = []

    def bad_hook(case, event):
        forwarded.append(event)
        raise TypeError("renderer bug")

    result = run_cases([_make_case(agent=StubAgent(events=events))], on_run_event=bad_hook).results[0]

    assert len(forwarded) == 1  # forwarding stops after the first failure
    assert result.error == "hook: on_run_event TypeError: renderer bug"
    assert result.judge_passed is True  # the judge check still ran
    assert result.passed is False


# ---------------------------------------------------------------------------
# Evidence fields (check 15)
# ---------------------------------------------------------------------------


def test_evidence_fields_and_response_exclusion(monkeypatch):
    _install_fake_evals(monkeypatch)
    output = RunOutput(
        content="Paris is the capital of France.",
        tools=[ToolExecution(tool_name="search_web"), ToolExecution(tool_name="summarize")],
    )
    agent = StubAgent(output=output)
    case = _make_case(agent=agent, name="capital")

    suite_result = run_cases([case])
    result = suite_result.results[0]

    assert result.response is output
    assert result.output == "Paris is the capital of France."
    assert result.tools_called == ("search_web", "summarize")
    assert result.session_id.startswith("eval-capital-")
    assert agent.session_ids == [result.session_id]

    case_payload = suite_result.to_dict()["cases"][0]
    assert case_payload["output"] == "Paris is the capital of France."
    assert case_payload["tools_called"] == ["search_web", "summarize"]
    assert case_payload["judge_reason"] == "meets the criteria"
    assert case_payload["session_id"] == result.session_id
    assert "response" not in case_payload


def test_structured_content_serialized_without_repr(monkeypatch):
    _install_fake_evals(monkeypatch)

    result = run_cases([_make_case(agent=StubAgent(output=RunOutput(content={"answer": 42})))]).results[0]

    assert result.output == '{"answer": 42}'


def test_falsy_content_is_preserved(monkeypatch):
    _install_fake_evals(monkeypatch)

    result = run_cases([_make_case(agent=StubAgent(output=RunOutput(content=0)))]).results[0]

    assert result.output == "0"


# ---------------------------------------------------------------------------
# CLI (check 10)
# ---------------------------------------------------------------------------


def test_cli_exit_zero_when_all_pass(monkeypatch, capsys):
    _install_fake_evals(monkeypatch)

    exit_code = cli([_make_case()], argv=[])

    assert exit_code == 0
    assert "1/1 passed" in capsys.readouterr().out


def test_cli_exit_one_on_failure(monkeypatch, capsys):
    _install_fake_evals(monkeypatch, judge_passed=False)

    exit_code = cli([_make_case()], argv=[])

    assert exit_code == 1
    assert "1 failed" in capsys.readouterr().out


def test_cli_exit_two_when_no_cases_match(monkeypatch, capsys):
    _install_fake_evals(monkeypatch)
    agent = StubAgent()

    exit_code = cli([_make_case(agent=agent, name="only_case")], argv=["--tag", "nope"])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "no cases selected" in output
    assert "only_case" in output
    assert agent.run_count == 0


def test_cli_list_runs_nothing(monkeypatch, capsys):
    _install_fake_evals(monkeypatch)
    agent = StubAgent()

    exit_code = cli([_make_case(agent=agent, name="listed_case")], argv=["--list"])

    assert exit_code == 0
    assert "listed_case" in capsys.readouterr().out
    assert agent.run_count == 0


def test_cli_json_output_writes_payload(monkeypatch, tmp_path):
    _install_fake_evals(monkeypatch)
    json_path = tmp_path / "reports" / "evals.json"

    exit_code = cli([_make_case(name="json_case")], argv=["--json-output", str(json_path)])

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"] == {"total": 1, "passed": 1, "failed": 0, "status": "PASS"}
    assert payload["cases"][0]["name"] == "json_case"


def test_cli_verbose_renders_response_post_hoc(monkeypatch):
    _install_fake_evals(monkeypatch)
    output = RunOutput(content="verbose output")
    rendered = []
    monkeypatch.setattr("agno.utils.pprint.pprint_run_response", lambda response, **kwargs: rendered.append(response))

    exit_code = cli([_make_case(agent=StubAgent(output=output))], argv=["-v"])

    assert exit_code == 0
    assert rendered == [output]


def test_cli_timeout_flag_sets_default_timeout(monkeypatch, capsys):
    _install_fake_evals(monkeypatch)

    exit_code = cli([_make_case(agent=StubAgent(delay=5.0))], argv=["--timeout", "1"])

    assert exit_code == 1
    assert "timeout: exceeded 1s" in capsys.readouterr().out


def test_cli_list_with_json_output_writes_case_list(monkeypatch, tmp_path):
    _install_fake_evals(monkeypatch)
    agent = StubAgent()
    json_path = tmp_path / "cases.json"

    exit_code = cli(
        [_make_case(agent=agent, name="listed", tags=("smoke",), timeout_seconds=30)],
        argv=["--list", "--json-output", str(json_path)],
    )

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload == {
        "cases": [{"name": "listed", "agent_id": "stub-agent", "tags": ["smoke"], "timeout_seconds": 30}]
    }
    assert agent.run_count == 0


def test_cli_survives_rich_markup_in_model_output(monkeypatch, capsys):
    # Model- and user-derived strings must not be parsed as rich markup: a stray
    # closing tag raised MarkupError and killed the suite after the case passed.
    _install_fake_evals(monkeypatch, judge_reason="reason with [/dim] tag")
    output = RunOutput(
        content="model said [/dim] oops [bold]",
        tools=[ToolExecution(tool_name="tool [/red] name")],
    )
    case = _make_case(agent=StubAgent(output=output), name="markup [case]")

    exit_code = cli([case], argv=[])

    assert exit_code == 0
    assert "model said" in capsys.readouterr().out


def test_acli_returns_exit_code(monkeypatch, capsys):
    _install_fake_evals(monkeypatch)

    exit_code = asyncio.run(acli([_make_case()], argv=[]))

    assert exit_code == 0
    assert "1/1 passed" in capsys.readouterr().out


def test_acli_runs_inside_existing_event_loop(monkeypatch):
    _install_fake_evals(monkeypatch)

    async def main():
        return await acli([_make_case()], argv=[])

    assert asyncio.run(main()) == 0


# ---------------------------------------------------------------------------
# python -m agno.eval entry
# ---------------------------------------------------------------------------


def test_module_entry_loads_cases_and_forwards_flags(monkeypatch, tmp_path, capsys):
    _install_fake_evals(monkeypatch)
    (tmp_path / "fake_eval_cases.py").write_text(
        "from agno.eval.suite import Case\n"
        "\n"
        "\n"
        "class _Agent:\n"
        "    id = 'module-agent'\n"
        "\n"
        "\n"
        "CASES = (Case(name='module_case', agent=_Agent(), input='q', criteria='ok'),)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    from agno.eval.__main__ import main

    assert main(["fake_eval_cases", "--list"]) == 0
    assert "module_case" in capsys.readouterr().out
    assert main(["missing_module_xyz"]) == 2
    assert main(["fake_eval_cases:NOPE"]) == 2
    assert main([]) == 2
