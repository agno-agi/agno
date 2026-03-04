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
        assert result[0].content == '{"key": "value"}'

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


class TestIdempotency:
    def test_double_normalize_produces_same_result(self):
        combined = _gemini_combined([("c1", "a", "r1"), ("c2", "b", "r2")])
        once = normalize_tool_result_messages([combined], compress_tool_results=True)
        twice = normalize_tool_result_messages(once, compress_tool_results=True)
        assert [(m.tool_call_id, m.content, m.tool_name, m.compressed_content) for m in twice] == [
            (m.tool_call_id, m.content, m.tool_name, m.compressed_content) for m in once
        ]

    def test_triple_normalize_stable(self):
        combined = _gemini_combined([("c1", "fn", "result")])
        first = normalize_tool_result_messages([combined])
        second = normalize_tool_result_messages(first)
        third = normalize_tool_result_messages(second)
        assert len(third) == 1
        assert third[0].tool_call_id == "c1"
        assert third[0].content == "result"


class TestEmptyStringToolCallId:
    def test_empty_string_id_not_treated_as_missing(self):
        msg = Message(role="tool", content="result", tool_call_id="", tool_name="fn")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == ""
        assert result[0].content == "result"

    def test_empty_string_id_with_tool_calls_does_not_split(self):
        msg = Message(
            role="tool",
            content="result",
            tool_call_id="",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == ""

    def test_empty_string_id_with_list_content_normalizes(self):
        msg = Message(role="tool", content=["a", "b"], tool_call_id="", tool_name="fn")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].content == "a\nb"
        assert result[0].tool_call_id == ""


class TestNonStringToolCallId:
    def test_integer_id_cast_to_string(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"tool_call_id": 123, "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].tool_call_id == "123"

    def test_float_id_cast_to_string(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"tool_call_id": 1.5, "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert result[0].tool_call_id == "1.5"

    def test_bool_id_cast_to_string(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"tool_call_id": True, "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert result[0].tool_call_id == "True"


class TestSplitFieldPreservation:
    def test_provider_data_preserved(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            provider_data={"gemini_safety": {"rating": "safe"}},
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "r1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "r2"},
            ],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 2
        assert result[0].provider_data == {"gemini_safety": {"rating": "safe"}}
        assert result[1].provider_data == {"gemini_safety": {"rating": "safe"}}

    def test_from_history_preserved(self):
        msg = Message(
            role="tool",
            content=["r1"],
            from_history=True,
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        result = normalize_tool_result_messages([msg])
        assert result[0].from_history is True

    def test_created_at_preserved(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        original_ts = msg.created_at
        result = normalize_tool_result_messages([msg])
        assert result[0].created_at == original_ts

    def test_metrics_not_shared_between_splits(self):
        msg = _gemini_combined([("c1", "a", "r1"), ("c2", "b", "r2")])
        result = normalize_tool_result_messages([msg])
        assert result[0].metrics is not result[1].metrics
        assert result[0].metrics is not msg.metrics


class TestMixedContentTypes:
    def test_content_list_with_dict_item(self):
        msg = Message(
            role="tool",
            content=[{"nested": {"key": [1, 2]}}],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "compressed"}],
        )
        result = normalize_tool_result_messages([msg])
        assert "nested" in result[0].content

    def test_content_list_with_int_item(self):
        msg = Message(
            role="tool",
            content=[42],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "compressed"}],
        )
        result = normalize_tool_result_messages([msg])
        assert result[0].content == "42"

    def test_content_list_with_none_item_falls_back_to_tc(self):
        msg = Message(
            role="tool",
            content=[None],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "fallback"}],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].content is None or result[0].content == "fallback"

    def test_content_list_with_mixed_types(self):
        msg = Message(
            role="tool",
            content=["plain", {"nested": True}, 7],
            tool_name="a, b, c",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "x1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "x2"},
                {"tool_call_id": "c3", "tool_name": "c", "content": "x3"},
            ],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 3
        assert result[0].content == "plain"
        assert "nested" in result[1].content
        assert result[2].content == "7"


class TestScalarContentWithMultipleToolCalls:
    def test_scalar_content_reused_for_each_split(self):
        msg = Message(
            role="tool",
            content="shared-output",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "tc1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "tc2"},
            ],
        )
        result = normalize_tool_result_messages([msg])
        assert len(result) == 2
        assert result[0].content == "shared-output"
        assert result[1].content == "shared-output"


class TestToolNameFallbackOverflow:
    def test_names_shorter_than_tool_calls(self):
        msg = Message(
            role="tool",
            content=["r1", "r2", "r3"],
            tool_name="first, second",
            tool_calls=[
                {"tool_call_id": "c1", "content": "x1"},
                {"tool_call_id": "c2", "content": "x2"},
                {"tool_call_id": "c3", "content": "x3"},
            ],
        )
        result = normalize_tool_result_messages([msg])
        assert result[0].tool_name == "first"
        assert result[1].tool_name == "second"
        assert result[2].tool_name is None


class TestFunctionRolePassthrough:
    def test_function_role_not_processed_as_tool(self):
        msg = Message(role="function", name="legacy_fn", content='{"ok": true}')
        result = normalize_tool_result_messages([msg])
        assert result[0] is msg

    def test_function_role_content_not_modified(self):
        msg = Message(role="function", content=["a", "b"])
        result = normalize_tool_result_messages([msg])
        assert result[0] is msg
        assert result[0].content == ["a", "b"]


class TestCombinedWithoutToolCalls:
    def test_list_content_no_tool_calls_normalizes_content(self):
        msg = Message(role="tool", content=["r1", "r2"], tool_name="a, b")
        result = normalize_tool_result_messages([msg])
        assert len(result) == 1
        assert result[0].content == "r1\nr2"

    def test_list_content_no_tool_calls_preserves_tool_call_id(self):
        msg = Message(role="tool", content=["r1"], tool_call_id="c1", tool_name="fn")
        result = normalize_tool_result_messages([msg])
        assert result[0].tool_call_id == "c1"
        assert result[0].content == "r1"


class TestLargeMessages:
    def test_100_tool_calls(self):
        tool_calls_data = [(f"call_{i}", f"tool_{i}", f"result_{i}") for i in range(100)]
        combined = _gemini_combined(tool_calls_data)
        result = normalize_tool_result_messages([combined])
        assert len(result) == 100
        assert result[0].tool_call_id == "call_0"
        assert result[0].content == "result_0"
        assert result[99].tool_call_id == "call_99"
        assert result[99].content == "result_99"

    def test_100_tool_calls_with_compression(self):
        tool_calls_data = [(f"call_{i}", f"tool_{i}", f"result_{i}") for i in range(100)]
        combined = _gemini_combined(tool_calls_data)
        result = normalize_tool_result_messages([combined], compress_tool_results=True)
        assert len(result) == 100
        for i, msg in enumerate(result):
            assert msg.tool_call_id == f"call_{i}"
            assert msg.compressed_content == f"result_{i}"


class TestNestedJsonRoundTrip:
    def test_nested_dict_through_normalize_serialize_restore(self):
        msg = Message(
            role="tool",
            content=[{"outer": {"inner": [1, {"deep": True}]}}],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": {"summary": {"tokens": [1, 2, 3]}}}],
        )
        normalized = normalize_tool_result_messages([msg], compress_tool_results=True)
        assert len(normalized) == 1
        assert "outer" in normalized[0].content
        assert normalized[0].compressed_content is not None

        serialized = normalized[0].to_dict()
        restored = Message.from_dict(serialized)
        renormalized = normalize_tool_result_messages([restored], compress_tool_results=True)
        assert renormalized[0].tool_call_id == "c1"
        assert renormalized[0].content == normalized[0].content


class TestInputNotMutated:
    def test_original_messages_list_unchanged(self):
        combined = _gemini_combined([("c1", "a", "r1"), ("c2", "b", "r2")])
        original_msgs = [combined]
        original_len = len(original_msgs)
        original_content = combined.content.copy() if isinstance(combined.content, list) else combined.content
        original_tc = combined.tool_calls.copy() if combined.tool_calls else None

        normalize_tool_result_messages(original_msgs)

        assert len(original_msgs) == original_len
        assert combined.content == original_content
        assert combined.tool_calls == original_tc

    def test_original_message_fields_not_modified(self):
        msg = Message(role="tool", content=["a", "b"], tool_call_id="c1", tool_name="fn")
        original_content = msg.content.copy()
        normalize_tool_result_messages([msg])
        assert msg.content == original_content
