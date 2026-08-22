"""Regression tests for surfacing Anthropic server-executed tool calls as ToolExecution records.

Claude returns server-executed tool calls as `server_tool_use` blocks paired with
`*_tool_result` blocks (web_search, code_execution, bash_code_execution, web_fetch,
text_editor_code_execution, tool_search). Before this change, those blocks were
stashed into `provider_data["server_tool_blocks"]` for history but never became
`ToolExecution` records - so `run_response.tools` stayed empty and the AgentOS UI
didn't render a tool card for them.

These tests cover the non-streaming and streaming parser paths.
"""

from typing import List, Optional
from unittest.mock import MagicMock

from agno.models.anthropic.claude import (
    _CLAUDE_SERVER_RESULT_TYPES,
    Claude,
    _flatten_claude_server_tool_result,
)
from agno.models.response import ModelResponseEvent


def _make_server_tool_use_block(block_id: str, name: str, tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "server_tool_use"
    block.id = block_id
    block.name = name
    block.input = tool_input
    block.citations = None
    block.model_dump.return_value = {
        "type": "server_tool_use",
        "id": block_id,
        "name": name,
        "input": tool_input,
    }
    return block


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = None
    return block


def _make_web_search_result_block(tool_use_id: str, items: List[dict]) -> MagicMock:
    """`content` is a list of WebSearchResultBlock-like items."""

    def _item(d: dict) -> MagicMock:
        m = MagicMock()
        m.type = "web_search_result"
        m.error_code = None
        m.model_dump.return_value = d
        return m

    block = MagicMock()
    block.type = "web_search_tool_result"
    block.tool_use_id = tool_use_id
    block.content = [_item(d) for d in items]
    block.citations = None
    block.model_dump.return_value = {
        "type": "web_search_tool_result",
        "tool_use_id": tool_use_id,
        "content": items,
    }
    return block


def _make_code_execution_result_block(
    tool_use_id: str, stdout: str, stderr: str = "", return_code: int = 0, error_code: Optional[str] = None
) -> MagicMock:
    """`content` is a single CodeExecutionResultBlock OR a CodeExecutionToolResultError."""
    content = MagicMock()
    if error_code is not None:
        content.type = "code_execution_tool_result_error"
        content.error_code = error_code
        content.model_dump.return_value = {
            "type": "code_execution_tool_result_error",
            "error_code": error_code,
        }
    else:
        content.type = "code_execution_result"
        content.stdout = stdout
        content.stderr = stderr
        content.return_code = return_code
        content.error_code = None
        content.model_dump.return_value = {
            "type": "code_execution_result",
            "stdout": stdout,
            "stderr": stderr,
            "return_code": return_code,
        }

    block = MagicMock()
    block.type = "code_execution_tool_result"
    block.tool_use_id = tool_use_id
    block.content = content
    block.citations = None
    block.model_dump.return_value = {
        "type": "code_execution_tool_result",
        "tool_use_id": tool_use_id,
    }
    return block


# ---------------------------------------------------------------------------
# Non-streaming parser tests
# ---------------------------------------------------------------------------


def test_parse_pairs_web_search_call_with_result():
    """server_tool_use(web_search) + matching web_search_tool_result → one
    ToolExecution with the queries on tool_args and the result list flattened."""
    model = Claude(id="claude-opus-4-6")

    call_block = _make_server_tool_use_block(
        block_id="srvtoolu_01",
        name="web_search",
        tool_input={"query": "agno framework"},
    )
    result_block = _make_web_search_result_block(
        tool_use_id="srvtoolu_01",
        items=[{"url": "https://www.agno.com", "title": "Agno", "type": "web_search_result"}],
    )
    text_block = _make_text_block("Agno is a Python framework for building agents.")

    response = MagicMock()
    response.role = "assistant"
    response.content = [call_block, result_block, text_block]
    response.stop_reason = "end_turn"
    response.usage = None

    parsed = model._parse_provider_response(response)

    assert parsed.tool_executions is not None
    assert len(parsed.tool_executions) == 1
    te = parsed.tool_executions[0]
    assert te.tool_call_id == "srvtoolu_01"
    assert te.tool_name == "web_search"
    assert te.tool_args == {"query": "agno framework"}
    assert te.result is not None
    assert "agno.com" in te.result
    assert te.tool_call_error is False


def test_parse_records_error_results():
    """is_error from the result block flows through to ToolExecution.tool_call_error."""
    model = Claude(id="claude-opus-4-6")
    call_block = _make_server_tool_use_block(
        block_id="srvtoolu_err",
        name="code_execution",
        tool_input={"code": "1/0"},
    )
    result_block = _make_code_execution_result_block(
        tool_use_id="srvtoolu_err",
        stdout="",
        error_code="execution_failed",
    )

    response = MagicMock()
    response.role = "assistant"
    response.content = [call_block, result_block]
    response.stop_reason = "end_turn"
    response.usage = None

    parsed = model._parse_provider_response(response)

    assert parsed.tool_executions[0].tool_name == "code_execution"
    assert parsed.tool_executions[0].tool_call_error is True
    assert "execution_failed" in parsed.tool_executions[0].result


def test_parse_unmatched_call_still_emits_execution_with_none_result():
    """If the server returns a server_tool_use without a matching result (e.g. a
    partial / cancelled response), we still surface the call - result is just
    None and tool_call_error is left None (unknown rather than False)."""
    model = Claude(id="claude-opus-4-6")
    call_block = _make_server_tool_use_block(
        block_id="srvtoolu_orphan",
        name="web_search",
        tool_input={"query": "foo"},
    )

    response = MagicMock()
    response.role = "assistant"
    response.content = [call_block]
    response.stop_reason = "end_turn"
    response.usage = None

    parsed = model._parse_provider_response(response)

    assert len(parsed.tool_executions) == 1
    te = parsed.tool_executions[0]
    assert te.result is None
    assert te.tool_call_error is None


def test_parse_preserves_server_blocks_in_provider_data():
    """The raw server_tool_use block is still stashed into provider_data so
    history reconstruction continues to work alongside the new ToolExecution."""
    model = Claude(id="claude-opus-4-6")
    call_block = _make_server_tool_use_block(
        block_id="srvtoolu_keep",
        name="web_search",
        tool_input={"query": "foo"},
    )
    result_block = _make_web_search_result_block("srvtoolu_keep", [])

    response = MagicMock()
    response.role = "assistant"
    response.content = [call_block, result_block]
    response.stop_reason = "end_turn"
    response.usage = None

    parsed = model._parse_provider_response(response)

    assert parsed.provider_data is not None
    server_blocks = parsed.provider_data.get("server_tool_blocks", [])
    block_types = [b.get("type") for b in server_blocks]
    assert "server_tool_use" in block_types
    assert "web_search_tool_result" in block_types


def test_parse_skips_client_tool_use_blocks():
    """Regular tool_use blocks (client-declared functions) must NOT be turned
    into ToolExecutions - they still go through the existing tool_calls path
    so the run loop can dispatch them locally."""
    model = Claude(id="claude-opus-4-6")
    client_tool_block = MagicMock()
    client_tool_block.type = "tool_use"
    client_tool_block.id = "toolu_client"
    client_tool_block.name = "send_email"
    client_tool_block.input = {"to": "yash@phidata.com"}
    client_tool_block.citations = None

    response = MagicMock()
    response.role = "assistant"
    response.content = [client_tool_block]
    response.stop_reason = "tool_use"
    response.usage = None

    parsed = model._parse_provider_response(response)

    # Client tool went to tool_calls, NOT tool_executions.
    assert parsed.tool_executions in (None, [])
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0]["id"] == "toolu_client"
    assert parsed.tool_calls[0]["function"]["name"] == "send_email"


# ---------------------------------------------------------------------------
# Streaming parser tests
# ---------------------------------------------------------------------------


def test_stream_message_stop_pairs_and_tags_event():
    """MessageStopEvent carries the full reconstructed content list - we pair
    server_tool_use + result there and set event=tool_call_completed so the
    streaming consumer routes the ToolExecution to run_response.tools."""
    from anthropic.types import MessageStopEvent

    model = Claude(id="claude-opus-4-6")

    call_block = _make_server_tool_use_block(
        block_id="srvtoolu_stream",
        name="web_search",
        tool_input={"query": "antigravity"},
    )
    result_block = _make_web_search_result_block(
        "srvtoolu_stream",
        [{"url": "https://example.com", "title": "X", "type": "web_search_result"}],
    )
    text_block = _make_text_block("Found something.")

    message = MagicMock()
    message.content = [call_block, result_block, text_block]
    message.context_management = None
    message.container = None

    event = MagicMock(spec=MessageStopEvent)
    event.__class__ = MessageStopEvent
    event.message = message

    parsed = model._parse_provider_response_delta(event)

    assert parsed.tool_executions is not None
    assert len(parsed.tool_executions) == 1
    te = parsed.tool_executions[0]
    assert te.tool_call_id == "srvtoolu_stream"
    assert te.tool_name == "web_search"
    assert te.tool_args == {"query": "antigravity"}
    assert te.result is not None
    # Event tag is required for the streaming consumer in agent/_response.py
    # to actually route the ToolExecution to run_response.tools.
    assert parsed.event == ModelResponseEvent.tool_call_completed.value


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_result_type_registry_covers_known_families():
    """_CLAUDE_SERVER_RESULT_TYPES should at minimum include the documented
    server-executed tool families. Adding a new family is fine but missing
    one means the parser will silently skip its result blocks."""
    expected_min = {
        "web_search_tool_result",
        "code_execution_tool_result",
        "bash_code_execution_tool_result",
        "web_fetch_tool_result",
    }
    assert expected_min.issubset(set(_CLAUDE_SERVER_RESULT_TYPES))


def test_flatten_handles_list_content():
    """List content (e.g. WebSearchToolResultBlockContent) is joined; error
    detection happens via .type ending in _error or .error_code presence."""
    items: List[MagicMock] = []
    for i in range(2):
        item = MagicMock()
        item.type = "web_search_result"
        item.error_code = None
        item.model_dump.return_value = {"type": "web_search_result", "url": f"https://x{i}.com"}
        items.append(item)

    block = MagicMock()
    block.content = items

    text, is_error = _flatten_claude_server_tool_result(block)
    assert text is not None
    assert "x0.com" in text and "x1.com" in text
    assert is_error is False


def test_flatten_handles_none_content():
    block = MagicMock()
    block.content = None
    text, is_error = _flatten_claude_server_tool_result(block)
    assert text is None
    assert is_error is False
