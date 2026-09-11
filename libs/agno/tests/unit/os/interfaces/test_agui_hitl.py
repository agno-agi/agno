"""HITL over the AG-UI interface.

Covers the gap #8565 leaves open:
  1. Emission  - requires_confirmation / requires_user_input pauses must surface as
     TOOL_CALL_* events (so a card can render), not just external_execution.
  2. Resolution - an inbound ToolMessage must resolve the matching paused requirement BY
     its stored pause_type (confirm / provide_user_input / external result), NOT a blanket
     result-write (which silently rejects a confirmation at dispatch).
"""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core.types import Tool as AGUITool
from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
from agno.models.response import ToolExecution, UserInputField
from agno.os.interfaces.agui.handlers import on_run_completed
from agno.os.interfaces.agui.input import parse_client_tools
from agno.os.interfaces.agui.resume import (
    ensure_requirements_resolved,
    resolve_requirements_from_tool_messages,
)
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)
from agno.run import RunContext
from agno.run.agent import RunPausedEvent
from agno.run.requirement import RunRequirement
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.tools import tool
from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion

from ._agui_stream_rules import assert_valid_agui_stream


def _emitted(chunk) -> list:
    """Drive a pause through the handler, checking the framing of everything it emits.

    A pause emits the approval cards and the run's terminal event in one batch, so the
    batch is a whole stream and the same rules apply to it as to a mapper's output. The
    per-test assertions below each name one tool_call_id; none of them would notice the
    batch opening a message it never closes or ending a tool call it never started.
    """
    events = on_run_completed(chunk, StreamState())
    assert_valid_agui_stream(events)
    return events


def _tool_call_start_ids(events) -> list:
    return [e.tool_call_id for e in events if type(e).__name__ == "ToolCallStartEvent"]


def _tool_args_delta(events, tool_call_id: str) -> str:
    deltas = [e.delta for e in events if type(e).__name__ == "ToolCallArgsEvent" and e.tool_call_id == tool_call_id]
    assert len(deltas) == 1
    return deltas[0]


def _paused(tool: ToolExecution) -> RunPausedEvent:
    return RunPausedEvent(tools=[tool])


def _tm(tool_call_id: str, content: str) -> AGUIToolMessage:
    return AGUIToolMessage(id="m-" + tool_call_id, role="tool", content=content, tool_call_id=tool_call_id)


def _team_paused(*, requirements=None, tools=None) -> TeamRunPausedEvent:
    return TeamRunPausedEvent(requirements=requirements, tools=tools)


def _member_req(te: ToolExecution, member_id: str = "m1") -> RunRequirement:
    req = RunRequirement(te)
    req.member_agent_id = member_id
    return req


class TestPauseEmission:
    def test_requires_confirmation_emits_tool_call(self):
        tool = ToolExecution(
            tool_call_id="tc-confirm",
            tool_name="generate_task_steps",
            tool_args={"steps": []},
            requires_confirmation=True,
        )
        assert "tc-confirm" in _tool_call_start_ids(_emitted(_paused(tool)))

    def test_requires_user_input_emits_tool_call(self):
        tool = ToolExecution(
            tool_call_id="tc-input",
            tool_name="ask_question",
            tool_args={},
            requires_user_input=True,
        )
        assert "tc-input" in _tool_call_start_ids(_emitted(_paused(tool)))

    def test_external_execution_still_emits_tool_call(self):
        tool = ToolExecution(
            tool_call_id="tc-external",
            tool_name="run_browser_tool",
            tool_args={},
            external_execution_required=True,
        )
        assert "tc-external" in _tool_call_start_ids(_emitted(_paused(tool)))

    def test_user_feedback_emits_exactly_one_tool_call(self):
        """A user_feedback (ask_user) tool already surfaces via the user_input partition
        (core sets requires_user_input=True on it, models/base.py). It must emit EXACTLY
        ONE TOOL_CALL_START -- a dedicated feedback partition would double-emit the same
        tool_call_id (the tool sits in both partitions), a protocol violation."""
        tool = ToolExecution(
            tool_call_id="tc-feedback",
            tool_name="ask_user",
            tool_args={"questions": [{"question": "Pick a color", "options": [{"label": "red"}, {"label": "blue"}]}]},
            requires_user_input=True,
            user_feedback_schema=[
                UserFeedbackQuestion(
                    question="Pick a color",
                    options=[UserFeedbackOption(label="red"), UserFeedbackOption(label="blue")],
                )
            ],
        )
        ids = _tool_call_start_ids(_emitted(_paused(tool)))
        assert ids.count("tc-feedback") == 1


class TestPauseArguments:
    """A pause emits its cards and the run's terminal event in one batch.

    Serializing an argument is the one step in that batch that reads a value the tool
    author chose, so it is the one step that can raise. The batch is built before any of
    it is yielded, so raising sends none of it: the route catches the exception and the
    client gets the run's error in place of the cards it would have answered with.
    """

    def test_an_argument_json_cannot_serialize_keeps_the_card_and_the_terminal_event(self):
        tool = ToolExecution(
            tool_call_id="tc-datetime",
            tool_name="schedule_meeting",
            tool_args={"starts_at": datetime(2026, 1, 2, 3, 4, 5), "title": "review"},
            requires_confirmation=True,
        )

        events = _emitted(_paused(tool))

        assert "tc-datetime" in _tool_call_start_ids(events)
        assert type(events[-1]).__name__ == "RunFinishedEvent"
        assert json.loads(_tool_args_delta(events, "tc-datetime")) == {
            "starts_at": "2026-01-02 03:04:05",
            "title": "review",
        }

    def test_absent_arguments_are_an_empty_object_not_a_null(self):
        """A tool call's arguments are an object, and a card cannot read a null as one."""
        tool = ToolExecution(
            tool_call_id="tc-noargs",
            tool_name="approve",
            tool_args=None,
            requires_confirmation=True,
        )

        events = _emitted(_paused(tool))

        assert json.loads(_tool_args_delta(events, "tc-noargs")) == {}


class TestPauseResolution:
    def test_confirmation_accepted_confirms_and_leaves_result_none(self):
        req = RunRequirement(ToolExecution(tool_call_id="tc1", tool_name="x", requires_confirmation=True))
        resolve_requirements_from_tool_messages([req], [_tm("tc1", json.dumps({"accepted": True}))])
        assert req.tool_execution.confirmed is True
        assert req.tool_execution.result is None  # MUST stay None or dispatch silently rejects it
        assert req.is_resolved()

    def test_confirmation_rejected_sets_confirmed_false(self):
        req = RunRequirement(ToolExecution(tool_call_id="tc1", tool_name="x", requires_confirmation=True))
        resolve_requirements_from_tool_messages([req], [_tm("tc1", json.dumps({"accepted": False}))])
        assert req.tool_execution.confirmed is False

    def test_user_input_provides_values_and_keeps_flag(self):
        te = ToolExecution(
            tool_call_id="tc2",
            tool_name="ask",
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        resolve_requirements_from_tool_messages(
            [RunRequirement(te)], [_tm("tc2", json.dumps({"values": {"city": "Paris"}}))]
        )
        assert te.user_input_schema[0].value == "Paris"
        assert te.answered is True
        assert te.requires_user_input is True  # kept, else next model turn sees a dangling tool_call

    def test_user_input_malformed_payload_raises(self):
        """Narrowed to the single {values:{...}} shape: a malformed user_input payload (no/non-dict
        "values") fails LOUD at merge - the same fail-loud lane as the resume guard - instead of
        silently resolving the paused tool with empty input."""
        te = ToolExecution(
            tool_call_id="tc-bad",
            tool_name="ask",
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        with pytest.raises(ValueError, match="user_input expects"):
            resolve_requirements_from_tool_messages(
                [RunRequirement(te)], [_tm("tc-bad", json.dumps({"city": "Paris"}))]
            )

    def test_user_input_empty_values_is_accepted_not_raised(self):
        """An explicit empty {"values": {}} is a valid dict (user filled nothing): accepted gracefully
        (no raise), leaving the field unanswered so the guard/re-prompt handles it - only a non-dict
        "values" is malformed and raises."""
        te = ToolExecution(
            tool_call_id="tc-empty",
            tool_name="ask",
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        req = RunRequirement(te)
        resolve_requirements_from_tool_messages([req], [_tm("tc-empty", json.dumps({"values": {}}))])
        assert te.user_input_schema[0].value is None
        assert req.is_resolved() is False

    def test_external_execution_sets_result(self):
        te = ToolExecution(tool_call_id="tc3", tool_name="run", external_execution_required=True)
        req = RunRequirement(te)
        resolve_requirements_from_tool_messages([req], [_tm("tc3", "browser output")])
        assert req.external_execution_result == "browser output"

    def test_user_feedback_provides_selections_and_answers(self):
        te = ToolExecution(
            tool_call_id="tc-fb",
            tool_name="ask_user",
            requires_user_input=True,
            user_feedback_schema=[
                UserFeedbackQuestion(
                    question="Pick a color",
                    options=[UserFeedbackOption(label="red"), UserFeedbackOption(label="blue")],
                )
            ],
        )
        req = RunRequirement(te)
        resolve_requirements_from_tool_messages(
            [req], [_tm("tc-fb", json.dumps({"selections": {"Pick a color": ["red"]}}))]
        )
        assert te.user_feedback_schema[0].selected_options == ["red"]
        assert te.answered is True
        assert req.is_resolved()

    def test_user_feedback_malformed_payload_raises(self):
        """A user_feedback payload missing the {'selections': {...}} envelope (or with a
        non-list value) fails LOUD at merge -- the same fail-loud lane as user_input."""
        te = ToolExecution(
            tool_call_id="tc-fb-bad",
            tool_name="ask_user",
            requires_user_input=True,
            user_feedback_schema=[UserFeedbackQuestion(question="Pick", options=[UserFeedbackOption(label="red")])],
        )
        with pytest.raises(ValueError, match="user_feedback expects"):
            resolve_requirements_from_tool_messages(
                [RunRequirement(te)], [_tm("tc-fb-bad", json.dumps({"Pick": ["red"]}))]
            )

    def test_user_feedback_empty_selections_not_resolved(self):
        """An explicit empty {"selections": {}} is a valid dict (user picked nothing): accepted
        gracefully (no raise), leaving the question unanswered so the resume guard re-prompts --
        mirrors the user_input empty-values case."""
        te = ToolExecution(
            tool_call_id="tc-fb-empty",
            tool_name="ask_user",
            requires_user_input=True,
            user_feedback_schema=[UserFeedbackQuestion(question="Pick", options=[UserFeedbackOption(label="red")])],
        )
        req = RunRequirement(te)
        resolve_requirements_from_tool_messages([req], [_tm("tc-fb-empty", json.dumps({"selections": {}}))])
        assert te.user_feedback_schema[0].selected_options is None
        assert req.is_resolved() is False


class TestDedupe:
    def test_backend_confirmation_tool_wins_over_same_named_client_tool(self):
        """A frontend-advertised client tool must NOT shadow the agent's own
        requires_confirmation tool. get_tools appends client_tools AFTER the agent's
        tools (_tools.py:131/239) and parse_tools skips later duplicates, so the
        backend tool (the executor) is the one kept."""

        @tool(requires_confirmation=True)
        def send_email(to: str, subject: str, body: str) -> str:
            return f"Email sent to {to}"

        client_tools = parse_client_tools(
            [
                AGUITool(
                    name="send_email",
                    description="frontend twin",
                    parameters={"type": "object", "properties": {}},
                )
            ]
        )
        functions = parse_tools(
            agent=Agent(),
            tools=[send_email, *client_tools],  # mirrors get_tools ordering
            model=MagicMock(),
            run_context=RunContext(run_id="r", session_id="s"),
        )
        assert len(functions) == 1
        assert functions[0].requires_confirmation is True
        assert not functions[0].external_execution


class TestStreamWrappers:
    """The pause emission must surface through BOTH AG-UI stream wrappers (sync + async),
    not only the path-agnostic on_run_completed. Both delegate to the shared terminal
    tracker -> on_run_completed; these drive a requires_confirmation pause through each wrapper.
    (The resume path is async-only - acontinue_run - so it has no sync twin to cover.)"""

    def test_sync_wrapper_emits_tool_call_on_confirmation_pause(self):
        tool = ToolExecution(tool_call_id="tc-sync", tool_name="send_email", requires_confirmation=True)
        events = list(
            stream_agno_response_as_agui_events(iter([RunPausedEvent(tools=[tool])]), thread_id="t", run_id="r")
        )
        assert_valid_agui_stream(events)
        assert "tc-sync" in _tool_call_start_ids(events)

    async def test_async_wrapper_emits_tool_call_on_confirmation_pause(self):
        tool = ToolExecution(tool_call_id="tc-async", tool_name="send_email", requires_confirmation=True)

        async def _aiter(items):
            for item in items:
                yield item

        events = [
            e
            async for e in async_stream_agno_response_as_agui_events(
                _aiter([RunPausedEvent(tools=[tool])]), thread_id="t", run_id="r"
            )
        ]
        assert_valid_agui_stream(events)
        assert "tc-async" in _tool_call_start_ids(events)


class TestUnresolvedGuard:
    """A multi-tool pause answered only partially must NOT reach dispatch half-paused
    (where unanswered confirmation tools are silently rejected). The resume guard raises instead."""

    def _two_confirmations(self):
        return (
            RunRequirement(ToolExecution(tool_call_id="a", tool_name="confirm_a", requires_confirmation=True)),
            RunRequirement(ToolExecution(tool_call_id="b", tool_name="confirm_b", requires_confirmation=True)),
        )

    def test_partial_answer_leaves_one_unresolved_and_guard_raises(self):
        req_a, req_b = self._two_confirmations()
        resolve_requirements_from_tool_messages([req_a, req_b], [_tm("a", json.dumps({"accepted": True}))])
        assert req_a.is_resolved() is True
        assert req_b.is_resolved() is False  # unanswered tool stays paused, not silently rejected
        with pytest.raises(ValueError, match="Partial resume"):
            ensure_requirements_resolved([req_a, req_b])

    def test_fully_answered_set_passes_the_guard(self):
        req_a, req_b = self._two_confirmations()
        resolve_requirements_from_tool_messages(
            [req_a, req_b],
            [_tm("a", json.dumps({"accepted": True})), _tm("b", json.dumps({"accepted": False}))],
        )
        ensure_requirements_resolved([req_a, req_b])  # both resolved -> no raise


class TestTeamPauseEmission:
    """A Team paused run carries member pauses (all types) in active_requirements with member_agent_id,
    and the team leader's external tools in .tools. on_run_completed must surface both as TOOL_CALL_*,
    not just external_execution. Nothing dedupes the two channels; see the last test here."""

    def test_team_member_confirmation_emits_tool_call(self):
        req = _member_req(ToolExecution(tool_call_id="m-confirm", tool_name="send_email", requires_confirmation=True))
        assert "m-confirm" in _tool_call_start_ids(_emitted(_team_paused(requirements=[req])))

    def test_team_member_user_input_emits_tool_call(self):
        req = _member_req(
            ToolExecution(
                tool_call_id="m-input",
                tool_name="ask",
                requires_user_input=True,
                user_input_schema=[UserInputField(name="city", field_type=str)],
            )
        )
        assert "m-input" in _tool_call_start_ids(_emitted(_team_paused(requirements=[req])))

    def test_team_member_user_feedback_emits_tool_call(self):
        req = _member_req(
            ToolExecution(
                tool_call_id="m-feedback",
                tool_name="ask_user",
                requires_user_input=True,
                user_feedback_schema=[UserFeedbackQuestion(question="Pick", options=[UserFeedbackOption(label="a")])],
            )
        )
        assert "m-feedback" in _tool_call_start_ids(_emitted(_team_paused(requirements=[req])))

    def test_team_leader_external_still_emits(self):
        """Regression guard: leader external tools live in .tools; the seam switch must not drop them."""
        tool = ToolExecution(tool_call_id="leader-ext", tool_name="run_browser_tool", external_execution_required=True)
        assert "leader-ext" in _tool_call_start_ids(_emitted(_team_paused(tools=[tool])))

    def test_a_tool_reported_through_both_channels_is_announced_twice(self):
        """A leader external tool sits in BOTH .tools and active_requirements.

        The handler folds a requirement in when it names a member agent, and nothing
        compares tool_call_ids across the two channels, so the same call is announced
        twice and the reference client aborts the run on the second TOOL_CALL_START.
        This pins what ships: the dedupe is a known gap held out of this change, and
        both assertions below fail the moment it is closed.

        Built with the file's own member-requirement helper on purpose. A bare
        RunRequirement carries no member_agent_id, the handler skips it, and the count
        then comes from .tools alone and holds whether a dedupe exists or not.
        """
        tool = ToolExecution(tool_call_id="dup-ext", tool_name="run_browser_tool", external_execution_required=True)
        events = on_run_completed(_team_paused(requirements=[_member_req(tool)], tools=[tool]), StreamState())

        assert _tool_call_start_ids(events).count("dup-ext") == 2
        with pytest.raises(AssertionError, match="tool call id dup-ext is started twice in one stream"):
            assert_valid_agui_stream(events)

    def test_team_member_requirement_resolves_via_existing_merge(self):
        """A member (member_agent_id) confirmation resolves through the EXISTING
        resolve_requirements_from_tool_messages - input.py is entity-agnostic, so team HITL needs no resolution change."""
        req = _member_req(ToolExecution(tool_call_id="m-res", tool_name="send_email", requires_confirmation=True))
        resolve_requirements_from_tool_messages([req], [_tm("m-res", json.dumps({"accepted": True}))])
        assert req.tool_execution.confirmed is True
        assert req.is_resolved()
