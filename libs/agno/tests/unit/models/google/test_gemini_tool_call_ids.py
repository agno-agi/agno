import pytest

pytest.importorskip("google.genai")

from google.genai.types import Candidate, Content, FunctionCall, GenerateContentResponse, Part

from agno.models.google.gemini import Gemini
from agno.models.message import Message


@pytest.mark.parametrize("stream", [False, True])
def test_parallel_tool_call_ids_survive_round_trip(stream):
    model = Gemini()
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[
                        Part(function_call=FunctionCall(id="call-a", name="lookup", args={"city": "Paris"})),
                        Part(function_call=FunctionCall(id="call-b", name="lookup", args={"city": "Tokyo"})),
                    ],
                )
            )
        ]
    )
    parsed = model._parse_provider_response_delta(response) if stream else model._parse_provider_response(response)
    messages = [
        Message(role="assistant", tool_calls=parsed.tool_calls),
        Message(role="tool", tool_call_id="call-b", tool_name="lookup", content="Tokyo result"),
        Message(role="tool", tool_call_id="call-a", tool_name="lookup", content="Paris result"),
    ]

    formatted, _ = model._format_messages(messages)

    calls = [part.function_call for message in formatted for part in message.parts if part.function_call]
    results = [part.function_response for message in formatted for part in message.parts if part.function_response]
    assert [call.id for call in calls] == ["call-a", "call-b"]
    assert [result.id for result in results] == ["call-b", "call-a"]
