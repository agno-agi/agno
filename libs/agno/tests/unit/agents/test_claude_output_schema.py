"""Native structured output for ClaudeAgent.

The Claude Agent SDK enforces schemas via `output_format` on the query and returns
validated data on `ResultMessage.structured_output`. These tests stub the SDK so
they assert the adapter's request shape and result translation without spawning the
Claude Code subprocess.
"""

import json
from typing import Any, List
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunEvent


class Company(BaseModel):
    name: str
    founded_year: int


# --- Fake SDK -------------------------------------------------------------


class _TextBlock:
    def __init__(self, text: str):
        self.text = text


class _AssistantMessage:
    def __init__(self, content: List[Any]):
        self.content = content


class _SystemMessage:
    def __init__(self, subtype: str = "init", data: dict | None = None):
        self.subtype = subtype
        self.data = data or {}


class _ResultMessage:
    def __init__(self, result: str = "", structured_output: Any = None, subtype: str = "success"):
        self.result = result
        self.structured_output = structured_output
        self.subtype = subtype
        self.is_error = False
        self.session_id = "sdk-sess"


class _StreamEvent:
    def __init__(self, event: dict):
        self.event = event


class _ToolUseBlock:  # unused here but referenced by isinstance checks in the adapter
    pass


class _ToolResultBlock:
    pass


class _UserMessage:
    def __init__(self, content):
        self.content = content


class _ClaudeAgentOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeSDK:
    """Stub matching the claude_agent_sdk surface the adapter touches."""

    ClaudeAgentOptions = _ClaudeAgentOptions
    ResultMessage = _ResultMessage
    AssistantMessage = _AssistantMessage
    SystemMessage = _SystemMessage
    TextBlock = _TextBlock
    StreamEvent = _StreamEvent
    ToolUseBlock = _ToolUseBlock
    ToolResultBlock = _ToolResultBlock
    UserMessage = _UserMessage

    def __init__(self, messages: List[Any]):
        self._messages = messages
        self.captured_options: Any = None
        self.captured_prompt: Any = None

    def query(self, *, prompt, options):
        self.captured_prompt = prompt
        self.captured_options = options

        async def _gen():
            for m in self._messages:
                yield m

        return _gen()


VALID = {"name": "Anthropic", "founded_year": 2021}


@pytest.fixture
def patch_sdk():
    def _install(messages):
        fake = FakeSDK(messages)
        return patch("agno.agents.claude.agent._sdk", return_value=fake), fake

    return _install


# --- output_format request shape -----------------------------------------


def test_output_format_set_on_options(patch_sdk):
    ctx, fake = patch_sdk([_ResultMessage(structured_output=VALID)])
    agent = ClaudeAgent(name="c")
    with ctx:
        agent.run("info about Anthropic", output_schema=Company)

    fmt = fake.captured_options.kwargs.get("output_format")
    assert fmt is not None
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] == Company.model_json_schema()


def test_no_output_format_without_schema(patch_sdk):
    ctx, fake = patch_sdk([_ResultMessage(result="hello")])
    agent = ClaudeAgent(name="c")
    with ctx:
        agent.run("say hi")

    assert "output_format" not in fake.captured_options.kwargs


def test_prompt_not_injected_with_schema(patch_sdk):
    """Native path: the schema must NOT be appended to the prompt."""
    ctx, fake = patch_sdk([_ResultMessage(structured_output=VALID)])
    agent = ClaudeAgent(name="c")
    with ctx:
        agent.run("info about Anthropic", output_schema=Company)

    assert fake.captured_prompt == "info about Anthropic"
    assert "json" not in fake.captured_prompt.lower()


# --- result translation ---------------------------------------------------


def test_structured_output_returned_as_model(patch_sdk):
    ctx, _ = patch_sdk([_ResultMessage(structured_output=VALID)])
    agent = ClaudeAgent(name="c")
    with ctx:
        result = agent.run("info", output_schema=Company)

    assert isinstance(result.content, Company)
    assert result.content.name == "Anthropic"
    assert result.content.founded_year == 2021
    assert result.content_type == "Company"


def test_plain_text_still_returned_without_schema(patch_sdk):
    ctx, _ = patch_sdk([_ResultMessage(result="just text")])
    agent = ClaudeAgent(name="c")
    with ctx:
        result = agent.run("say something")

    assert result.content == "just text"
    assert result.content_type == "str"


# --- streaming ------------------------------------------------------------


def test_stream_suppresses_narration_and_emits_object(patch_sdk):
    """With a schema, text deltas are dropped; a single JSON content event carries
    the validated object, which the base class parses back into the model."""
    messages = [
        _StreamEvent({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "thinking..."}}),
        _ResultMessage(structured_output=VALID),
    ]
    ctx, _ = patch_sdk(messages)
    agent = ClaudeAgent(name="c")
    with ctx:
        events = list(agent.run("info", stream=True, output_schema=Company))

    content_events = [e for e in events if e.event == RunEvent.run_content.value]
    # narration ("thinking...") suppressed; only the JSON object event remains
    assert len(content_events) == 1
    assert json.loads(content_events[0].content) == VALID

    completed = [e for e in events if e.event == RunEvent.run_completed.value]
    assert isinstance(completed[0].content, Company)
    assert completed[0].content.name == "Anthropic"


def test_stream_narration_flows_without_schema(patch_sdk):
    messages = [
        _StreamEvent({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello "}}),
        _StreamEvent({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}}),
        _ResultMessage(result="hello world"),
    ]
    ctx, _ = patch_sdk(messages)
    agent = ClaudeAgent(name="c")
    with ctx:
        events = list(agent.run("greet", stream=True))

    content_events = [e for e in events if e.event == RunEvent.run_content.value]
    assert "".join(e.content for e in content_events) == "hello world"
