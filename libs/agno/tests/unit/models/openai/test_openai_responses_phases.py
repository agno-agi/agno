"""A response with commentary and final answer message items gives one assistant text, the same in every mode."""

import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses
from agno.tools.function import Function

MODES = ["sync", "async", "sync_stream", "async_stream"]

NARRATION = "I am retrieving the price table."
COMMENTARY = "The price table is: apples 1.20; bananas 0.50."
FINAL_ANSWER = "The price table is:\n\n- Apples: 1.20\n- Bananas: 0.50"


def get_price_table() -> str:
    """Get the price table for the store."""
    return "PRICE-TABLE: apples 1.20 | bananas 0.50"


def _message(text: str, phase: Optional[str] = None, item_id: str = "msg_1") -> Dict[str, Any]:
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


def _function_call() -> Dict[str, Any]:
    return {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "get_price_table",
        "arguments": "{}",
        "status": "completed",
    }


def _response(response_id: str, output: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-luna",
        "status": "completed",
        "error": None,
        "usage": None,
        "output": output,
    }


def _stream_events(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = [{"type": "response.created", "response": {**response, "output": []}}]
    for index, item in enumerate(response["output"]):
        if item["type"] == "message":
            text = item["content"][0]["text"]
            events.append(
                {"type": "response.output_item.added", "output_index": index, "item": {**item, "content": []}}
            )
            # Two deltas per item, so the text has to be accumulated
            for delta in (text[: len(text) // 2], text[len(text) // 2 :]):
                if delta:
                    events.append(
                        {
                            "type": "response.output_text.delta",
                            "output_index": index,
                            "content_index": 0,
                            "item_id": item["id"],
                            "delta": delta,
                        }
                    )
        else:
            events.append({"type": "response.output_item.added", "output_index": index, "item": item})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": response})
    return events


def _transport(responses: List[Dict[str, Any]]) -> httpx.MockTransport:
    remaining = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        response = remaining.pop(0)
        if json.loads(request.content).get("stream"):
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in _stream_events(response))
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handle)


async def _run(mode: str, responses: List[Dict[str, Any]]) -> Tuple[List[Message], str]:
    """Run the model loop over the scripted responses. Returns the assistant messages and the streamed text."""
    transport = _transport(responses)
    messages = [Message(role="user", content="Show me the price table.")]
    tools = [Function.from_callable(get_price_table)]
    streamed = ""
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            model = OpenAIResponses(id="gpt-5.6-luna", client=client, async_client=async_client)
            if mode == "sync":
                model.response(messages=messages, tools=tools)
            elif mode == "async":
                await model.aresponse(messages=messages, tools=tools)
            elif mode == "sync_stream":
                for chunk in model.response_stream(messages=messages, tools=tools):
                    if isinstance(getattr(chunk, "content", None), str) and not chunk.tool_executions:
                        streamed += chunk.content
            else:
                async for chunk in model.aresponse_stream(messages=messages, tools=tools):
                    if isinstance(getattr(chunk, "content", None), str) and not chunk.tool_executions:
                        streamed += chunk.content
    return [message for message in messages if message.role == "assistant"], streamed


@pytest.mark.parametrize("mode", MODES)
async def test_commentary_with_a_function_call_stays_the_message_text(mode):
    assistants, _ = await _run(
        mode,
        [
            _response("resp_1", [_message(NARRATION, "commentary"), _function_call()]),
            _response("resp_2", [_message(FINAL_ANSWER, "final_answer")]),
        ],
    )

    assert [message.content for message in assistants] == [NARRATION, FINAL_ANSWER]
    assert assistants[0].tool_calls and assistants[0].tool_calls[0]["function"]["name"] == "get_price_table"


@pytest.mark.parametrize("mode", MODES)
async def test_final_answer_is_the_message_text_when_commentary_comes_with_it(mode):
    assistants, streamed = await _run(
        mode,
        [
            _response("resp_1", [_message(NARRATION, "commentary"), _function_call()]),
            _response(
                "resp_2",
                [_message(COMMENTARY, "commentary", "msg_1"), _message(FINAL_ANSWER, "final_answer", "msg_2")],
            ),
        ],
    )

    assert [message.content for message in assistants] == [NARRATION, FINAL_ANSWER]
    if mode.endswith("stream"):
        # Deltas of every message item are still streamed
        assert streamed == NARRATION + COMMENTARY + FINAL_ANSWER


@pytest.mark.parametrize("mode", MODES)
async def test_repeated_final_answer_is_kept_once(mode):
    assistants, _ = await _run(
        mode,
        [
            _response(
                "resp_1",
                [_message(FINAL_ANSWER, "final_answer", "msg_1"), _message(FINAL_ANSWER, "final_answer", "msg_2")],
            )
        ],
    )

    assert [message.content for message in assistants] == [FINAL_ANSWER]


@pytest.mark.parametrize("mode", MODES)
async def test_commentary_is_the_message_text_when_the_final_answer_is_empty(mode):
    assistants, _ = await _run(
        mode,
        [_response("resp_1", [_message(COMMENTARY, "commentary", "msg_1"), _message("", "final_answer", "msg_2")])],
    )

    assert [message.content for message in assistants] == [COMMENTARY]


@pytest.mark.parametrize("mode", MODES)
async def test_message_without_a_phase_is_unchanged(mode):
    assistants, streamed = await _run(mode, [_response("resp_1", [_message(FINAL_ANSWER)])])

    assert [message.content for message in assistants] == [FINAL_ANSWER]
    if mode.endswith("stream"):
        assert streamed == FINAL_ANSWER


@pytest.mark.parametrize("mode", MODES)
async def test_messages_without_a_phase_are_joined_as_before(mode):
    assistants, _ = await _run(
        mode,
        [_response("resp_1", [_message("First part. ", item_id="msg_1"), _message("Second part.", item_id="msg_2")])],
    )

    assert [message.content for message in assistants] == ["First part. Second part."]
