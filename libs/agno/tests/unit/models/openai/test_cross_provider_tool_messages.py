"""Tests for cross-provider tool message normalization.

When switching providers mid-session (e.g., Gemini -> OpenAI), tool messages
stored by one provider must be normalized before sending to another.

Gemini stores combined tool results as:
  Message(role="tool", content=["result1", "result2"], tool_calls=[...])

OpenAI expects:
  {"role": "tool", "content": "result1", "tool_call_id": "call_123"}

These tests verify that _format_message and _format_messages normalize correctly
across ALL affected providers.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
os.environ.setdefault("GROQ_API_KEY", "test-key-for-testing")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-for-testing")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-testing")
os.environ.setdefault("AIMLAPI_API_KEY", "test-key-for-testing")
os.environ.setdefault("CEREBRAS_API_KEY", "test-key-for-testing")

import pytest

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses


# ---------------------------------------------------------------------------
# Helper: build Gemini-style combined tool message
# ---------------------------------------------------------------------------
def _gemini_combined_message(
    tool_calls_data: list[tuple[str, str, str]],
) -> Message:
    """Build a Gemini-style combined tool message.

    Args:
        tool_calls_data: list of (tool_call_id, tool_name, content) tuples
    """
    return Message(
        role="tool",
        content=[tc[2] for tc in tool_calls_data],
        tool_name=", ".join(tc[1] for tc in tool_calls_data),
        tool_calls=[{"tool_call_id": tc[0], "tool_name": tc[1], "content": tc[2]} for tc in tool_calls_data],
    )


def _assistant_with_tool_calls(call_ids: list[str], names: list[str]) -> Message:
    """Build an assistant message with tool_calls."""
    return Message(
        role="assistant",
        tool_calls=[
            {
                "id": cid,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
            for cid, name in zip(call_ids, names)
        ],
    )


# ===========================================================================
# 1. OpenAI Chat — Single Message Normalization (_format_message)
# ===========================================================================
class TestOpenAIChatNormalization:
    def setup_method(self):
        self.model = OpenAIChat(id="gpt-4o-mini")

    def test_list_content_to_string(self):
        msg = Message(role="tool", content=['{"echo": "hello"}'], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert isinstance(fmt["content"], str)
        assert fmt["content"] == '{"echo": "hello"}'

    def test_multi_item_list_content(self):
        msg = Message(
            role="tool",
            content=['{"a": 1}', '{"b": 2}'],
            tool_call_id="call_1",
        )
        fmt = self.model._format_message(msg)
        assert fmt["content"] == '{"a": 1}\n{"b": 2}'

    def test_preserves_string_content(self):
        msg = Message(role="tool", content='{"echo": "hello"}', tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert fmt["content"] == '{"echo": "hello"}'
        assert fmt["tool_call_id"] == "call_1"

    def test_extracts_tool_call_id_from_tool_calls(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_calls=[{"tool_call_id": "call_99", "tool_name": "t", "content": "result"}],
        )
        fmt = self.model._format_message(msg)
        assert fmt["tool_call_id"] == "call_99"

    def test_extracts_tool_call_id_skips_none_value(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_calls=[
                {"tool_call_id": None, "tool_name": "t1", "content": "r1"},
                {"tool_call_id": "call_valid", "tool_name": "t2", "content": "r2"},
            ],
        )
        fmt = self.model._format_message(msg)
        assert fmt["tool_call_id"] == "call_valid"

    def test_preserves_existing_tool_call_id(self):
        msg = Message(
            role="tool",
            content="result",
            tool_call_id="call_existing",
            tool_calls=[{"tool_call_id": "call_other", "tool_name": "t", "content": "x"}],
        )
        fmt = self.model._format_message(msg)
        assert fmt["tool_call_id"] == "call_existing"

    def test_removes_tool_calls_from_tool_role(self):
        msg = Message(
            role="tool",
            content="result",
            tool_call_id="call_1",
            tool_calls=[{"tool_call_id": "call_1", "tool_name": "t", "content": "result"}],
        )
        fmt = self.model._format_message(msg)
        assert "tool_calls" not in fmt

    def test_assistant_preserves_tool_calls(self):
        msg = _assistant_with_tool_calls(["call_1"], ["echo"])
        fmt = self.model._format_message(msg)
        assert "tool_calls" in fmt
        assert len(fmt["tool_calls"]) == 1

    def test_none_content(self):
        msg = Message(role="tool", content=None, tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert fmt["content"] == ""

    def test_list_with_none_items(self):
        msg = Message(role="tool", content=[None, '{"ok": true}', None], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert fmt["content"] == '{"ok": true}'

    def test_tool_calls_none_not_reintroduced(self):
        msg = Message(role="tool", content="result", tool_call_id="call_1", tool_calls=[])
        fmt = self.model._format_message(msg)
        assert "tool_calls" not in fmt

    def test_db_round_trip(self):
        original = Message(
            role="tool",
            content=['{"echo": "hello"}'],
            tool_name="echo",
            tool_calls=[{"tool_call_id": "call_rt", "tool_name": "echo", "content": '{"echo": "hello"}'}],
        )
        serialized = original.to_dict()
        assert isinstance(serialized["content"], list)
        restored = Message.from_dict(serialized)
        assert isinstance(restored.content, list)
        fmt = self.model._format_message(restored)
        assert isinstance(fmt["content"], str)
        assert fmt["tool_call_id"] == "call_rt"
        assert "tool_calls" not in fmt


# ===========================================================================
# 2. OpenAI Chat — Multi-Tool Splitting (_format_messages)
# ===========================================================================
class TestOpenAIChatSplitting:
    def setup_method(self):
        self.model = OpenAIChat(id="gpt-4o-mini")

    def test_splits_combined_message(self):
        msgs = [
            _gemini_combined_message(
                [
                    ("call_1", "search", '{"results": ["a"]}'),
                    ("call_2", "fetch", '{"page": "b"}'),
                ]
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 2
        assert fmt[0] == {"role": "tool", "content": '{"results": ["a"]}', "tool_call_id": "call_1"}
        assert fmt[1] == {"role": "tool", "content": '{"page": "b"}', "tool_call_id": "call_2"}

    def test_no_split_when_tool_call_id_set(self):
        msgs = [Message(role="tool", content="result", tool_call_id="call_1")]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 1
        assert fmt[0]["tool_call_id"] == "call_1"

    def test_preserves_message_order(self):
        msgs = [
            Message(role="user", content="Hello"),
            _assistant_with_tool_calls(["call_1", "call_2"], ["search", "fetch"]),
            _gemini_combined_message(
                [
                    ("call_1", "search", "result1"),
                    ("call_2", "fetch", "result2"),
                ]
            ),
            Message(role="assistant", content="Done"),
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 5  # user + assistant + 2 split tool + assistant
        assert fmt[0]["role"] == "user"
        assert fmt[1]["role"] == "assistant"
        assert fmt[2]["role"] == "tool"
        assert fmt[2]["tool_call_id"] == "call_1"
        assert fmt[3]["role"] == "tool"
        assert fmt[3]["tool_call_id"] == "call_2"
        assert fmt[4]["role"] == "assistant"

    def test_split_handles_list_content_in_tc(self):
        # When compress_tool_results=False (default), prefer original content over tc content
        msgs = [
            Message(
                role="tool",
                content=["orig"],
                tool_calls=[{"tool_call_id": "call_1", "tool_name": "t", "content": ["nested1", "nested2"]}],
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert fmt[0]["content"] == "orig"
        # When compressing, use tc content
        fmt_compressed = self.model._format_messages(msgs, compress_tool_results=True)
        assert fmt_compressed[0]["content"] == "nested1\nnested2"

    def test_split_handles_none_content_in_tc(self):
        # When original content exists, prefer it even if tc content is None
        msgs = [
            Message(
                role="tool",
                content=["orig"],
                tool_calls=[{"tool_call_id": "call_1", "tool_name": "t", "content": None}],
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert fmt[0]["content"] == "orig"

    def test_split_skips_tc_without_id(self):
        msgs = [
            Message(
                role="tool",
                content=["r1", "r2"],
                tool_calls=[
                    {"tool_call_id": "call_1", "tool_name": "t1", "content": "r1"},
                    {"tool_name": "t2", "content": "r2"},  # no tool_call_id
                ],
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 1
        assert fmt[0]["tool_call_id"] == "call_1"

    def test_split_handles_int_content(self):
        msgs = [
            Message(
                role="tool",
                content=["42"],
                tool_calls=[{"tool_call_id": "call_1", "tool_name": "calc", "content": 42}],
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert fmt[0]["content"] == "42"

    def test_empty_tool_calls_list_does_not_split(self):
        msgs = [Message(role="tool", content="result", tool_call_id="call_1", tool_calls=[])]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 1

    def test_three_way_split(self):
        msgs = [
            _gemini_combined_message(
                [
                    ("call_1", "tool_a", "result_a"),
                    ("call_2", "tool_b", "result_b"),
                    ("call_3", "tool_c", "result_c"),
                ]
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 3
        assert [f["tool_call_id"] for f in fmt] == ["call_1", "call_2", "call_3"]


# ===========================================================================
# 3. OpenAI Responses API
# ===========================================================================
class TestOpenAIResponsesNormalization:
    def setup_method(self):
        self.model = OpenAIResponses(id="gpt-4o-mini")

    def test_combined_message_emits_all_outputs(self):
        msgs = [
            Message(role="user", content="Do two things"),
            _assistant_with_tool_calls(["call_1", "call_2"], ["search", "fetch"]),
            _gemini_combined_message(
                [
                    ("call_1", "search", '{"results": ["a"]}'),
                    ("call_2", "fetch", '{"page": "b"}'),
                ]
            ),
        ]
        fmt = self.model._format_messages(msgs)
        outputs = [m for m in fmt if m.get("type") == "function_call_output"]
        assert len(outputs) == 2
        assert outputs[0]["call_id"] == "call_1"
        assert outputs[0]["output"] == '{"results": ["a"]}'
        assert outputs[1]["call_id"] == "call_2"
        assert outputs[1]["output"] == '{"page": "b"}'

    def test_normal_tool_message_preserved(self):
        msgs = [
            Message(role="user", content="Echo"),
            _assistant_with_tool_calls(["call_1"], ["echo"]),
            Message(role="tool", content='{"echo": "hi"}', tool_call_id="call_1"),
        ]
        fmt = self.model._format_messages(msgs)
        outputs = [m for m in fmt if m.get("type") == "function_call_output"]
        assert len(outputs) == 1
        assert outputs[0]["output"] == '{"echo": "hi"}'

    def test_list_content_normalized_on_normal_tool(self):
        msgs = [
            Message(role="user", content="Echo"),
            _assistant_with_tool_calls(["call_1"], ["echo"]),
            Message(role="tool", content=['{"echo": "hi"}'], tool_call_id="call_1"),
        ]
        fmt = self.model._format_messages(msgs)
        outputs = [m for m in fmt if m.get("type") == "function_call_output"]
        assert len(outputs) == 1
        assert outputs[0]["output"] == '{"echo": "hi"}'

    def test_combined_with_fc_id_mapping(self):
        """Gemini tool_call_ids map through fc_id_to_call_id correctly."""
        assistant = Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "fc_1",
                    "call_id": "call_real_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                },
            ],
        )
        tool = Message(
            role="tool",
            content=["result"],
            tool_calls=[{"tool_call_id": "fc_1", "tool_name": "search", "content": "result"}],
        )
        fmt = self.model._format_messages([Message(role="user", content="Go"), assistant, tool])
        outputs = [m for m in fmt if m.get("type") == "function_call_output"]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_real_1"

    def test_three_way_combined_outputs(self):
        msgs = [
            Message(role="user", content="Do three things"),
            _assistant_with_tool_calls(["c1", "c2", "c3"], ["a", "b", "c"]),
            _gemini_combined_message(
                [
                    ("c1", "a", "r1"),
                    ("c2", "b", "r2"),
                    ("c3", "c", "r3"),
                ]
            ),
        ]
        fmt = self.model._format_messages(msgs)
        outputs = [m for m in fmt if m.get("type") == "function_call_output"]
        assert len(outputs) == 3
        assert [o["call_id"] for o in outputs] == ["c1", "c2", "c3"]

    def test_reasoning_model_skips_function_calls_but_keeps_outputs(self):
        """When previous_response_id exists, function_call items are skipped
        but function_call_output from combined messages should still be emitted."""
        model = OpenAIResponses(id="o3")
        assistant = Message(
            role="assistant",
            content="thinking...",
            provider_data={"response_id": "resp_abc123"},
            tool_calls=[
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
            ],
        )
        tool = Message(
            role="tool",
            content=["search result"],
            tool_calls=[{"tool_call_id": "call_1", "tool_name": "search", "content": "search result"}],
        )
        user_followup = Message(role="user", content="Now what?")
        msgs = [
            Message(role="user", content="Search"),
            assistant,
            tool,
            user_followup,
        ]
        fmt = model._format_messages(msgs)
        # With previous_response_id, only messages AFTER the assistant are formatted
        # So: tool message + user followup
        outputs = [m for m in fmt if m.get("type") == "function_call_output"]
        users = [m for m in fmt if isinstance(m, dict) and m.get("role") == "user"]
        function_calls = [m for m in fmt if isinstance(m, dict) and m.get("type") == "function_call"]
        assert len(outputs) == 1, f"Expected 1 function_call_output, got {len(outputs)}"
        assert len(users) == 1
        assert len(function_calls) == 0  # skipped due to reasoning model


# ===========================================================================
# 4. DeepSeek — inherits _format_messages from OpenAIChat
# ===========================================================================
class TestDeepSeekCrossProvider:
    def setup_method(self):
        from agno.models.deepseek import DeepSeek

        self.model = DeepSeek(id="deepseek-chat")

    def test_inherits_format_messages(self):
        assert hasattr(self.model, "_format_messages")

    def test_splits_combined_message(self):
        msgs = [
            _gemini_combined_message(
                [
                    ("call_1", "search", "r1"),
                    ("call_2", "fetch", "r2"),
                ]
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 2
        assert fmt[0]["tool_call_id"] == "call_1"
        assert fmt[1]["tool_call_id"] == "call_2"

    def test_normalizes_list_content(self):
        msg = Message(role="tool", content=["r1", "r2"], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert isinstance(fmt["content"], str)
        assert fmt["content"] == "r1\nr2"

    def test_preserves_reasoning_content(self):
        msg = Message(role="assistant", content="answer", reasoning_content="thinking...")
        fmt = self.model._format_message(msg)
        assert fmt.get("reasoning_content") == "thinking..."


# ===========================================================================
# 5. Groq
# ===========================================================================
class TestGroqCrossProvider:
    def setup_method(self):
        from agno.models.groq import Groq

        self.model = Groq(id="llama-3.3-70b-versatile")

    def test_splits_combined_message(self):
        msgs = [
            _gemini_combined_message(
                [
                    ("call_1", "search", "r1"),
                    ("call_2", "fetch", "r2"),
                ]
            )
        ]
        fmt = self.model.format_messages(msgs)
        assert len(fmt) == 2
        assert fmt[0] == {"role": "tool", "content": "r1", "tool_call_id": "call_1"}
        assert fmt[1] == {"role": "tool", "content": "r2", "tool_call_id": "call_2"}

    def test_normalizes_list_content(self):
        msg = Message(role="tool", content=["r1", "r2"], tool_call_id="call_1")
        fmt = self.model.format_message(msg)
        assert isinstance(fmt["content"], str)

    def test_preserves_non_tool_messages(self):
        msgs = [
            Message(role="user", content="Hello"),
            _gemini_combined_message([("call_1", "t", "r")]),
        ]
        fmt = self.model.format_messages(msgs)
        assert len(fmt) == 2
        assert fmt[0]["role"] == "user"
        assert fmt[1]["role"] == "tool"

    def test_filters_none_in_list_content(self):
        msg = Message(role="tool", content=[None, "result", None], tool_call_id="call_1")
        fmt = self.model.format_message(msg)
        assert fmt["content"] == "result"


# ===========================================================================
# 6. Cohere
# ===========================================================================
class TestCohereCrossProvider:
    def setup_method(self):
        from agno.utils.models.cohere import format_messages

        self.format_messages = format_messages

    def test_splits_combined_message(self):
        msgs = [
            _gemini_combined_message(
                [
                    ("call_1", "search", "r1"),
                    ("call_2", "fetch", "r2"),
                ]
            )
        ]
        fmt = self.format_messages(msgs)
        assert len(fmt) == 2
        assert fmt[0] == {"role": "tool", "content": "r1", "tool_call_id": "call_1"}
        assert fmt[1] == {"role": "tool", "content": "r2", "tool_call_id": "call_2"}

    def test_normalizes_list_content(self):
        msgs = [Message(role="tool", content=["r1"], tool_call_id="call_1")]
        fmt = self.format_messages(msgs)
        assert isinstance(fmt[0]["content"], str)

    def test_normal_tool_message_preserved(self):
        msgs = [Message(role="tool", content="result", tool_call_id="call_1")]
        fmt = self.format_messages(msgs)
        assert len(fmt) == 1
        assert fmt[0]["content"] == "result"
        assert fmt[0]["tool_call_id"] == "call_1"

    def test_three_way_split(self):
        msgs = [
            _gemini_combined_message(
                [
                    ("c1", "a", "r1"),
                    ("c2", "b", "r2"),
                    ("c3", "c", "r3"),
                ]
            )
        ]
        fmt = self.format_messages(msgs)
        assert len(fmt) == 3
        assert [f["tool_call_id"] for f in fmt] == ["c1", "c2", "c3"]


# ===========================================================================
# 7. OpenAILike Inheritors (OpenRouter, AIMLAPI, CerebrasOpenAI)
# ===========================================================================
class TestOpenAILikeInheritors:
    """All OpenAILike subclasses inherit _format_messages from OpenAIChat."""

    @pytest.fixture(
        params=[
            ("openrouter", "OpenRouter", "openai/gpt-4o"),
            ("aimlapi", "AIMLAPI", "gpt-4o"),
            ("cerebras_openai", "CerebrasOpenAI", "llama-3.3-70b"),
        ],
        ids=["OpenRouter", "AIMLAPI", "CerebrasOpenAI"],
    )
    def model(self, request):
        module_name, class_name, model_id = request.param
        if module_name == "cerebras_openai":
            mod = __import__("agno.models.cerebras", fromlist=[class_name])
        elif module_name == "openrouter":
            mod = __import__("agno.models.openrouter", fromlist=[class_name])
        else:
            mod = __import__(f"agno.models.{module_name}", fromlist=[class_name])
        cls = getattr(mod, class_name)
        return cls(id=model_id)

    def test_has_format_messages(self, model):
        assert hasattr(model, "_format_messages")

    def test_splits_combined_message(self, model):
        msgs = [
            _gemini_combined_message(
                [
                    ("call_1", "search", "r1"),
                    ("call_2", "fetch", "r2"),
                ]
            )
        ]
        fmt = model._format_messages(msgs)
        assert len(fmt) == 2
        assert fmt[0]["tool_call_id"] == "call_1"
        assert fmt[1]["tool_call_id"] == "call_2"

    def test_normal_message_passthrough(self, model):
        msgs = [Message(role="tool", content="result", tool_call_id="call_1")]
        fmt = model._format_messages(msgs)
        assert len(fmt) == 1
        assert fmt[0]["tool_call_id"] == "call_1"


# ===========================================================================
# 8. Edge Cases
# ===========================================================================
class TestEdgeCases:
    def setup_method(self):
        self.model = OpenAIChat(id="gpt-4o-mini")

    def test_empty_content_list(self):
        msg = Message(role="tool", content=[], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert fmt["content"] == ""

    def test_single_none_in_content_list(self):
        msg = Message(role="tool", content=[None], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert fmt["content"] == ""

    def test_dict_content_in_list(self):
        msg = Message(role="tool", content=[{"key": "value"}], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert isinstance(fmt["content"], str)
        assert "key" in fmt["content"]

    def test_mixed_types_in_content_list(self):
        msg = Message(role="tool", content=["string", 42, None, True], tool_call_id="call_1")
        fmt = self.model._format_message(msg)
        assert isinstance(fmt["content"], str)
        assert "string" in fmt["content"]
        assert "42" in fmt["content"]
        assert "True" in fmt["content"]
        assert "None" not in fmt["content"]

    def test_tool_message_with_both_tool_call_id_and_tool_calls_does_not_split(self):
        """When tool_call_id is set, _format_messages should NOT split even if tool_calls exist."""
        msgs = [
            Message(
                role="tool",
                content="result",
                tool_call_id="call_1",
                tool_calls=[{"tool_call_id": "call_1", "tool_name": "t", "content": "result"}],
            )
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 1
        assert fmt[0]["tool_call_id"] == "call_1"

    def test_multiple_combined_messages_in_sequence(self):
        """Two consecutive Gemini combined messages should both be split."""
        msgs = [
            _gemini_combined_message([("c1", "t1", "r1"), ("c2", "t2", "r2")]),
            _gemini_combined_message([("c3", "t3", "r3"), ("c4", "t4", "r4")]),
        ]
        fmt = self.model._format_messages(msgs)
        assert len(fmt) == 4
        assert [f["tool_call_id"] for f in fmt] == ["c1", "c2", "c3", "c4"]

    def test_full_conversation_flow(self):
        """Simulate a complete Gemini session loaded into OpenAI."""
        msgs = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Search for X and fetch Y"),
            _assistant_with_tool_calls(["call_1", "call_2"], ["search", "fetch"]),
            _gemini_combined_message(
                [
                    ("call_1", "search", '{"results": ["doc1", "doc2"]}'),
                    ("call_2", "fetch", '{"page": "content of Y"}'),
                ]
            ),
            Message(role="assistant", content="I found the results."),
            Message(role="user", content="Now calculate something"),
            _assistant_with_tool_calls(["call_3"], ["calc"]),
            Message(
                role="tool",
                content='{"result": 42}',
                tool_call_id="call_3",
            ),
            Message(role="assistant", content="The answer is 42."),
        ]
        fmt = self.model._format_messages(msgs)
        # system + user + assistant(2 tool_calls) + 2 split tool + assistant + user + assistant(1 tool_call) + 1 tool + assistant
        assert len(fmt) == 10
        roles = [f.get("role") for f in fmt]
        assert roles == [
            "developer",
            "user",
            "assistant",
            "tool",
            "tool",
            "assistant",
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert fmt[3]["tool_call_id"] == "call_1"
        assert fmt[4]["tool_call_id"] == "call_2"
        assert fmt[8]["tool_call_id"] == "call_3"

    def test_db_round_trip_then_split(self):
        """Combined message → DB → load → _format_messages splits correctly."""
        original = _gemini_combined_message(
            [
                ("call_1", "search", '{"r": 1}'),
                ("call_2", "fetch", '{"r": 2}'),
            ]
        )
        serialized = original.to_dict()
        restored = Message.from_dict(serialized)
        assert isinstance(restored.content, list)
        assert restored.tool_call_id is None

        fmt = self.model._format_messages([restored])
        assert len(fmt) == 2
        assert fmt[0]["tool_call_id"] == "call_1"
        assert fmt[0]["content"] == '{"r": 1}'
        assert fmt[1]["tool_call_id"] == "call_2"
        assert fmt[1]["content"] == '{"r": 2}'

    def test_end_to_end_gemini_to_openai_payload(self):
        """Validate the exact payload that would be sent to OpenAI API.

        Simulates: Gemini creates combined tool message → stored to DB → loaded → formatted for OpenAI.
        Asserts every field at every stage.
        """
        # --- Stage 1: Gemini creates a combined tool message ---
        # This is what gemini.py:format_function_call_results produces
        gemini_msg = Message(
            role="tool",
            content=['{"stock": "AAPL", "price": 150.0}', '{"stock": "MSFT", "price": 420.0}'],
            tool_name="get_stock_price, get_stock_price",
            tool_calls=[
                {
                    "tool_call_id": "call_abc",
                    "tool_name": "get_stock_price",
                    "content": '{"stock": "AAPL", "price": 150.0}',
                },
                {
                    "tool_call_id": "call_def",
                    "tool_name": "get_stock_price",
                    "content": '{"stock": "MSFT", "price": 420.0}',
                },
            ],
        )
        # Verify Gemini's combined structure
        assert isinstance(gemini_msg.content, list)
        assert len(gemini_msg.content) == 2
        assert gemini_msg.tool_call_id is None  # No top-level tool_call_id

        # --- Stage 2: Stored to DB (to_dict) ---
        serialized = gemini_msg.to_dict()
        assert isinstance(serialized["content"], list)
        assert "tool_call_id" not in serialized  # None values are filtered by to_dict
        assert len(serialized["tool_calls"]) == 2

        # --- Stage 3: Loaded from DB (from_dict) ---
        restored = Message.from_dict(serialized)
        assert isinstance(restored.content, list)
        assert restored.tool_call_id is None
        assert len(restored.tool_calls) == 2

        # --- Stage 4: Formatted for OpenAI Chat API ---
        chat_model = OpenAIChat(id="gpt-4o-mini")
        chat_formatted = chat_model._format_messages([restored])

        # Must produce exactly 2 separate tool messages
        assert len(chat_formatted) == 2

        # First tool message
        assert chat_formatted[0] == {
            "role": "tool",
            "content": '{"stock": "AAPL", "price": 150.0}',
            "tool_call_id": "call_abc",
        }
        # Second tool message
        assert chat_formatted[1] == {
            "role": "tool",
            "content": '{"stock": "MSFT", "price": 420.0}',
            "tool_call_id": "call_def",
        }

        # Verify content is string (the exact thing OpenAI requires)
        for msg in chat_formatted:
            assert isinstance(msg["content"], str), f"OpenAI requires string content, got {type(msg['content'])}"
            assert isinstance(msg["tool_call_id"], str)
            assert "tool_calls" not in msg  # tool_calls must NOT be on tool-role messages

        # --- Stage 5: Formatted for OpenAI Responses API ---
        responses_model = OpenAIResponses(id="gpt-4o-mini")
        # Need an assistant message with matching tool_calls for Responses API
        assistant_msg = _assistant_with_tool_calls(["call_abc", "call_def"], ["get_stock_price", "get_stock_price"])
        resp_formatted = responses_model._format_messages(
            [
                Message(role="user", content="Get AAPL and MSFT prices"),
                assistant_msg,
                restored,
            ]
        )

        # Extract function_call_output items
        outputs = [m for m in resp_formatted if m.get("type") == "function_call_output"]
        assert len(outputs) == 2
        assert outputs[0] == {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": '{"stock": "AAPL", "price": 150.0}',
        }
        assert outputs[1] == {
            "type": "function_call_output",
            "call_id": "call_def",
            "output": '{"stock": "MSFT", "price": 420.0}',
        }

    def test_without_fix_would_fail(self):
        """Prove that without normalization, list content would be sent to OpenAI.

        This test validates the exact scenario that caused the original bug.
        """
        # Build a message with list content (the problematic state)
        msg = Message(
            role="tool",
            content=['{"result": "data"}'],
            tool_call_id="call_1",
        )

        # With our fix: content should be normalized to string
        chat_model = OpenAIChat(id="gpt-4o-mini")
        fmt = chat_model._format_message(msg)
        assert isinstance(fmt["content"], str), "Fix must convert list content to string"
        assert fmt["content"] == '{"result": "data"}'

        # Verify the message dict would be valid for OpenAI
        assert fmt["role"] == "tool"
        assert fmt["tool_call_id"] == "call_1"
        assert "tool_calls" not in fmt
