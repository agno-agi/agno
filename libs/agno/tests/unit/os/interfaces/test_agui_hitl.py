"""HITL over the AG-UI interface.

Covers the gap #8565 leaves open:
  1. Emission  - requires_confirmation / requires_user_input pauses must surface as
     TOOL_CALL_* events (so a card can render), not just external_execution.
  2. Resolution - an inbound ToolMessage must resolve the matching paused requirement BY
     its stored pause_type (confirm / provide_user_input / external result), NOT a blanket
     result-write (which silently rejects a confirmation at dispatch).
"""

import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core.types import Tool as AGUITool
from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent.agent import Agent
from agno.agent._tools import parse_tools
from agno.models.response import ToolExecution, UserInputField
from agno.os.interfaces.agui.handlers import on_run_completed
from agno.os.interfaces.agui.input import (
    agui_tools_to_external_functions,
    ensure_requirements_resolved,
    merge_tool_results_into_requirements,
)
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)
from agno.run import RunContext
from agno.run.agent import RunPausedEvent
from agno.run.requirement import RunRequirement
from agno.tools import tool


def _tool_call_start_ids(events) -> list:
    return [e.tool_call_id for e in events if type(e).__name__ == "ToolCallStartEvent"]


def _paused(tool: ToolExecution) -> RunPausedEvent:
    return RunPausedEvent(tools=[tool])


def _tm(tool_call_id: str, content: str) -> AGUIToolMessage:
    return AGUIToolMessage(id="m-" + tool_call_id, role="tool", content=content, tool_call_id=tool_call_id)


class TestPauseEmission:
    def test_requires_confirmation_emits_tool_call(self):
        tool = ToolExecution(
            tool_call_id="tc-confirm",
            tool_name="generate_task_steps",
            tool_args={"steps": []},
            requires_confirmation=True,
        )
        assert "tc-confirm" in _tool_call_start_ids(on_run_completed(_paused(tool), StreamState()))

    def test_requires_user_input_emits_tool_call(self):
        tool = ToolExecution(
            tool_call_id="tc-input",
            tool_name="ask_question",
            tool_args={},
            requires_user_input=True,
        )
        assert "tc-input" in _tool_call_start_ids(on_run_completed(_paused(tool), StreamState()))

    def test_external_execution_still_emits_tool_call(self):
        tool = ToolExecution(
            tool_call_id="tc-external",
            tool_name="run_browser_tool",
            tool_args={},
            external_execution_required=True,
        )
        assert "tc-external" in _tool_call_start_ids(on_run_completed(_paused(tool), StreamState()))


class TestPauseResolution:
    def test_confirmation_accepted_confirms_and_leaves_result_none(self):
        req = RunRequirement(ToolExecution(tool_call_id="tc1", tool_name="x", requires_confirmation=True))
        merge_tool_results_into_requirements([req], [_tm("tc1", json.dumps({"accepted": True}))])
        assert req.tool_execution.confirmed is True
        assert req.tool_execution.result is None  # MUST stay None or dispatch silently rejects it
        assert req.is_resolved()

    def test_confirmation_rejected_sets_confirmed_false(self):
        req = RunRequirement(ToolExecution(tool_call_id="tc1", tool_name="x", requires_confirmation=True))
        merge_tool_results_into_requirements([req], [_tm("tc1", json.dumps({"accepted": False}))])
        assert req.tool_execution.confirmed is False

    def test_user_input_provides_values_and_keeps_flag(self):
        te = ToolExecution(
            tool_call_id="tc2",
            tool_name="ask",
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        merge_tool_results_into_requirements(
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
        with pytest.raises(ValueError, match="user_input resume expects"):
            merge_tool_results_into_requirements([RunRequirement(te)], [_tm("tc-bad", json.dumps({"city": "Paris"}))])

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
        merge_tool_results_into_requirements([req], [_tm("tc-empty", json.dumps({"values": {}}))])
        assert te.user_input_schema[0].value is None
        assert req.is_resolved() is False

    def test_external_execution_sets_result(self):
        te = ToolExecution(tool_call_id="tc3", tool_name="run", external_execution_required=True)
        req = RunRequirement(te)
        merge_tool_results_into_requirements([req], [_tm("tc3", "browser output")])
        assert req.external_execution_result == "browser output"


class TestDedupe:
    def test_backend_confirmation_tool_wins_over_same_named_client_tool(self):
        """A frontend-advertised client tool must NOT shadow the agent's own
        requires_confirmation tool. get_tools appends client_tools AFTER the agent's
        tools (_tools.py:131/239) and parse_tools skips later duplicates, so the
        backend tool (the executor) is the one kept."""

        @tool(requires_confirmation=True)
        def send_email(to: str, subject: str, body: str) -> str:
            return f"Email sent to {to}"

        client_tools = agui_tools_to_external_functions(
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
    not only the path-agnostic on_run_completed. Both delegate to process_completion ->
    on_run_completed; these drive a requires_confirmation pause through each wrapper.
    (The resume path is async-only - acontinue_run - so it has no sync twin to cover.)"""

    def test_sync_wrapper_emits_tool_call_on_confirmation_pause(self):
        tool = ToolExecution(tool_call_id="tc-sync", tool_name="send_email", requires_confirmation=True)
        events = list(
            stream_agno_response_as_agui_events(iter([RunPausedEvent(tools=[tool])]), thread_id="t", run_id="r")
        )
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
        merge_tool_results_into_requirements([req_a, req_b], [_tm("a", json.dumps({"accepted": True}))])
        assert req_a.is_resolved() is True
        assert req_b.is_resolved() is False  # unanswered tool stays paused, not silently rejected
        with pytest.raises(ValueError, match="Partial resume"):
            ensure_requirements_resolved([req_a, req_b])

    def test_fully_answered_set_passes_the_guard(self):
        req_a, req_b = self._two_confirmations()
        merge_tool_results_into_requirements(
            [req_a, req_b],
            [_tm("a", json.dumps({"accepted": True})), _tm("b", json.dumps({"accepted": False}))],
        )
        ensure_requirements_resolved([req_a, req_b])  # both resolved -> no raise
