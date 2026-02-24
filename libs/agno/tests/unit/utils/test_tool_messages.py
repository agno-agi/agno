from agno.models.message import Message
from agno.utils.models.tool_messages import normalize_tool_result_messages, tool_result_text


def _gemini_combined(tool_calls_data):
    return Message(
        role="tool",
        content=[tc[2] for tc in tool_calls_data],
        tool_name=", ".join(tc[1] for tc in tool_calls_data),
        tool_calls=[{"tool_call_id": tc[0], "tool_name": tc[1], "content": tc[2]} for tc in tool_calls_data],
    )


def _canonical(tool_call_id, content, tool_name="func"):
    return Message(role="tool", content=content, tool_call_id=tool_call_id, tool_name=tool_name)


class TestToolResultText:
    def test_none_returns_empty(self):
        assert tool_result_text(None) == ""

    def test_string_passthrough(self):
        assert tool_result_text("hello") == "hello"

    def test_list_joined(self):
        assert tool_result_text(["a", "b", "c"]) == "a\nb\nc"

    def test_list_with_none_filtered(self):
        assert tool_result_text(["a", None, "b"]) == "a\nb"

    def test_number(self):
        assert tool_result_text(42) == "42"


class TestNonToolPassthrough:
    def test_user_and_assistant_unchanged(self):
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="world"),
        ]
        result = normalize_tool_result_messages(msgs)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    def test_system_message_unchanged(self):
        msgs = [Message(role="system", content="You are helpful")]
        result = normalize_tool_result_messages(msgs)
        assert len(result) == 1
        assert result[0].content == "You are helpful"


class TestSplitGeminiCombined:
    def test_two_tools(self):
        combined = _gemini_combined(
            [
                ("call_1", "add", '{"result": 3}'),
                ("call_2", "multiply", '{"result": 6}'),
            ]
        )
        result = normalize_tool_result_messages([combined])
        assert len(result) == 2
        assert result[0].tool_call_id == "call_1"
        assert result[0].tool_name == "add"
        assert result[0].content == '{"result": 3}'
        assert result[1].tool_call_id == "call_2"
        assert result[1].tool_name == "multiply"
        assert result[1].content == '{"result": 6}'

    def test_three_tools(self):
        combined = _gemini_combined(
            [
                ("call_1", "a", "r1"),
                ("call_2", "b", "r2"),
                ("call_3", "c", "r3"),
            ]
        )
        result = normalize_tool_result_messages([combined])
        assert len(result) == 3
        for i, r in enumerate(result):
            assert r.tool_call_id == f"call_{i + 1}"
            assert r.role == "tool"

    def test_skips_entry_without_id(self):
        combined = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"tool_name": "func"}],
        )
        result = normalize_tool_result_messages([combined])
        assert len(result) == 0

    def test_tool_name_fallback_from_comma_separated(self):
        combined = Message(
            role="tool",
            content=["r1", "r2"],
            tool_name="add, multiply",
            tool_calls=[
                {"tool_call_id": "c1", "content": "r1"},
                {"tool_call_id": "c2", "content": "r2"},
            ],
        )
        result = normalize_tool_result_messages([combined])
        assert result[0].tool_name == "add"
        assert result[1].tool_name == "multiply"


class TestCanonicalPassthrough:
    def test_canonical_string_content(self):
        msg = _canonical("call_1", "result", "func")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0] is msg

    def test_canonical_list_content_normalized(self):
        msg = Message(role="tool", content=["a", "b"], tool_call_id="call_1", tool_name="func")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].content == "a\nb"
        assert result[0].tool_call_id == "call_1"


class TestCompression:
    def test_compressed_content_from_tool_calls(self):
        combined = Message(
            role="tool",
            content=["original_full_result"],
            tool_name="func",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "func", "content": "compressed_summary"}],
        )
        result = normalize_tool_result_messages([combined], compress_tool_results=True)
        assert len(result) == 1
        assert result[0].content == "original_full_result"
        assert result[0].compressed_content == "compressed_summary"

    def test_no_compression_when_disabled(self):
        combined = Message(
            role="tool",
            content=["original"],
            tool_name="func",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "func", "content": "compressed"}],
        )
        result = normalize_tool_result_messages([combined], compress_tool_results=False)
        assert result[0].compressed_content is None


class TestDBRoundTrip:
    def test_serialize_deserialize_normalize(self):
        combined = _gemini_combined(
            [
                ("call_1", "add", '{"result": 3}'),
                ("call_2", "multiply", '{"result": 6}'),
            ]
        )
        serialized = combined.to_dict()
        restored = Message.from_dict(serialized)

        assert isinstance(restored.content, list)
        assert restored.tool_call_id is None

        result = normalize_tool_result_messages([restored])
        assert len(result) == 2
        assert result[0].tool_call_id == "call_1"
        assert result[0].content == '{"result": 3}'
        assert result[1].tool_call_id == "call_2"
        assert result[1].content == '{"result": 6}'


class TestEdgeCases:
    def test_compression_with_dict_content_stringified(self):
        msg = Message(
            role="tool",
            content=[{"full": "result"}],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": {"summary": "short"}}],
        )
        out = normalize_tool_result_messages([msg], compress_tool_results=True)
        assert len(out) == 1
        assert isinstance(out[0].compressed_content, str)
        assert "summary" in out[0].compressed_content

    def test_compression_with_list_content_stringified(self):
        msg = Message(
            role="tool",
            content=["full result"],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": ["line1", "line2"]}],
        )
        out = normalize_tool_result_messages([msg], compress_tool_results=True)
        assert isinstance(out[0].compressed_content, str)

    def test_alternate_id_key_id(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == "c1"

    def test_alternate_id_key_call_id(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"call_id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == "c1"

    def test_content_length_mismatch_falls_back_to_tc_content(self):
        msg = Message(
            role="tool",
            content=["only-first"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "tc1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "tc2"},
            ],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 2
        assert result[0].content == "only-first"
        assert result[1].content == "tc2"

    def test_single_tool_in_combined_format(self):
        msg = Message(
            role="tool",
            content=["result"],
            tool_name="fn",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "result"}],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == "c1"
        assert result[0].content == "result"

    def test_empty_tool_calls_list_passes_through(self):
        msg = Message(role="tool", content="result", tool_call_id="c1", tool_name="fn", tool_calls=[])
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == "c1"

    def test_none_content_passthrough(self):
        msg = Message(role="tool", content=None, tool_call_id="c1", tool_name="fn")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].content is None

    def test_dict_content_in_original(self):
        msg = Message(
            role="tool",
            content=[{"key": "value"}],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "compressed"}],
        )
        result = normalize_tool_result_messages([msg], compress_tool_results=False)
        assert result[0].content == "{'key': 'value'}"

    def test_missing_tc_content_falls_back_to_original(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a"},
                {"tool_call_id": "c2", "tool_name": "b"},
            ],
        )
        result = normalize_tool_result_messages([msg])
        assert result[0].content == "r1"
        assert result[1].content == "r2"


class TestNoneFieldPassthrough:
    def test_none_tool_call_id_passes_through(self):
        msg = Message(role="tool", content="result", tool_call_id=None, tool_name="fn")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id is None
        assert result[0].tool_name == "fn"
        assert result[0].content == "result"

    def test_none_tool_name_passes_through(self):
        msg = Message(role="tool", content="result", tool_call_id="c1", tool_name=None)
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == "c1"
        assert result[0].tool_name is None

    def test_non_tool_message_not_affected(self):
        msg = Message(role="user", content="hello")
        result = normalize_tool_result_messages([msg])
        assert result[0] is msg

    def test_canonical_with_ids_set_unchanged(self):
        msg = _canonical("c1", "result", "fn")
        result = normalize_tool_result_messages([msg])
        assert result[0] is msg

    def test_none_tool_call_id_with_list_content_normalizes_content(self):
        msg = Message(role="tool", content=["a", "b"], tool_call_id=None, tool_name="fn")
        result = normalize_tool_result_messages([msg])
        assert result[0].tool_call_id is None
        assert result[0].content == "a\nb"


class TestMixedMessages:
    def test_mixed_conversation(self):
        msgs = [
            Message(role="user", content="Calculate 2+3"),
            Message(
                role="assistant",
                tool_calls=[
                    {"id": "c1", "type": "function", "function": {"name": "add", "arguments": '{"a":2,"b":3}'}}
                ],
            ),
            _gemini_combined([("c1", "add", '{"result": 5}')]),
            Message(role="assistant", content="The result is 5"),
            Message(role="user", content="Now multiply by 2"),
            Message(
                role="assistant",
                tool_calls=[
                    {"id": "c2", "type": "function", "function": {"name": "multiply", "arguments": '{"a":5,"b":2}'}}
                ],
            ),
            _canonical("c2", '{"result": 10}', "multiply"),
        ]
        result = normalize_tool_result_messages(msgs)
        assert len(result) == 7
        assert result[2].tool_call_id == "c1"
        assert result[2].tool_name == "add"
        assert result[6].tool_call_id == "c2"
        assert result[6].content == '{"result": 10}'
