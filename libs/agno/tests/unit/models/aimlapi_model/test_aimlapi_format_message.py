"""Tests for the AI/ML API message formatter.

The class overrides ``_format_message`` only to turn a ``None`` content into an
empty string. The override has to keep the base class's signature: the caller in
``OpenAIChat._format_messages`` passes ``compress_tool_results`` positionally, so
an override that drops the parameter raises ``TypeError`` on every single run.
"""

import inspect

from agno.models.aimlapi import AIMLAPI
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat


def test_signature_matches_the_base_class():
    """A drifted override breaks every run, so pin the parameter names."""
    overridden = list(inspect.signature(AIMLAPI._format_message).parameters)
    base = list(inspect.signature(OpenAIChat._format_message).parameters)

    assert overridden == base


def test_accepts_compress_tool_results_positionally():
    """This is exactly how the base class calls it."""
    model = AIMLAPI(api_key="test-key")

    formatted = model._format_message(Message(role="user", content="hi"), False)

    assert formatted["content"] == "hi"


def test_none_content_becomes_an_empty_string():
    """The one behaviour the override exists for."""
    model = AIMLAPI(api_key="test-key")

    formatted = model._format_message(Message(role="assistant", content=None))

    assert formatted["content"] == ""
