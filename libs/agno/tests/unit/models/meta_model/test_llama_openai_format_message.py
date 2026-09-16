"""Tests for LlamaOpenAI._format_message signature and compression forwarding.

OpenAIChat._format_all_messages calls _format_message(message, compress_tool_results)
with the flag as a positional argument, so an override that omits the parameter
raises TypeError on every run. These tests pin the override to the base-class
signature and assert the flag actually reaches the Llama formatter.
"""

import inspect

import pytest

pytest.importorskip("llama_api_client")

from agno.models.message import Message  # noqa: E402
from agno.models.meta.llama_openai import LlamaOpenAI  # noqa: E402
from agno.models.openai.chat import OpenAIChat  # noqa: E402


def test_format_message_signature_matches_base_class():
    """The override must accept every parameter the base class passes."""
    base = inspect.signature(OpenAIChat._format_message)
    override = inspect.signature(LlamaOpenAI._format_message)

    assert list(override.parameters) == list(base.parameters)


def test_format_message_accepts_compress_tool_results_positionally():
    """The base class passes the flag positionally, so the call must not raise."""
    model = LlamaOpenAI(api_key="test-key")

    formatted = model._format_message(Message(role="user", content="hello"), False)

    assert formatted["role"] == "user"


def test_compress_tool_results_is_forwarded_to_the_formatter():
    """A compressed tool result must be used when the flag is set."""
    model = LlamaOpenAI(api_key="test-key")
    message = Message(role="tool", content="x" * 200, tool_call_id="call_1")
    message.compressed_content = "SHORT"

    compressed = model._format_message(message, True)
    uncompressed = model._format_message(message, False)

    assert compressed["content"] == "SHORT"
    assert uncompressed["content"] == "x" * 200
