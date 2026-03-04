import json

import pytest

from agno.models.message import Message
from agno.utils.models.tool_messages import normalize_tool_result_messages, resolve_tool_call_id, tool_result_text


def _assistant_with_tool_calls(tool_calls):
    return Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": tc_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for tc_id, name, args in tool_calls
        ],
    )


def _gemini_combined(tool_calls_data):
    return Message(
        role="tool",
        content=[tc[2] for tc in tool_calls_data],
        tool_name=", ".join(tc[1] for tc in tool_calls_data),
        tool_calls=[{"tool_call_id": tc[0], "tool_name": tc[1], "content": tc[2]} for tc in tool_calls_data],
    )


def _canonical(tool_call_id, content, tool_name="func"):
    return Message(role="tool", content=content, tool_call_id=tool_call_id, tool_name=tool_name)


def _user(text):
    return Message(role="user", content=text)


def _system(text):
    return Message(role="system", content=text)


def _assistant(text):
    return Message(role="assistant", content=text)


# ──────────────────────────────────────────────────────────────────────
# Claude formatter integration
# ──────────────────────────────────────────────────────────────────────


class TestClaudeFormatterWithGeminiMessages:
    def test_single_gemini_tool_result(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "get_price", {"symbol": "AAPL"})]),
            _gemini_combined([("tc1", "get_price", '{"price": 150.0}')]),
            _assistant("AAPL is $150"),
        ]
        chat, sys = format_messages(msgs)
        tool_msg = [
            m
            for m in chat
            if m["role"] == "user"
            and isinstance(m.get("content"), list)
            and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"])
        ]
        assert len(tool_msg) == 1
        assert tool_msg[0]["content"][0]["tool_use_id"] == "tc1"
        assert "150" in tool_msg[0]["content"][0]["content"]

    def test_multiple_gemini_tool_results(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "add", {"a": 1}), ("tc2", "mul", {"b": 2})]),
            _gemini_combined([("tc1", "add", "3"), ("tc2", "mul", "6")]),
            _assistant("done"),
        ]
        chat, _ = format_messages(msgs)
        tool_msgs = []
        for m in chat:
            if m["role"] == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tool_msgs.append(c)
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_use_id"] == "tc1"
        assert tool_msgs[1]["tool_use_id"] == "tc2"

    def test_gemini_dict_content_serialized_as_json(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "info", {})]),
            _gemini_combined([("tc1", "info", {"nested": {"deep": [1, 2, 3]}})]),
            _assistant("done"),
        ]
        chat, _ = format_messages(msgs)
        tool_blocks = []
        for m in chat:
            if m["role"] == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tool_blocks.append(c)
        assert len(tool_blocks) == 1
        content_str = tool_blocks[0]["content"]
        assert isinstance(content_str, str)
        parsed = json.loads(content_str)
        assert parsed == {"nested": {"deep": [1, 2, 3]}}

    def test_mixed_canonical_and_gemini_in_history(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            # Run 1: OpenAI canonical
            _user("q1"),
            _assistant_with_tool_calls([("oai-1", "fn_a", {})]),
            _canonical("oai-1", "result_a", "fn_a"),
            _assistant("a1"),
            # Run 2: Gemini combined
            _user("q2"),
            _assistant_with_tool_calls([("gem-1", "fn_b", {}), ("gem-2", "fn_c", {})]),
            _gemini_combined([("gem-1", "fn_b", "result_b"), ("gem-2", "fn_c", "result_c")]),
            _assistant("a2"),
        ]
        chat, _ = format_messages(msgs)
        tool_ids = []
        for m in chat:
            if m["role"] == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tool_ids.append(c["tool_use_id"])
        assert "oai-1" in tool_ids
        assert "gem-1" in tool_ids
        assert "gem-2" in tool_ids
        assert None not in tool_ids

    def test_gemini_tool_with_none_content(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "noop", {})]),
            Message(
                role="tool",
                content=[None],
                tool_name="noop",
                tool_calls=[{"tool_call_id": "tc1", "tool_name": "noop", "content": None}],
            ),
            _assistant("done"),
        ]
        chat, _ = format_messages(msgs)
        tool_blocks = []
        for m in chat:
            if m["role"] == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tool_blocks.append(c)
        assert len(tool_blocks) == 1
        assert tool_blocks[0]["tool_use_id"] == "tc1"
        assert isinstance(tool_blocks[0]["content"], str)


class TestClaudeFormatterEdgeCases:
    def test_tool_call_id_empty_string_not_none(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "fn", {})]),
            Message(role="tool", content="result", tool_call_id="", tool_name="fn"),
            _assistant("done"),
        ]
        chat, _ = format_messages(msgs)
        tool_blocks = []
        for m in chat:
            if m["role"] == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tool_blocks.append(c)
        assert len(tool_blocks) == 1
        assert tool_blocks[0]["tool_use_id"] == ""

    def test_consecutive_tool_results_merged(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "a", {}), ("tc2", "b", {})]),
            _canonical("tc1", "r1", "a"),
            _canonical("tc2", "r2", "b"),
            _assistant("done"),
        ]
        chat, _ = format_messages(msgs)
        user_with_tools = [
            m
            for m in chat
            if m["role"] == "user"
            and isinstance(m.get("content"), list)
            and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"])
        ]
        assert len(user_with_tools) == 1
        assert len(user_with_tools[0]["content"]) == 2

    def test_gemini_combined_splits_then_merges_for_claude(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "a", {}), ("tc2", "b", {})]),
            _gemini_combined([("tc1", "a", "r1"), ("tc2", "b", "r2")]),
            _assistant("done"),
        ]
        chat, _ = format_messages(msgs)
        user_with_tools = [
            m
            for m in chat
            if m["role"] == "user"
            and isinstance(m.get("content"), list)
            and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"])
        ]
        assert len(user_with_tools) == 1
        assert len(user_with_tools[0]["content"]) == 2
        assert user_with_tools[0]["content"][0]["tool_use_id"] == "tc1"
        assert user_with_tools[0]["content"][1]["tool_use_id"] == "tc2"


# ──────────────────────────────────────────────────────────────────────
# OpenAI formatter integration
# ──────────────────────────────────────────────────────────────────────


class TestOpenAIFormatterWithGeminiMessages:
    def _format(self, messages):
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat.__new__(OpenAIChat)
        model.role_map = None
        model.default_role_map = {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"}
        return model._format_messages(messages)

    def test_single_gemini_tool_result(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "fn", {})]),
            _gemini_combined([("tc1", "fn", "result")]),
            _assistant("done"),
        ]
        formatted = self._format(msgs)
        tool_msgs = [m for m in formatted if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"
        assert "tool_calls" not in tool_msgs[0]

    def test_multiple_gemini_tool_results_split(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "a", {}), ("tc2", "b", {})]),
            _gemini_combined([("tc1", "a", "r1"), ("tc2", "b", "r2")]),
            _assistant("done"),
        ]
        formatted = self._format(msgs)
        tool_msgs = [m for m in formatted if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_call_id"] == "tc1"
        assert tool_msgs[1]["tool_call_id"] == "tc2"

    def test_dict_content_becomes_json_string(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "fn", {})]),
            _gemini_combined([("tc1", "fn", {"key": "value", "num": 42})]),
            _assistant("done"),
        ]
        formatted = self._format(msgs)
        tool_msgs = [m for m in formatted if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        content = tool_msgs[0]["content"]
        assert isinstance(content, str)
        parsed = json.loads(content)
        assert parsed == {"key": "value", "num": 42}

    def test_gemini_tool_call_with_id_key_not_tool_call_id(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_name="fn",
            tool_calls=[{"id": "uuid-123", "tool_name": "fn", "content": "result"}],
        )
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("uuid-123", "fn", {})]),
            msg,
            _assistant("done"),
        ]
        formatted = self._format(msgs)
        tool_msgs = [m for m in formatted if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "uuid-123"


# ──────────────────────────────────────────────────────────────────────
# DB round-trip simulation
# ──────────────────────────────────────────────────────────────────────


class TestDBRoundTrip:
    def test_gemini_combined_survives_serialize_deserialize(self):
        original = _gemini_combined([("tc1", "add", '{"result": 42}'), ("tc2", "mul", '{"result": 100}')])
        serialized = original.to_dict()
        restored = Message(**serialized)

        assert restored.tool_call_id is None
        assert restored.tool_calls is not None
        assert len(restored.tool_calls) == 2

        normalized = normalize_tool_result_messages([restored])
        assert len(normalized) == 2
        assert normalized[0].tool_call_id == "tc1"
        assert normalized[1].tool_call_id == "tc2"

    def test_canonical_survives_serialize_deserialize(self):
        original = _canonical("call_abc123", '{"result": 42}', "my_func")
        serialized = original.to_dict()
        restored = Message(**serialized)

        assert restored.tool_call_id == "call_abc123"
        normalized = normalize_tool_result_messages([restored])
        assert len(normalized) == 1
        assert normalized[0].tool_call_id == "call_abc123"

    def test_full_conversation_round_trip_through_claude(self):
        from agno.utils.models.claude import format_messages

        conversation = [
            _system("sys"),
            _user("q1"),
            _assistant_with_tool_calls([("oai-1", "get_price", {"symbol": "AAPL"})]),
            _canonical("oai-1", "150.0", "get_price"),
            _assistant("AAPL=$150"),
            _user("q2"),
            _assistant_with_tool_calls([("gem-1", "divide", {"a": 1, "b": 2})]),
            _gemini_combined([("gem-1", "divide", '{"result": 0.5}')]),
            _assistant("0.5"),
        ]

        serialized = [m.to_dict() for m in conversation]
        restored = [Message(**d) for d in serialized]

        chat, sys = format_messages(restored)

        tool_use_ids = []
        for m in chat:
            if isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tool_use_ids.append(c["tool_use_id"])

        assert "oai-1" in tool_use_ids
        assert "gem-1" in tool_use_ids
        assert None not in tool_use_ids


# ──────────────────────────────────────────────────────────────────────
# Weird edge cases
# ──────────────────────────────────────────────────────────────────────


class TestWeirdEdgeCases:
    def test_tool_calls_empty_list_treated_as_falsy(self):
        msg = Message(
            role="tool",
            content="result",
            tool_call_id=None,
            tool_name="fn",
            tool_calls=[],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 1
        assert normalized[0].tool_call_id is None

    def test_tool_call_with_no_known_id_keys(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_name="fn",
            tool_calls=[{"tool_name": "fn", "content": "result", "unknown_key": "???"}],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 0

    def test_tool_call_with_none_id_value(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_name="fn",
            tool_calls=[{"tool_call_id": None, "id": None, "tool_name": "fn"}],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 0

    def test_mixed_valid_and_invalid_tool_calls(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "valid-1", "tool_name": "a", "content": "r1"},
                {"tool_name": "b", "content": "r2"},
            ],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 1
        assert normalized[0].tool_call_id == "valid-1"

    def test_numeric_tool_call_id_cast_to_string(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_name="fn",
            tool_calls=[{"tool_call_id": 12345, "tool_name": "fn", "content": "result"}],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 1
        assert normalized[0].tool_call_id == "12345"
        assert isinstance(normalized[0].tool_call_id, str)

    def test_deeply_nested_dict_content_in_list(self):
        nested = {"a": {"b": {"c": [1, 2, {"d": True}]}}}
        msg = Message(
            role="tool",
            content=[nested],
            tool_name="fn",
            tool_calls=[{"tool_call_id": "tc1", "tool_name": "fn", "content": nested}],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 1
        parsed = json.loads(normalized[0].content)
        assert parsed == nested

    def test_tool_result_with_single_quotes_python_repr(self):
        bad_str = "{'key': 'value'}"
        msg = _canonical("tc1", bad_str, "fn")
        normalized = normalize_tool_result_messages([msg])
        assert normalized[0].content == bad_str

    def test_tool_result_with_unicode(self):
        msg = _canonical("tc1", '{"emoji": "\\u2764", "text": "hello"}', "fn")
        normalized = normalize_tool_result_messages([msg])
        assert normalized[0].content is not None

    def test_very_large_content_list(self):
        items = [f'{{"idx": {i}}}' for i in range(50)]
        msg = Message(
            role="tool",
            content=items,
            tool_name=", ".join(f"fn_{i}" for i in range(50)),
            tool_calls=[{"tool_call_id": f"tc_{i}", "tool_name": f"fn_{i}", "content": items[i]} for i in range(50)],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 50
        for i, n in enumerate(normalized):
            assert n.tool_call_id == f"tc_{i}"

    def test_content_list_shorter_than_tool_calls(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "tc1", "tool_name": "a", "content": "r1"},
                {"tool_call_id": "tc2", "tool_name": "b", "content": "r2"},
            ],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 2
        assert normalized[0].content == "r1"
        assert normalized[1].content == "r2"

    def test_content_list_longer_than_tool_calls(self):
        msg = Message(
            role="tool",
            content=["r1", "r2", "r3"],
            tool_name="a",
            tool_calls=[
                {"tool_call_id": "tc1", "tool_name": "a", "content": "r1"},
            ],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 1
        assert normalized[0].content == "r1"

    def test_gemini_combined_with_tool_call_error(self):
        msg = Message(
            role="tool",
            content=["error: division by zero"],
            tool_name="divide",
            tool_call_error=True,
            tool_calls=[{"tool_call_id": "tc1", "tool_name": "divide", "content": "error: division by zero"}],
        )
        normalized = normalize_tool_result_messages([msg])
        assert len(normalized) == 1
        assert normalized[0].tool_call_id == "tc1"
        assert "division by zero" in normalized[0].content


# ──────────────────────────────────────────────────────────────────────
# Bedrock formatter integration
# ──────────────────────────────────────────────────────────────────────


class TestBedrockFormatterWithGeminiMessages:
    def _format(self, messages):
        from agno.models.aws.bedrock import AwsBedrock

        model = AwsBedrock.__new__(AwsBedrock)
        return model._format_messages(messages)

    def test_single_gemini_tool_result(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "fn", {})]),
            _gemini_combined([("tc1", "fn", "result")]),
            _assistant("done"),
        ]
        formatted, sys_msg = self._format(msgs)
        tool_results = []
        for m in formatted:
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and "toolResult" in c:
                        tool_results.append(c["toolResult"])
        assert len(tool_results) == 1
        assert tool_results[0]["toolUseId"] == "tc1"

    def test_multiple_gemini_tool_results_merged(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "a", {}), ("tc2", "b", {})]),
            _gemini_combined([("tc1", "a", "r1"), ("tc2", "b", "r2")]),
            _assistant("done"),
        ]
        formatted, _ = self._format(msgs)
        user_with_tools = [
            m
            for m in formatted
            if m.get("role") == "user"
            and isinstance(m.get("content"), list)
            and any("toolResult" in c for c in m["content"] if isinstance(c, dict))
        ]
        assert len(user_with_tools) == 1
        tool_results = [
            c["toolResult"] for c in user_with_tools[0]["content"] if isinstance(c, dict) and "toolResult" in c
        ]
        assert len(tool_results) == 2
        assert tool_results[0]["toolUseId"] == "tc1"
        assert tool_results[1]["toolUseId"] == "tc2"

    def test_dict_content_serialized_for_bedrock(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("tc1", "fn", {})]),
            _gemini_combined([("tc1", "fn", {"data": [1, 2, 3]})]),
            _assistant("done"),
        ]
        formatted, _ = self._format(msgs)
        tool_results = []
        for m in formatted:
            if m.get("role") == "user":
                for c in m.get("content", []):
                    if isinstance(c, dict) and "toolResult" in c:
                        tool_results.append(c["toolResult"])
        assert len(tool_results) == 1
        result_content = tool_results[0]["content"][0]["json"]["result"]
        assert isinstance(result_content, str)
        parsed = json.loads(result_content)
        assert parsed == {"data": [1, 2, 3]}


# ──────────────────────────────────────────────────────────────────────
# Gemini formatter integration (inline handling, no normalizer)
# ──────────────────────────────────────────────────────────────────────


class TestGeminiFormatterWithCanonicalMessages:
    def _format(self, messages):
        from agno.models.google.gemini import Gemini

        model = Gemini.__new__(Gemini)
        model.reverse_role_map = {"user": "user", "assistant": "model", "tool": "user", "system": "system"}
        return model._format_messages(messages)

    def test_canonical_tool_result_accepted(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("oai-1", "fn", {})]),
            _canonical("oai-1", "result", "fn"),
            _assistant("done"),
        ]
        formatted, _ = self._format(msgs)
        tool_parts = []
        for content in formatted:
            for part in content.parts:
                if hasattr(part, "function_response") and part.function_response is not None:
                    tool_parts.append(part)
        assert len(tool_parts) == 1

    def test_multiple_canonical_results_merged_into_one_content(self):
        msgs = [
            _system("sys"),
            _user("go"),
            _assistant_with_tool_calls([("oai-1", "a", {}), ("oai-2", "b", {})]),
            _canonical("oai-1", "r1", "a"),
            _canonical("oai-2", "r2", "b"),
            _assistant("done"),
        ]
        formatted, _ = self._format(msgs)
        tool_contents = [
            c
            for c in formatted
            if any(hasattr(p, "function_response") and p.function_response is not None for p in c.parts)
        ]
        assert len(tool_contents) == 1
        assert len(tool_contents[0].parts) == 2


class TestResolveToolCallId:
    def test_prefers_tool_call_id_over_id(self):
        tc = {"tool_call_id": "first", "id": "second"}
        assert resolve_tool_call_id(tc) == "first"

    def test_falls_back_to_id(self):
        tc = {"id": "only"}
        assert resolve_tool_call_id(tc) == "only"

    def test_falls_back_to_call_id(self):
        tc = {"call_id": "third"}
        assert resolve_tool_call_id(tc) == "third"

    def test_returns_none_when_all_missing(self):
        tc = {"name": "fn", "content": "result"}
        assert resolve_tool_call_id(tc) is None

    def test_skips_none_values(self):
        tc = {"tool_call_id": None, "id": "fallback"}
        assert resolve_tool_call_id(tc) == "fallback"

    def test_empty_string_not_skipped(self):
        tc = {"tool_call_id": "", "id": "fallback"}
        assert resolve_tool_call_id(tc) == ""

    def test_numeric_cast_to_string(self):
        tc = {"id": 42}
        assert resolve_tool_call_id(tc) == "42"
