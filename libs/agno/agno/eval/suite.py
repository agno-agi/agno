"""Eval suite runner: declare `Case`s, run them with `run_cases`/`arun_cases`, ship a CLI with `cli`.

A `Case` is one input to one agent or team plus optional checks (`AgentAsJudgeEval` via
`criteria`, `ReliabilityEval` via `expected_tool_calls`). The runner executes the
selected cases sequentially on a single event loop and returns a `SuiteResult`
whose `to_dict()` payload is a stable contract for CI consumers.

The runner performs no console I/O: presentation flows through the
`on_case_start` / `on_run_event` / `on_case_end` hooks. `cli()` (and its async
twin `acli()`) is a pure consumer of that public API.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from inspect import isawaitable, iscoroutine, iscoroutinefunction
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple, Union, cast
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.eval.reliability import ReliabilityEval
from agno.models.base import Model
from agno.run.agent import RunErrorEvent, RunOutput, RunOutputEvent
from agno.run.base import RunStatus
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowErrorEvent
from agno.team.team import Team

if TYPE_CHECKING:
    from rich.console import Console
    from rich.status import Status

__all__ = [
    "Case",
    "CaseResult",
    "JudgeMode",
    "SuiteResult",
    "acli",
    "arun_cases",
    "cli",
    "run_cases",
]


class JudgeMode(str, Enum):
    """How the judge grades a Case's answer. A str-enum whose values match AgentAsJudgeEval's
    scoring_strategy; the equal string (e.g. "numeric") is accepted too."""

    BINARY = "binary"  # a pass/fail verdict
    NUMERIC = "numeric"  # a 1-10 score, passes when it meets judge_threshold


@dataclass(frozen=True)
class Case:
    """One eval case: an input to one agent or team, plus optional judge/reliability checks."""

    name: str
    input: str
    # The agent or team under test: pass exactly one of agent= or team= (separate fields,
    # mirroring AccuracyEval, so a Team never rides in a param named 'agent'). A Team routes
    # reliability through team_response=.
    agent: Optional[Agent] = None
    team: Optional[Team] = None
    tags: Tuple[str, ...] = ()
    # Per-case timeout in seconds; falls back to the runner's default_timeout
    timeout_seconds: Optional[int] = None

    # Judge check - set `criteria` to enable AgentAsJudgeEval. Verdict is binary pass/fail by
    # default; set judge_mode=JudgeMode.NUMERIC for a 1-10 score gated on judge_threshold.
    criteria: Optional[str] = None
    # Per-case judge model override; falls back to the runner's judge_model=,
    # then AgentAsJudgeEval's default
    judge_model: Optional[Model] = None
    # Judge scoring mode. BINARY is a pass/fail verdict; NUMERIC grades 1-10 and passes when the
    # score meets judge_threshold.
    judge_mode: JudgeMode = JudgeMode.BINARY
    # Pass bar for numeric scoring (1-10); read only when judge_mode is NUMERIC.
    judge_threshold: int = 7

    # Reliability check - set `expected_tool_calls` to enable ReliabilityEval.
    expected_tool_calls: Optional[Tuple[str, ...]] = None
    allow_additional_tool_calls: bool = True

    # Lifecycle hooks. setup runs before the run (outside the timeout); its return
    # value ("context") is passed to teardown. teardown always runs once setup has
    # completed (pass, fail, error, timeout) and receives (context, result) so it can
    # inspect result.error / result.timed_out. Sync callables run via
    # asyncio.to_thread; async callables are awaited.
    setup: Optional[Callable[[], Any]] = None
    teardown: Optional[Callable[[Any, "CaseResult"], Any]] = None

    def __post_init__(self) -> None:
        # Exactly one of agent/team: neither has anything to run, both is ambiguous.
        if self.agent is None and self.team is None:
            raise ValueError(f"case {self.name!r}: provide one of 'agent' or 'team'")
        if self.agent is not None and self.team is not None:
            raise ValueError(f"case {self.name!r}: provide only one of 'agent' or 'team'")
        # Truthiness, not `is None`: criteria="" or expected_tool_calls=() would
        # otherwise construct a case whose checks pass vacuously - a green CI gate
        # that verified nothing.
        if not self.criteria and not self.expected_tool_calls:
            raise ValueError(f"case {self.name!r} has no checks: set criteria and/or expected_tool_calls")
        # A raw string bypasses the JudgeMode type, so reject an unknown mode and, for NUMERIC, a
        # judge_threshold outside 1-10. Membership accepts the enum members and their equal strings.
        if self.judge_mode not in (JudgeMode.BINARY, JudgeMode.NUMERIC):
            raise ValueError(f"case {self.name!r}: judge_mode must be a JudgeMode, got {self.judge_mode!r}")
        if self.judge_mode == JudgeMode.NUMERIC and not 1 <= self.judge_threshold <= 10:
            raise ValueError(f"case {self.name!r}: judge_threshold must be 1-10, got {self.judge_threshold}")


@dataclass
class CaseResult:
    """Outcome of one case, with enough evidence to debug a failure from the payload alone."""

    name: str
    tags: Tuple[str, ...]
    # Split like AccuracyEval: agent_id for an agent case, team_id for a team; the other
    # stays None.
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    # The generated eval session id - links the case to its stored session/trace when
    # db= is set. Empty for skipped cases: no session was created.
    session_id: str = ""
    duration_seconds: float = 0.0
    judge_passed: Optional[bool] = None  # None = check not configured
    judge_reason: Optional[str] = None  # the judge's stated reason, when available
    judge_score: Optional[int] = None  # numeric-mode score (1-10); None in binary mode
    reliability_passed: Optional[bool] = None  # None = check not configured
    output: Optional[str] = None  # response text - what the judge graded
    tools_called: Tuple[str, ...] = ()  # tool names fired during the run, in order
    timed_out: bool = False
    # True for cases the suite never ran (appended after a cancelled-run abort)
    skipped: bool = False
    # Run error, judge/reliability error, teardown error - "; "-joined
    error: Optional[str] = None
    # Raw run output - full programmatic access to content, tool calls, metrics.
    # Excluded from to_dict(). A team case stores its TeamRunOutput.
    response: Optional[Union[RunOutput, TeamRunOutput]] = None

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        checks = [c for c in (self.judge_passed, self.reliability_passed) if c is not None]
        return bool(checks) and all(checks)


@dataclass
class SuiteResult:
    """Results of a suite run. The summary is derived from the per-case results."""

    results: List[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def status(self) -> str:
        # An empty suite fails: CI gates compare == "PASS", and a typo'd tag must
        # not green-light a release having run nothing.
        if not self.results:
            return "FAIL"
        return "PASS" if self.passed == self.total else "FAIL"

    def to_dict(self) -> Dict[str, Any]:
        """Machine-readable payload. This shape is a contract parsed by CI consumers."""
        return {
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "status": self.status,
            },
            "cases": [
                {
                    "name": result.name,
                    "agent_id": result.agent_id,
                    "team_id": result.team_id,
                    "tags": list(result.tags),
                    "session_id": result.session_id,
                    "duration_seconds": result.duration_seconds,
                    "judge_passed": result.judge_passed,
                    "judge_reason": result.judge_reason,
                    "judge_score": result.judge_score,
                    "reliability_passed": result.reliability_passed,
                    "output": result.output,
                    "tools_called": list(result.tools_called),
                    "timed_out": result.timed_out,
                    "skipped": result.skipped,
                    "passed": result.passed,
                    "error": result.error,
                }
                for result in self.results
            ],
        }


# Team and workflow runs yield their own error event classes (no shared base or
# is_error marker with the agent's) - match all three so the team/workflow
# fast-follows cannot silently reintroduce error loss. If run/base.py ever grows
# an is_error property (mirroring is_cancelled), switch to that.
_RUN_ERROR_EVENTS = (RunErrorEvent, TeamRunErrorEvent, WorkflowErrorEvent)

# Keyed by non-completed status; the "agent"/"team" label is prefixed at use.
_STATUS_ERRORS = {
    RunStatus.paused: "run paused awaiting user input",
    RunStatus.cancelled: "run cancelled",
    RunStatus.error: "run ended in error status",
}


def _component_id(case: Case) -> str:
    # Exactly one of agent/team is set (enforced at construction); fall back to the case name.
    if case.agent is not None:
        return case.agent.id or case.name
    if case.team is not None:
        return case.team.id or case.name
    return case.name


def _case_matches(case: Case, *, tag: Optional[str], name: Optional[str]) -> bool:
    if name is not None and case.name != name:
        return False
    if tag is not None and tag not in case.tags:
        return False
    return True


def _append_error(result: CaseResult, message: str) -> None:
    result.error = "; ".join(part for part in (result.error, message) if part)


def _tool_names(response: Union[RunOutput, TeamRunOutput]) -> Tuple[str, ...]:
    """Tool names fired during the run, in order. A team's members keep their calls in
    member_responses, so collect one level down - otherwise only the leader's
    delegate_task_to_member shows, not the member's real tool."""
    names = [tool.tool_name or "?" for tool in (response.tools or [])]
    for member in getattr(response, "member_responses", None) or []:
        names.extend(tool.tool_name or "?" for tool in (member.tools or []))
    return tuple(names)


def _extract_evidence(result: CaseResult, response: Union[RunOutput, TeamRunOutput]) -> None:
    """Copy the payload evidence fields (output, tools_called) off the run output."""
    try:
        result.output = response.get_content_as_string() if response.content is not None else ""
    except Exception:
        # get_content_as_string json-serializes non-str content and raises on
        # values json can't handle (datetime, bytes, ...) - fall back to repr
        # rather than failing the case on evidence extraction.
        result.output = str(response.content)
    result.tools_called = _tool_names(response)


async def _call_hook(hook: Callable[..., Any], *args: Any) -> Any:
    if iscoroutinefunction(hook):
        return await hook(*args)
    result = await asyncio.to_thread(hook, *args)
    if isawaitable(result):
        # Async callable objects and sync wrappers returning a coroutine land here:
        # iscoroutinefunction misses both, so await the result back on the loop
        # instead of silently dropping an un-awaited coroutine.
        return await result
    return result


def _call_presentation_hook(hook: Callable[..., Any], *args: Any) -> None:
    """Presentation hooks are sync-only: they run inline on the event loop.

    An async hook would return a coroutine that never executes - no rendering, no
    error, just a GC-time warning. Since setup/teardown DO await async callables,
    users will assume symmetry: surface the mistake as a hook error instead.
    """
    result = hook(*args)
    if iscoroutine(result):
        result.close()
        raise TypeError("presentation hooks must be sync callables; use setup/teardown for async work")


async def _run_case_body(
    case: Case,
    result: CaseResult,
    *,
    judge_model: Optional[Model],
    db: Optional[Union[BaseDb, AsyncBaseDb]],
    on_run_event: Optional[Callable[[Case, RunOutputEvent], None]],
) -> None:
    """Run the agent or team, then judge + reliability checks. Runs inside the case timeout; mutates result."""
    response: Optional[Union[RunOutput, TeamRunOutput]] = None
    component_errored = False
    # Pick the agent or team under test (exactly one is set) and label it for error messages.
    if case.agent is not None:
        runner: Union[Agent, Team] = case.agent
        component_label = "agent"
    else:
        runner = case.team  # type: ignore[assignment]
        component_label = "team"
    forward_events = on_run_event is not None
    try:
        async for event in runner.arun(
            input=case.input,
            stream=True,
            stream_events=True,
            yield_run_output=True,
            session_id=result.session_id,
        ):
            if isinstance(event, (RunOutput, TeamRunOutput)):
                # The final run output arrives in-stream (yield_run_output=True). It is
                # captured, not forwarded to on_run_event - on_case_end delivers it.
                # Response AND evidence fields are committed immediately: the stream can
                # stall after the final output (e.g. a hung telemetry call in transport
                # cleanup) and a timeout then must not discard what the run produced.
                response = event
                result.response = event
                _extract_evidence(result, event)
                continue
            if isinstance(event, _RUN_ERROR_EVENTS):
                # The streaming path does not raise on in-run model/API failures: it
                # yields an error event and ends without the final RunOutput. Recorded
                # at capture time so a later timeout cannot discard it.
                component_errored = True
                # Agent/team error events carry the message in .content, the
                # workflow's in .error
                error_text = getattr(event, "content", None) or getattr(event, "error", None) or "unknown error"
                error_type = getattr(event, "error_type", None)
                if error_type:
                    error_text = f"{error_type}: {error_text}"
                _append_error(result, f"{component_label}: {error_text}")
            if forward_events and on_run_event is not None:
                try:
                    _call_presentation_hook(on_run_event, case, event)
                except Exception as exc:
                    # A presentation-hook bug must not read as a run failure: record
                    # it once and stop forwarding for the rest of this case.
                    forward_events = False
                    _append_error(result, f"hook: on_run_event {type(exc).__name__}: {exc}")
    except Exception as exc:
        # Only pre-stream failures (e.g. input validation) raise out of arun.
        _append_error(result, f"{component_label}: {type(exc).__name__}: {exc}")
        return

    # Only a completed run is gradeable: paused/cancelled runs carry placeholder
    # content (e.g. HITL boilerplate), and any other status (pending, running,
    # regenerated, ...) is not a real answer either.
    gradeable = not component_errored and response is not None and response.status == RunStatus.completed
    if not gradeable:
        if not component_errored:
            if response is None:
                _append_error(result, f"{component_label}: no run output recorded")
            else:
                _append_error(
                    result,
                    # `or` instead of a .get() default: the default is evaluated eagerly,
                    # and a duck-typed agent or team may yield status=None (no .value).
                    f"{component_label}: "
                    + (
                        _STATUS_ERRORS.get(response.status)
                        or f"run ended with status {getattr(response.status, 'value', response.status)}"
                    ),
                )
        return

    if case.criteria:
        try:
            judge = await AgentAsJudgeEval(
                name=case.name,
                criteria=case.criteria,
                # Numeric mode grades 1-10 and derives passed = score >= threshold itself, so the
                # verdict still gates cleanly; binary mode ignores threshold.
                # cast the str-enum to the Literal scoring_strategy declares; the value is unchanged.
                scoring_strategy=cast(Literal["binary", "numeric"], case.judge_mode),
                threshold=case.judge_threshold,
                model=case.judge_model or judge_model,
                db=db,
                show_spinner=False,
                # The eval awaits its telemetry POST before returning; on a blackholed
                # network that burns case-timeout budget after the verdict is computed.
                telemetry=False,
            ).arun(input=case.input, output=result.output or "")
        except Exception as exc:
            _append_error(result, f"judge: {type(exc).__name__}: {exc}")
        else:
            if judge is not None and judge.results:
                result.judge_passed = judge.results[0].passed
                result.judge_reason = judge.results[0].reason or None
                # None in binary mode; the 1-10 number in numeric mode, kept so a payload can
                # track quality drift a bare pass/fail would hide.
                result.judge_score = getattr(judge.results[0], "score", None)
            else:
                _append_error(result, "judge: returned no result")

    if case.expected_tool_calls:
        # A team's real tool calls live in nested member runs; ReliabilityEval merges those via
        # team_response= (agent_response= sees only the top-level messages - a team leader's
        # delegation).
        try:
            reliability = await ReliabilityEval(
                name=case.name,
                agent_response=response if isinstance(response, RunOutput) else None,
                team_response=response if isinstance(response, TeamRunOutput) else None,
                expected_tool_calls=list(case.expected_tool_calls),
                allow_additional_tool_calls=case.allow_additional_tool_calls,
                db=db,
                show_spinner=False,
                telemetry=False,
            ).arun()
        except Exception as exc:
            _append_error(result, f"reliability: {type(exc).__name__}: {exc}")
        else:
            if reliability is None:
                _append_error(result, "reliability: returned no result")
            else:
                result.reliability_passed = reliability.eval_status == "PASSED"


async def _arun_case(
    case: Case,
    *,
    default_timeout: int,
    judge_model: Optional[Model],
    db: Optional[Union[BaseDb, AsyncBaseDb]],
    on_run_event: Optional[Callable[[Case, RunOutputEvent], None]],
) -> CaseResult:
    start = time.perf_counter()
    result = CaseResult(
        name=case.name,
        tags=case.tags,
        agent_id=_component_id(case) if case.agent is not None else None,
        team_id=_component_id(case) if case.team is not None else None,
        # Dedicated session per case so eval traffic doesn't pollute the agent or team's history
        session_id=f"eval-{case.name}-{uuid4().hex[:8]}",
    )
    timeout = case.timeout_seconds if case.timeout_seconds is not None else default_timeout

    context: Any = None
    setup_completed = True
    if case.setup is not None:
        try:
            context = await _call_hook(case.setup)
        except Exception as exc:
            _append_error(result, f"setup: {type(exc).__name__}: {exc}")
            setup_completed = False

    if setup_completed:
        try:
            try:
                await asyncio.wait_for(
                    _run_case_body(case, result, judge_model=judge_model, db=db, on_run_event=on_run_event),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                result.timed_out = True
                _append_error(result, f"timeout: exceeded {timeout}s")
        finally:
            # Teardown runs even on timeout/error - a mutation may have landed before
            # the clock ran out. A teardown failure must be visible in the payload,
            # not only on a console.
            if case.teardown is not None:
                try:
                    await _call_hook(case.teardown, context, result)
                except Exception as exc:
                    _append_error(result, f"cleanup: {type(exc).__name__}: {exc}")

    result.duration_seconds = round(time.perf_counter() - start, 3)
    return result


async def arun_cases(
    cases: Sequence[Case],
    *,
    tag: Optional[str] = None,
    name: Optional[str] = None,
    default_timeout: int = 120,
    judge_model: Optional[Model] = None,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    on_case_start: Optional[Callable[[Case], None]] = None,
    on_case_end: Optional[Callable[[Case, CaseResult], None]] = None,
    on_run_event: Optional[Callable[[Case, RunOutputEvent], None]] = None,
) -> SuiteResult:
    """Run the selected cases sequentially and return a SuiteResult.

    Args:
        cases: The cases to select from.
        tag: Keep only cases with this tag.
        name: Keep only the case with this name.
        default_timeout: Per-case timeout in seconds, when Case.timeout_seconds is None.
        judge_model: Suite-wide default judge model; Case.judge_model overrides it.
        db: Passed to AgentAsJudgeEval/ReliabilityEval so results log to storage.
        on_case_start: Presentation hook, called before each case runs.
        on_case_end: Presentation hook, called with each case and its CaseResult -
            including the skipped cases appended after an abort (result.skipped=True),
            so hook-driven reporters and to_dict() agree on the case count.
        on_run_event: Presentation hook, called with every streamed run event.

    Performs no console I/O - all presentation flows through the hooks. Hooks are
    plain sync callables invoked on the event loop; keep them fast. A hook that
    raises (or an async hook, which is rejected) is recorded on the case
    ("hook: ..." error) without aborting the suite.

    A cancelled run aborts the suite: the unrun cases are recorded as failed with a
    "skipped: ..." error so the payload still accounts for every selected case. This
    fires on a cancelled RunOutput - a server-side cancel_run, or a KeyboardInterrupt
    agno converts into one.
    """
    selected = [case for case in cases if _case_matches(case, tag=tag, name=name)]

    results: List[CaseResult] = []
    for case in selected:
        start_hook_error: Optional[str] = None
        if on_case_start is not None:
            try:
                _call_presentation_hook(on_case_start, case)
            except Exception as exc:
                start_hook_error = f"hook: on_case_start {type(exc).__name__}: {exc}"
        result = await _arun_case(
            case,
            default_timeout=default_timeout,
            judge_model=judge_model,
            db=db,
            on_run_event=on_run_event,
        )
        if start_hook_error:
            _append_error(result, start_hook_error)
        results.append(result)
        if on_case_end is not None:
            try:
                _call_presentation_hook(on_case_end, case, result)
            except Exception as exc:
                _append_error(result, f"hook: on_case_end {type(exc).__name__}: {exc}")
        if result.response is not None and result.response.status == RunStatus.cancelled:
            # A server-side cancel_run (and a KeyboardInterrupt agno converts into a cancelled
            # RunOutput) surfaces as status=cancelled - stop here rather than marching through
            # the remaining cases. A terminal Ctrl-C under asyncio.run instead propagates
            # CancelledError, which unwinds the suite before reaching this branch.
            break

    # The unrun remainder (non-empty only after a cancelled-run abort; the cancelled
    # case's own result was appended before the break) stays visible everywhere a run
    # case would be: in the payload AND through on_case_end, so hook-driven reporters
    # cannot silently disagree with to_dict() about the case count.
    for case in selected[len(results) :]:
        result = CaseResult(
            name=case.name,
            tags=case.tags,
            agent_id=_component_id(case) if case.agent is not None else None,
            team_id=_component_id(case) if case.team is not None else None,
            skipped=True,
            error="skipped: suite aborted after cancelled run",
        )
        results.append(result)
        if on_case_end is not None:
            try:
                _call_presentation_hook(on_case_end, case, result)
            except Exception as exc:
                _append_error(result, f"hook: on_case_end {type(exc).__name__}: {exc}")

    # Some toolkit transports schedule async close work after a case finishes.
    # Yielding once before the loop closes avoids "event loop is closed" noise.
    await asyncio.sleep(0)
    return SuiteResult(results=results)


def run_cases(
    cases: Sequence[Case],
    *,
    tag: Optional[str] = None,
    name: Optional[str] = None,
    default_timeout: int = 120,
    judge_model: Optional[Model] = None,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    on_case_start: Optional[Callable[[Case], None]] = None,
    on_case_end: Optional[Callable[[Case, CaseResult], None]] = None,
    on_run_event: Optional[Callable[[Case, RunOutputEvent], None]] = None,
) -> SuiteResult:
    """Sync wrapper over arun_cases. The whole suite runs on a single event loop."""
    return asyncio.run(
        arun_cases(
            cases,
            tag=tag,
            name=name,
            default_timeout=default_timeout,
            judge_model=judge_model,
            db=db,
            on_case_start=on_case_start,
            on_case_end=on_case_end,
            on_run_event=on_run_event,
        )
    )


class _CliRenderer:
    """Console UI for cli(), driven entirely by the public runner hooks.

    All model- and user-derived strings (case names, outputs, tool names, judge
    reasons, errors) are markup-escaped: a model emitting rich tags like [/dim]
    must not crash or restyle the console.
    """

    def __init__(self, console: "Console", total: int, verbose: bool) -> None:
        self._console = console
        self._total = total
        self._verbose = verbose
        self._index = 0
        self._status: Optional["Status"] = None
        self._base_label = ""

    def on_case_start(self, case: Case) -> None:
        from rich.markup import escape
        from rich.status import Status

        self._index += 1
        self._console.rule(
            f"[bold]{escape(case.name)}[/bold]  [dim]{escape(_component_id(case))} · {self._index}/{self._total}[/dim]"
        )
        self._base_label = f"[bold]running[/bold] {escape(_component_id(case))}…"
        self._status = Status(self._base_label, console=self._console, spinner="dots")
        self._status.start()

    def on_run_event(self, case: Case, event: RunOutputEvent) -> None:
        from rich.markup import escape

        if self._status is None:
            return
        event_type = getattr(event, "event", None)
        if event_type == "ToolCallStarted":
            tool = getattr(event, "tool", None)
            tool_name = getattr(tool, "tool_name", None)
            if tool_name:
                self._status.update(
                    f"[bold]running[/bold] {escape(_component_id(case))} → [cyan]{escape(tool_name)}[/cyan]…"
                )
        elif event_type == "ToolCallCompleted":
            self._status.update(self._base_label)

    def close(self) -> None:
        """Stop the active spinner, restoring the terminal. Safe to call repeatedly."""
        if self._status is not None:
            self._status.stop()
            self._status = None

    def on_case_end(self, case: Case, result: CaseResult) -> None:
        from rich.markup import escape

        self.close()
        if result.skipped:
            # Skipped cases never started, so there is no rule header or response
            # to render - one compact line each keeps the abort visible.
            self._console.print(f"[dim]skipped:[/dim] {escape(result.name)}")
            return
        if self._verbose and result.response is not None:
            from agno.utils.pprint import pprint_run_response

            pprint_run_response(result.response, markdown=True)
            self._console.print(f"[dim]session: {escape(result.session_id)} · {result.duration_seconds}s[/dim]")
        else:
            self._print_response(result)
        self._print_verdicts(case, result)

    def _print_response(self, result: CaseResult) -> None:
        from rich.markup import escape

        self._console.print()
        self._console.print("[bold]Response[/bold]")
        if result.output:
            self._console.print(result.output, markup=False)
        else:
            self._console.print("[dim](empty)[/dim]")
        if result.tools_called:
            names = ", ".join(result.tools_called)
            self._console.print(f"\n[dim]tools fired:[/dim] {escape(names)}")

    def _print_verdicts(self, case: Case, result: CaseResult) -> None:
        from rich.markup import escape

        if result.judge_passed is not None:
            style = "green" if result.judge_passed else "red"
            verdict = "PASS" if result.judge_passed else "FAIL"
            self._console.print(f"\n[bold]Judge:[/bold] [{style}]{verdict}[/{style}]")
            if result.judge_reason:
                self._console.print(f"[dim]  {escape(result.judge_reason)}[/dim]")
        if result.reliability_passed is not None:
            style = "green" if result.reliability_passed else "red"
            verdict = "PASS" if result.reliability_passed else "FAIL"
            line = f"\n[bold]Reliability:[/bold] [{style}]{verdict}[/{style}]"
            if case.expected_tool_calls:
                expected = ", ".join(case.expected_tool_calls)
                line += f"  [dim]expected: {escape(expected)}[/dim]"
            self._console.print(line)
        if result.error:
            self._console.print(f"\n[red]error:[/red] {escape(result.error)}")


def _check_cell(passed: Optional[bool]) -> str:
    if passed is None:
        return "[dim]—[/dim]"
    style = "green" if passed else "red"
    verdict = "PASS" if passed else "FAIL"
    return f"[{style}]{verdict}[/{style}]"


def _print_case_list(console: "Console", cases: Sequence[Case], *, default_timeout: int) -> None:
    from rich.markup import escape
    from rich.table import Table

    table = Table(title="Eval Cases", title_style="bold sky_blue1", show_header=True, header_style="bold")
    table.add_column("Case", overflow="fold")
    table.add_column("Component")
    table.add_column("Tags")
    table.add_column("Timeout")
    for case in cases:
        timeout = case.timeout_seconds if case.timeout_seconds is not None else default_timeout
        table.add_row(escape(case.name), escape(_component_id(case)), escape(", ".join(case.tags)), str(timeout))
    console.print(table)


def _print_summary(console: "Console", suite: SuiteResult) -> None:
    from rich.markup import escape
    from rich.table import Table

    table = Table(title="Eval Summary", title_style="bold sky_blue1", show_header=True, header_style="bold")
    table.add_column("Case", overflow="fold")
    table.add_column("Judge")
    table.add_column("Reliability")
    table.add_column("Status")
    for result in suite.results:
        status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        table.add_row(
            escape(result.name), _check_cell(result.judge_passed), _check_cell(result.reliability_passed), status
        )

    console.print()
    console.print(table)

    summary = f"[green]{suite.passed}/{suite.total} passed[/green]"
    if suite.failed:
        summary += f", [red]{suite.failed} failed[/red]"
    console.print(f"\n{summary}")

    for result in suite.results:
        if result.error:
            console.print(f"  [dim]{escape(result.name)}:[/dim] [red]{escape(result.error)}[/red]")


def _write_json_output(console: "Console", path: Path, payload: Dict[str, Any]) -> bool:
    """Write the JSON payload and echo the path; returns False on a write failure.

    A bad --json-output path must be a clean error line and a failing exit code,
    not a traceback through cli().
    """
    from rich.markup import escape

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]error:[/red] cannot write json output to {escape(str(path))}: {escape(str(exc))}")
        return False
    console.print(f"[dim]json output:[/dim] {escape(str(path))}")
    return True


async def acli(
    cases: Sequence[Case],
    *,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    judge_model: Optional[Model] = None,
    default_timeout: int = 120,
    argv: Optional[Sequence[str]] = None,
) -> int:
    """Async variant of cli() for callers already inside an event loop."""
    import argparse

    from rich.console import Console
    from rich.markup import escape

    parser = argparse.ArgumentParser(description="Run the eval suite, or a subset with --name/--tag.")
    parser.add_argument("--name", default=None, help="Run only the case with this name")
    parser.add_argument("--tag", default=None, help="Run only cases with this tag")
    parser.add_argument("--timeout", type=int, default=default_timeout, help="Default per-case timeout in seconds")
    parser.add_argument("--json-output", type=Path, default=None, help="Write machine-readable JSON results")
    parser.add_argument(
        "--list", action="store_true", dest="list_cases", help="List selected cases without running them"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Render the full run panels (Message, Tool Calls, Response) after each case",
    )
    try:
        args = parser.parse_args(argv if argv is None else list(argv))
    except SystemExit as exc:
        # argparse exits on --help and usage errors; return the code instead of
        # letting SystemExit tear through a host event loop (server, notebook).
        return exc.code if isinstance(exc.code, int) else 2

    console = Console()
    selected = [case for case in cases if _case_matches(case, tag=args.tag, name=args.name)]
    if not selected:
        console.print(f"[red]no cases selected[/red] {escape(f'(name={args.name!r}, tag={args.tag!r})')}")
        console.print(f"  [dim]available:[/dim] {escape(', '.join(case.name for case in cases))}")
        return 2

    if args.list_cases:
        _print_case_list(console, selected, default_timeout=args.timeout)
        if args.json_output is not None:
            payload = {
                "cases": [
                    {
                        "name": case.name,
                        "agent_id": _component_id(case) if case.agent is not None else None,
                        "team_id": _component_id(case) if case.team is not None else None,
                        "tags": list(case.tags),
                        "timeout_seconds": case.timeout_seconds if case.timeout_seconds is not None else args.timeout,
                    }
                    for case in selected
                ]
            }
            if not _write_json_output(console, args.json_output, payload):
                return 1
        return 0

    renderer = _CliRenderer(console=console, total=len(selected), verbose=args.verbose)
    try:
        suite = await arun_cases(
            selected,
            default_timeout=args.timeout,
            judge_model=judge_model,
            db=db,
            on_case_start=renderer.on_case_start,
            on_case_end=renderer.on_case_end,
            on_run_event=renderer.on_run_event,
        )
    finally:
        # Restore the terminal (stop the spinner) even on error or Ctrl-C.
        renderer.close()

    _print_summary(console, suite)

    if args.json_output is not None and not _write_json_output(console, args.json_output, suite.to_dict()):
        return 1

    return 0 if suite.failed == 0 else 1


def cli(
    cases: Sequence[Case],
    *,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    judge_model: Optional[Model] = None,
    default_timeout: int = 120,
    argv: Optional[Sequence[str]] = None,
) -> int:
    """Run an argparse CLI over the given cases and return the exit code.

    Exit codes: 0 all selected cases passed, 1 any failure (including a failed
    --json-output write), 2 no cases matched the selector. Built purely on the
    public runner API - call it from a template's __main__.py with
    `sys.exit(cli(CASES, db=my_db))`. Inside an already-running event loop, use
    `await acli(...)` instead.
    """
    return asyncio.run(acli(cases, db=db, judge_model=judge_model, default_timeout=default_timeout, argv=argv))
