"""Unpaired function_call steps must be paired with a placeholder function_result.

Gemini's Interactions API expects every ``function_call`` step to be followed by a
``function_result`` step carrying the same call id. Sessions can hold runs whose tool
result was never recorded (e.g. a run that was interrupted mid-tool-execution).
Formatting pairs such calls with a placeholder function_result so the session stays
usable and the model can see the call never completed.
"""

import pytest

pytest.importorskip("google.genai")

from typing import Any, Dict, List

from agno.models.google.gemini_interactions import GeminiInteractions
from agno.models.message import Message
from agno.utils.message import MISSING_TOOL_RESULT_PLACEHOLDER

# Shape observed in affected sessions: uuid id, no call_id.
DELEGATE_CALL_ID = "d4f8a1b2-3c5e-4a91-b7d2-8e6f0a1c2b3d"


def _delegate_tool_call(call_id: str = DELEGATE_CALL_ID) -> Dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "delegate_task_to_member",
            "arguments": '{"member_id": "researcher", "task": "Research X"}',
        },
    }


def _steps_of_type(steps: List[Dict[str, Any]], step_type: str) -> List[Dict[str, Any]]:
    return [s for s in steps if s.get("type") == step_type]


class TestUnpairedToolCalls:
    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_complete_turn_is_preserved(self):
        """A call with its result must still be sent — both halves, correctly paired."""
        model = self._make_model()

        steps = model._build_input(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                Message(
                    role="tool",
                    tool_call_id=DELEGATE_CALL_ID,
                    tool_name="delegate_task_to_member",
                    content="Researcher: findings for X",
                ),
            ]
        )

        calls = _steps_of_type(steps, "function_call")
        results = _steps_of_type(steps, "function_result")
        assert len(calls) == 1
        assert len(results) == 1
        assert results[0]["call_id"] == DELEGATE_CALL_ID
        assert results[0]["result"] == "Researcher: findings for X"

    def test_call_with_no_recorded_result_gets_placeholder(self):
        """The reported bug: a run persisted with a tool call and no tool message."""
        model = self._make_model()

        steps = model._build_input(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                # No tool message was ever recorded for the call above.
                Message(role="assistant", content="Here are the findings."),
            ]
        )

        calls = _steps_of_type(steps, "function_call")
        results = _steps_of_type(steps, "function_result")
        assert len(calls) == 1, "the call must still be sent"
        assert len(results) == 1
        assert results[0]["call_id"] == calls[0]["id"]
        assert results[0]["result"] == MISSING_TOOL_RESULT_PLACEHOLDER

    def test_mixed_turn_pairs_real_and_placeholder_results(self):
        """A mixed turn: one recorded result and one missing result both stay valid."""
        model = self._make_model()
        paired_id = "call_paired"
        unpaired_id = "call_unpaired"

        steps = model._build_input(
            messages=[
                Message(role="user", content="Do both tasks"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[_delegate_tool_call(paired_id), _delegate_tool_call(unpaired_id)],
                ),
                Message(role="tool", tool_call_id=paired_id, tool_name="delegate_task_to_member", content="Paired result"),
            ]
        )

        results = _steps_of_type(steps, "function_result")
        by_call_id = {r["call_id"]: r for r in results}
        assert by_call_id[paired_id]["result"] == "Paired result"
        assert by_call_id[unpaired_id]["result"] == MISSING_TOOL_RESULT_PLACEHOLDER
