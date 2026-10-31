from typing import Any, Dict, List, Optional

from openai.types.responses import Response

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def _message_item(text: str, phase: Optional[str], item_id: str) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "type": "message",
        "id": item_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    if phase is not None:
        item["phase"] = phase
    return item


def _response(output: List[Dict[str, Any]]) -> Response:
    return Response.model_validate(
        {
            "id": "resp_1",
            "object": "response",
            "created_at": 0,
            "model": "gpt-5.5",
            "status": "completed",
            "error": None,
            "usage": None,
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def test_parse_provider_response_keeps_commentary_out_of_final_answer():
    model = OpenAIResponses(id="gpt-5.5")
    response = _response(
        [
            _message_item("Draft reply", "commentary", "msg_1"),
            _message_item("Final reply", "final_answer", "msg_2"),
        ]
    )

    model_response = model._parse_provider_response(response)

    assert model_response.content == "Final reply"
    assert model_response.provider_data is not None
    assert model_response.provider_data["phase"] == "final_answer"


def test_parse_provider_response_uses_last_final_answer():
    model = OpenAIResponses(id="gpt-5.5")
    response = _response(
        [
            _message_item("Final reply", "final_answer", "msg_1"),
            _message_item("Final reply", "final_answer", "msg_2"),
        ]
    )

    model_response = model._parse_provider_response(response)

    assert model_response.content == "Final reply"


def test_parse_provider_response_keeps_commentary_preamble_before_tool_call():
    model = OpenAIResponses(id="gpt-5.5")
    response = _response(
        [
            _message_item("Let me check that.", "commentary", "msg_1"),
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "{}",
                "status": "completed",
            },
        ]
    )

    model_response = model._parse_provider_response(response)

    assert model_response.content == "Let me check that."
    assert model_response.provider_data is not None
    assert model_response.provider_data["phase"] == "commentary"
    assert model_response.tool_calls is not None and len(model_response.tool_calls) == 1


def test_parse_provider_response_without_phase_is_unchanged():
    model = OpenAIResponses(id="gpt-4.1-mini")
    response = _response([_message_item("Hello", None, "msg_1")])

    model_response = model._parse_provider_response(response)

    assert model_response.content == "Hello"
    assert model_response.provider_data is not None
    assert "phase" not in model_response.provider_data


def test_format_messages_replays_assistant_phase():
    model = OpenAIResponses(id="gpt-4.1-mini")
    messages = [
        Message(role="user", content="Hi"),
        Message(role="assistant", content="Final reply", provider_data={"phase": "final_answer"}),
        Message(role="assistant", content="Older reply"),
        Message(role="user", content="Thanks"),
    ]

    formatted = model._format_messages(messages)

    assert formatted[1] == {"role": "assistant", "content": "Final reply", "phase": "final_answer"}
    assert formatted[2] == {"role": "assistant", "content": "Older reply"}
