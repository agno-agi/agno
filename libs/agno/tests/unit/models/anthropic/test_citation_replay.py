"""Document citations need a document_title key even when the title is null."""

import json

import pytest

pytest.importorskip("anthropic")

from anthropic.lib.streaming import MessageStopEvent
from anthropic.types import Message as AnthropicMessage
from anthropic.types import TextBlock, ThinkingBlock, Usage

from agno.models.anthropic.claude import Claude
from agno.models.message import Message
from agno.utils.models.claude import format_messages


@pytest.fixture(
    params=[
        {"type": "page_location", "start_page_number": 1, "end_page_number": 2},
        {"type": "char_location", "start_char_index": 0, "end_char_index": 6},
        {"type": "content_block_location", "start_block_index": 0, "end_block_index": 1},
    ],
    ids=["page", "char", "content_block"],
)
def citation(request):
    return {"cited_text": "Sample", "document_index": 0, **request.param}


@pytest.mark.parametrize("streaming", [False, True], ids=["response", "stream"])
@pytest.mark.parametrize("title", [None, "Report"], ids=["null_title", "named_title"])
def test_response_citations_keep_required_title_through_storage_and_replay(citation, streaming, title):
    expected_citation = {**citation, "document_title": title}
    response = AnthropicMessage(
        id="msg_citation",
        model="claude-sonnet-4-5",
        role="assistant",
        type="message",
        stop_reason="end_turn",
        usage=Usage(input_tokens=1, output_tokens=1),
        content=[
            ThinkingBlock(type="thinking", thinking="Read the document.", signature="signed-thinking"),
            TextBlock(type="text", text="A citation.", citations=[expected_citation]),
        ],
    )
    model = Claude(id="claude-sonnet-4-5", api_key="test-key")
    if streaming:
        parsed = model._parse_provider_response_delta(MessageStopEvent(type="message_stop", message=response))
    else:
        parsed = model._parse_provider_response(response)

    # Exercise the persisted representation, not just the SDK's in-memory block.
    stored = json.loads(json.dumps(parsed.provider_data))
    assert stored["content_blocks"][1]["citations"] == [expected_citation]
    assistant = Message(role="assistant", content=parsed.content, provider_data=stored)
    messages, _ = format_messages([Message(role="user", content="Summarize."), assistant])

    assert messages[1]["content"] == [
        {"type": "thinking", "thinking": "Read the document.", "signature": "signed-thinking"},
        {"type": "text", "text": "A citation.", "citations": [expected_citation]},
    ]


@pytest.mark.parametrize("storage", ["provider_data", "content"])
def test_replay_restores_title_in_old_history_without_mutating_it(citation, storage):
    blocks = [{"type": "text", "text": "A citation.", "citations": [citation]}]
    original = json.loads(json.dumps(blocks))
    if storage == "provider_data":
        assistant = Message(role="assistant", content="A citation.", provider_data={"content_blocks": blocks})
    else:
        assistant = Message(role="assistant", content=blocks)

    messages, _ = format_messages([Message(role="user", content="Summarize."), assistant])
    assert messages[1]["content"] == [
        {"type": "text", "text": "A citation.", "citations": [{**citation, "document_title": None}]},
    ]
    assert blocks == original
    replayed_again, _ = format_messages([Message(role="user", content="Summarize."), assistant])
    assert replayed_again == messages


def test_replay_does_not_add_document_title_to_web_citations():
    citation = {
        "type": "web_search_result_location",
        "cited_text": "Sample",
        "encrypted_index": "encrypted-index",
        "url": "https://example.com/report",
        "title": "Report",
    }
    block = {"type": "text", "text": "A web citation.", "citations": [citation]}
    assistant = Message(role="assistant", content="A web citation.", provider_data={"content_blocks": [block]})

    messages, _ = format_messages([Message(role="user", content="Summarize."), assistant])
    assert messages[1]["content"] == [block]
