import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-testing")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-testing")

from unittest.mock import patch

import pytest

from agno.models.message import Message

try:
    import anthropic.types  # noqa: F401

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    import google.genai  # noqa: F401

    HAS_GOOGLE_GENAI = True
except ImportError:
    HAS_GOOGLE_GENAI = False

try:
    import boto3  # noqa: F401

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

try:
    import mistralai  # noqa: F401

    HAS_MISTRAL = True
except ImportError:
    HAS_MISTRAL = False

requires_anthropic = pytest.mark.skipif(not HAS_ANTHROPIC, reason="anthropic SDK not installed")
requires_google_genai = pytest.mark.skipif(not HAS_GOOGLE_GENAI, reason="google-genai SDK not installed")
requires_boto3 = pytest.mark.skipif(not HAS_BOTO3, reason="boto3 not installed")
requires_mistral = pytest.mark.skipif(not HAS_MISTRAL, reason="mistralai SDK not installed")


def _gemini_combined(tool_calls_data):
    return Message(
        role="tool",
        content=[tc[2] for tc in tool_calls_data],
        tool_name=", ".join(tc[1] for tc in tool_calls_data),
        tool_calls=[{"tool_call_id": tc[0], "tool_name": tc[1], "content": tc[2]} for tc in tool_calls_data],
    )


def _canonical(tool_call_id, content, tool_name="func"):
    return Message(role="tool", content=content, tool_call_id=tool_call_id, tool_name=tool_name)


def _assistant_with_tool_calls(call_ids, names):
    return Message(
        role="assistant",
        tool_calls=[
            {"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}
            for cid, name in zip(call_ids, names)
        ],
    )


class TestOpenAIChatCrossProvider:
    def setup_method(self):
        from agno.models.openai.chat import OpenAIChat

        self.model = OpenAIChat(id="gpt-4o-mini")

    def test_canonical_message_formats_correctly(self):
        msg = _canonical("call_1", '{"result": 5}', "add")
        fmt = self.model._format_message(msg)
        assert fmt["role"] == "tool"
        assert fmt["content"] == '{"result": 5}'
        assert fmt["tool_call_id"] == "call_1"

    def test_gemini_combined_splits(self):
        combined = _gemini_combined(
            [
                ("call_1", "add", '{"result": 3}'),
                ("call_2", "multiply", '{"result": 6}'),
            ]
        )
        fmt = self.model._format_messages([combined])
        assert len(fmt) == 2
        assert fmt[0]["tool_call_id"] == "call_1"
        assert fmt[1]["tool_call_id"] == "call_2"

    def test_db_round_trip_combined(self):
        combined = _gemini_combined([("c1", "add", "r1"), ("c2", "sub", "r2")])
        restored = Message.from_dict(combined.to_dict())
        fmt = self.model._format_messages([restored])
        assert len(fmt) == 2
        assert fmt[0]["tool_call_id"] == "c1"
        assert fmt[1]["tool_call_id"] == "c2"


@requires_anthropic
class TestClaudeCrossProvider:
    def test_canonical_message_formats_correctly(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["call_1"], ["add"]),
            _canonical("call_1", '{"result": 5}', "add"),
        ]
        chat_msgs, _ = format_messages(msgs)
        tool_msg = chat_msgs[2]
        assert tool_msg["role"] == "user"
        tool_result = tool_msg["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "call_1"
        assert tool_result["content"] == '{"result": 5}'

    def test_gemini_combined_splits_into_tool_results(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            _gemini_combined([("c1", "add", "r1"), ("c2", "mul", "r2")]),
        ]
        chat_msgs, _ = format_messages(msgs)
        # The tool results should be in a single user message (merged for alternation)
        tool_msg = chat_msgs[2]
        assert tool_msg["role"] == "user"
        assert len(tool_msg["content"]) == 2
        assert tool_msg["content"][0]["tool_use_id"] == "c1"
        assert tool_msg["content"][1]["tool_use_id"] == "c2"

    def test_consecutive_canonical_tools_merged(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            _canonical("c1", "r1", "add"),
            _canonical("c2", "r2", "mul"),
        ]
        chat_msgs, _ = format_messages(msgs)
        # Two consecutive tool messages should merge into one user message
        tool_msg = chat_msgs[2]
        assert tool_msg["role"] == "user"
        assert len(tool_msg["content"]) == 2
        assert tool_msg["content"][0]["tool_use_id"] == "c1"
        assert tool_msg["content"][1]["tool_use_id"] == "c2"

    def test_list_content_stringified(self):
        from agno.utils.models.claude import format_messages

        msg_with_list = Message(role="tool", content=["a", "b"], tool_call_id="c1", tool_name="func")
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["func"]),
            msg_with_list,
        ]
        chat_msgs, _ = format_messages(msgs)
        tool_result = chat_msgs[2]["content"][0]
        assert isinstance(tool_result["content"], str)
        assert tool_result["content"] == "a\nb"

    def test_db_round_trip_combined(self):
        from agno.utils.models.claude import format_messages

        combined = _gemini_combined([("c1", "add", "r1"), ("c2", "mul", "r2")])
        restored = Message.from_dict(combined.to_dict())
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            restored,
        ]
        chat_msgs, _ = format_messages(msgs)
        tool_msg = chat_msgs[2]
        assert tool_msg["role"] == "user"
        assert len(tool_msg["content"]) == 2
        assert tool_msg["content"][0]["tool_use_id"] == "c1"


@requires_google_genai
class TestGeminiCrossProvider:
    def setup_method(self):
        with patch("agno.models.google.gemini.GeminiClient"):
            from agno.models.google.gemini import Gemini

            self.model = Gemini(id="gemini-2.0-flash")

    def test_canonical_message_produces_function_response(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["add"]),
            _canonical("c1", '{"result": 5}', "add"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        # Find the tool response content
        tool_content = None
        for content in formatted:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if hasattr(part, "function_response") and part.function_response is not None:
                        tool_content = content
                        break
        assert tool_content is not None
        func_resp = tool_content.parts[0]
        assert func_resp.function_response.name == "add"

    def test_consecutive_canonical_messages_grouped(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            _canonical("c1", "r1", "add"),
            _canonical("c2", "r2", "mul"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        # Find tool content — consecutive tool messages should be merged into one Content
        tool_contents = []
        for content in formatted:
            if content.role == "user" and content.parts:
                has_func_resp = any(
                    hasattr(p, "function_response") and p.function_response is not None for p in content.parts
                )
                if has_func_resp:
                    tool_contents.append(content)
        assert len(tool_contents) == 1
        assert len(tool_contents[0].parts) == 2

    def test_gemini_combined_still_works(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            _gemini_combined([("c1", "add", "r1"), ("c2", "mul", "r2")]),
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_contents = []
        for content in formatted:
            if content.role == "user" and content.parts:
                has_func_resp = any(
                    hasattr(p, "function_response") and p.function_response is not None for p in content.parts
                )
                if has_func_resp:
                    tool_contents.append(content)
        assert len(tool_contents) == 1
        assert len(tool_contents[0].parts) == 2


@requires_boto3
class TestBedrockCrossProvider:
    def setup_method(self):
        with patch("agno.models.aws.bedrock.AwsClient"), patch("agno.models.aws.bedrock.Session"):
            from agno.models.aws.bedrock import AwsBedrock

            self.model = AwsBedrock(id="anthropic.claude-sonnet-4-20250514-v1:0")

    def test_canonical_message_formats_correctly(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["add"]),
            _canonical("c1", '{"result": 5}', "add"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_msg = next(m for m in formatted if "toolResult" in str(m.get("content", [])))
        tool_result = tool_msg["content"][0]["toolResult"]
        assert tool_result["toolUseId"] == "c1"

    def test_gemini_combined_splits(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            _gemini_combined([("c1", "add", "r1"), ("c2", "mul", "r2")]),
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_msgs = [m for m in formatted if "toolResult" in str(m.get("content", []))]
        # Should be merged into one user message with 2 toolResult entries
        assert len(tool_msgs) == 1
        assert len(tool_msgs[0]["content"]) == 2

    def test_consecutive_canonical_merged(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2"], ["add", "mul"]),
            _canonical("c1", "r1", "add"),
            _canonical("c2", "r2", "mul"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_msgs = [m for m in formatted if "toolResult" in str(m.get("content", []))]
        assert len(tool_msgs) == 1
        assert len(tool_msgs[0]["content"]) == 2


@pytest.mark.skipif(not HAS_ANTHROPIC or not HAS_GOOGLE_GENAI, reason="requires anthropic + google-genai")
class TestThreeProviderCycle:
    def test_gemini_to_openai_to_claude(self):
        from agno.models.openai.chat import OpenAIChat
        from agno.utils.models.claude import format_messages as claude_format

        # Gemini creates combined tool message
        gemini_combined = _gemini_combined([("c1", "add", '{"result": 5}')])

        conversation = [
            Message(role="user", content="What is 2+3?"),
            _assistant_with_tool_calls(["c1"], ["add"]),
            gemini_combined,
            Message(role="assistant", content="The result is 5"),
            Message(role="user", content="Now multiply by 2"),
            _assistant_with_tool_calls(["c2"], ["multiply"]),
            _canonical("c2", '{"result": 10}', "multiply"),
            Message(role="assistant", content="The result is 10"),
        ]

        # DB round-trip
        serialized = [m.to_dict() for m in conversation]
        restored = [Message.from_dict(d) for d in serialized]

        # OpenAI reads it
        openai_model = OpenAIChat(id="gpt-4o-mini")
        openai_formatted = openai_model._format_messages(restored)
        tool_msgs = [m for m in openai_formatted if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        assert all(isinstance(m["content"], str) for m in tool_msgs)

        # Claude reads it
        claude_formatted, _ = claude_format(restored)
        claude_tool_blocks = []
        for msg in claude_formatted:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        claude_tool_blocks.append(block)
        assert len(claude_tool_blocks) == 2
        assert claude_tool_blocks[0]["tool_use_id"] == "c1"
        assert claude_tool_blocks[1]["tool_use_id"] == "c2"

    def test_openai_to_claude_to_gemini(self):
        from agno.utils.models.claude import format_messages as claude_format

        with patch("agno.models.google.gemini.GeminiClient"):
            from agno.models.google.gemini import Gemini

            gemini_model = Gemini(id="gemini-2.0-flash")

        conversation = [
            Message(role="user", content="Calculate 10/2"),
            _assistant_with_tool_calls(["c1"], ["divide"]),
            _canonical("c1", '{"result": 5}', "divide"),
            Message(role="assistant", content="5"),
            Message(role="user", content="Square root of that"),
            _assistant_with_tool_calls(["c2"], ["sqrt"]),
            _canonical("c2", '{"result": 2.236}', "sqrt"),
            Message(role="assistant", content="2.236"),
        ]

        serialized = [m.to_dict() for m in conversation]
        restored = [Message.from_dict(d) for d in serialized]

        # Claude reads canonical messages
        claude_formatted, _ = claude_format(restored)
        claude_tool_blocks = []
        for msg in claude_formatted:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        claude_tool_blocks.append(block)
        assert len(claude_tool_blocks) == 2

        # Gemini reads canonical messages
        gemini_formatted, _ = gemini_model._format_messages(restored)
        func_response_count = 0
        for content in gemini_formatted:
            if hasattr(content, "parts"):
                for part in content.parts:
                    if hasattr(part, "function_response") and part.function_response is not None:
                        func_response_count += 1
        assert func_response_count == 2


class TestOpenAIChatEdgeCases:
    def setup_method(self):
        from agno.models.openai.chat import OpenAIChat

        self.model = OpenAIChat(id="gpt-4o-mini")

    def test_combined_respects_compression_flag(self):
        msg = Message(
            role="tool",
            content=["ORIGINAL_FULL"],
            tool_name="search",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "search", "content": "COMPRESSED"}],
        )
        fmt = self.model._format_messages([msg], compress_tool_results=False)
        assert fmt[0]["content"] == "ORIGINAL_FULL"

    def test_combined_uses_compressed_when_enabled(self):
        msg = Message(
            role="tool",
            content=["ORIGINAL_FULL"],
            tool_name="search",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "search", "content": "COMPRESSED"}],
        )
        fmt = self.model._format_messages([msg], compress_tool_results=True)
        assert fmt[0]["content"] == "COMPRESSED"

    def test_combined_accepts_id_fallback(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["tool_call_id"] == "c1"

    def test_combined_accepts_call_id_fallback(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"call_id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["tool_call_id"] == "c1"

    def test_combined_falls_back_to_message_content(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a"},
                {"tool_call_id": "c2", "tool_name": "b"},
            ],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 2
        assert fmt[0]["content"] == "r1"
        assert fmt[1]["content"] == "r2"

    def test_combined_content_length_mismatch(self):
        msg = Message(
            role="tool",
            content=["only-first"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "tc1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "tc2"},
            ],
        )
        fmt = self.model._format_messages([msg])
        assert fmt[0]["content"] == "only-first"
        assert fmt[1]["content"] == "tc2"


class TestOpenAIResponsesEdgeCases:
    def setup_method(self):
        from agno.models.openai.responses import OpenAIResponses

        self.model = OpenAIResponses(id="gpt-4o")

    def test_combined_respects_compression_flag(self):
        msg = Message(
            role="tool",
            content=["ORIGINAL_FULL"],
            tool_name="search",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "search", "content": "COMPRESSED"}],
        )
        fmt = self.model._format_messages([msg])
        assert fmt[0]["output"] == "ORIGINAL_FULL"

    def test_combined_accepts_id_fallback(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_calls=[{"id": "c1", "tool_name": "fn", "content": "r1"}],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["call_id"] == "c1"

    def test_combined_falls_back_to_message_content(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a"},
                {"tool_call_id": "c2", "tool_name": "b"},
            ],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 2
        assert fmt[0]["output"] == "r1"
        assert fmt[1]["output"] == "r2"

    def test_does_not_overwrite_tool_call_id_with_none(self):
        messages = []
        fc_results = [Message(role="tool", content="ok", tool_call_id="fallback_id", tool_name="fn")]
        self.model.format_function_call_results(messages, fc_results, tool_call_ids=[None])
        assert messages[0].tool_call_id == "fallback_id"


@requires_google_genai
class TestGeminiEdgeCases:
    def setup_method(self):
        with patch("agno.models.google.gemini.GeminiClient"):
            from agno.models.google.gemini import Gemini

            self.model = Gemini(id="gemini-2.0-flash")

    def test_combined_length_mismatch_uses_per_tool_fallback(self):
        msg = Message(
            role="tool",
            content=["only-first"],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "tc1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "tc2"},
            ],
        )
        formatted, _ = self.model._format_messages([msg])
        got = [p.function_response.response["result"] for p in formatted[0].parts]
        assert got == ["only-first", "tc2"]

    def test_combined_missing_tool_name_uses_fallback(self):
        msg = Message(
            role="tool",
            content=["r1"],
            tool_name="lookup",
            tool_calls=[{"tool_call_id": "c1", "content": "r1"}],
        )
        formatted, _ = self.model._format_messages([msg])
        assert formatted[0].parts[0].function_response.name == "lookup"

    def test_combined_missing_tool_name_comma_separated(self):
        msg = Message(
            role="tool",
            content=["r1", "r2"],
            tool_name="add, multiply",
            tool_calls=[
                {"tool_call_id": "c1", "content": "r1"},
                {"tool_call_id": "c2", "content": "r2"},
            ],
        )
        formatted, _ = self.model._format_messages([msg])
        names = [p.function_response.name for p in formatted[0].parts]
        assert names == ["add", "multiply"]


class TestOpenAIChatDeepEdgeCases:
    def setup_method(self):
        from agno.models.openai.chat import OpenAIChat

        self.model = OpenAIChat(id="gpt-4o-mini")

    def test_canonical_none_content_becomes_empty_string(self):
        msg = _canonical("c1", None, "fn")
        fmt = self.model._format_messages([msg])
        assert fmt[0]["content"] == ""

    def test_canonical_list_content_joined(self):
        msg = Message(role="tool", content=["a", "b"], tool_call_id="c1", tool_name="fn")
        fmt = self.model._format_messages([msg])
        assert fmt[0]["content"] == "a\nb"

    def test_combined_with_empty_content_list(self):
        msg = Message(
            role="tool",
            content=[],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "fallback"}],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["content"] == "fallback"

    def test_combined_dict_content_in_tc_stringified(self):
        msg = Message(
            role="tool",
            content=[{"full": "result"}],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": {"summary": "s"}}],
        )
        fmt = self.model._format_messages([msg], compress_tool_results=True)
        assert isinstance(fmt[0]["content"], str)

    def test_message_order_preserved_with_mixed_tools(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["add"]),
            _canonical("c1", "result1", "add"),
            Message(role="assistant", content="ok"),
            Message(role="user", content="again"),
            _assistant_with_tool_calls(["c2", "c3"], ["mul", "div"]),
            _gemini_combined([("c2", "mul", "r2"), ("c3", "div", "r3")]),
        ]
        fmt = self.model._format_messages(msgs)
        roles = [m.get("role") for m in fmt]
        assert roles == ["user", "assistant", "tool", "assistant", "user", "assistant", "tool", "tool"]


class TestOpenAIResponsesDeepEdgeCases:
    def setup_method(self):
        from agno.models.openai.responses import OpenAIResponses

        self.model = OpenAIResponses(id="gpt-4o")

    def test_canonical_none_content_emits_empty_output(self):
        msg = _canonical("c1", None, "fn")
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["output"] == ""

    def test_canonical_empty_string_content_preserved(self):
        msg = _canonical("c1", "", "fn")
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["output"] == ""

    def test_combined_compression_uses_tc_content(self):
        msg = Message(
            role="tool",
            content=["ORIGINAL"],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "COMPRESSED"}],
        )
        fmt = self.model._format_messages([msg], compress_tool_results=True)
        assert fmt[0]["output"] == "COMPRESSED"

    def test_combined_with_empty_content_list(self):
        msg = Message(
            role="tool",
            content=[],
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "fallback"}],
        )
        fmt = self.model._format_messages([msg])
        assert len(fmt) == 1
        assert fmt[0]["output"] == "fallback"

    def test_format_function_call_results_preserves_existing_id_when_list_shorter(self):
        messages = []
        fc_results = [
            Message(role="tool", content="r1", tool_call_id="existing_1", tool_name="fn"),
            Message(role="tool", content="r2", tool_call_id="existing_2", tool_name="fn"),
        ]
        self.model.format_function_call_results(messages, fc_results, tool_call_ids=["new_1"])
        assert messages[0].tool_call_id == "new_1"
        assert messages[1].tool_call_id == "existing_2"


@requires_google_genai
class TestGeminiDeepEdgeCases:
    def setup_method(self):
        with patch("agno.models.google.gemini.GeminiClient"):
            from agno.models.google.gemini import Gemini

            self.model = Gemini(id="gemini-2.0-flash")

    def test_canonical_after_combined_merges_correctly(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2", "c3"], ["a", "b", "c"]),
            _gemini_combined([("c1", "a", "r1"), ("c2", "b", "r2")]),
            _canonical("c3", "r3", "c"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_contents = [
            c
            for c in formatted
            if c.role == "user"
            and c.parts
            and hasattr(c.parts[0], "function_response")
            and c.parts[0].function_response is not None
        ]
        # All 3 tool responses should merge into one Content block
        assert len(tool_contents) == 1
        assert len(tool_contents[0].parts) == 3

    def test_canonical_none_content_handled(self):
        msg = _canonical("c1", None, "fn")
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            msg,
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_contents = [
            c
            for c in formatted
            if c.role == "user"
            and c.parts
            and hasattr(c.parts[0], "function_response")
            and c.parts[0].function_response is not None
        ]
        assert len(tool_contents) == 1
        assert tool_contents[0].parts[0].function_response.response["result"] == ""

    def test_tool_after_user_message_not_merged(self):
        msgs = [
            Message(role="user", content="question"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            _canonical("c1", "result", "fn"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        # user, model (assistant), user (tool) — 3 Content blocks, tool not merged into first user
        assert len(formatted) == 3


@requires_anthropic
class TestClaudeDeepEdgeCases:
    def test_tool_after_regular_user_not_merged(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="question"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            _canonical("c1", "result", "fn"),
        ]
        chat_msgs, _ = format_messages(msgs)
        assert chat_msgs[0]["role"] == "user"
        assert isinstance(chat_msgs[0]["content"], list)
        assert chat_msgs[0]["content"][0]["type"] == "text"
        # Tool result should be separate user message, not merged into first user
        assert chat_msgs[2]["role"] == "user"
        assert chat_msgs[2]["content"][0]["type"] == "tool_result"

    def test_none_content_tool_still_formats(self):
        from agno.utils.models.claude import format_messages

        msg = _canonical("c1", None, "fn")
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            msg,
        ]
        chat_msgs, _ = format_messages(msgs)
        tool_result = chat_msgs[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "c1"
        assert tool_result["content"] == ""

    def test_three_consecutive_tools_all_merged(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2", "c3"], ["a", "b", "c"]),
            _canonical("c1", "r1", "a"),
            _canonical("c2", "r2", "b"),
            _canonical("c3", "r3", "c"),
        ]
        chat_msgs, _ = format_messages(msgs)
        tool_msg = chat_msgs[2]
        assert tool_msg["role"] == "user"
        assert len(tool_msg["content"]) == 3
        assert all(b["type"] == "tool_result" for b in tool_msg["content"])

    def test_combined_then_canonical_all_merged(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2", "c3"], ["a", "b", "c"]),
            _gemini_combined([("c1", "a", "r1"), ("c2", "b", "r2")]),
            _canonical("c3", "r3", "c"),
        ]
        chat_msgs, _ = format_messages(msgs)
        tool_msg = chat_msgs[2]
        assert tool_msg["role"] == "user"
        assert len(tool_msg["content"]) == 3

    def test_compression_with_combined_message(self):
        from agno.utils.models.claude import format_messages

        combined = Message(
            role="tool",
            content=["ORIGINAL"],
            tool_name="fn",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "fn", "content": "COMPRESSED"}],
        )
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            combined,
        ]
        chat_compressed, _ = format_messages(msgs, compress_tool_results=True)
        assert chat_compressed[2]["content"][0]["content"] == "COMPRESSED"

        chat_original, _ = format_messages(msgs, compress_tool_results=False)
        assert chat_original[2]["content"][0]["content"] == "ORIGINAL"


@requires_boto3
class TestBedrockDeepEdgeCases:
    def setup_method(self):
        with patch("agno.models.aws.bedrock.AwsClient"), patch("agno.models.aws.bedrock.Session"):
            from agno.models.aws.bedrock import AwsBedrock

            self.model = AwsBedrock(id="anthropic.claude-sonnet-4-20250514-v1:0")

    def test_tool_after_regular_user_not_merged(self):
        msgs = [
            Message(role="user", content="question"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            _canonical("c1", "result", "fn"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        user_msgs = [m for m in formatted if m.get("role") == "user"]
        # First user msg is text, second is tool result — NOT merged
        assert len(user_msgs) == 2

    def test_three_consecutive_tools_merged(self):
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1", "c2", "c3"], ["a", "b", "c"]),
            _canonical("c1", "r1", "a"),
            _canonical("c2", "r2", "b"),
            _canonical("c3", "r3", "c"),
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_msgs = [m for m in formatted if "toolResult" in str(m.get("content", []))]
        assert len(tool_msgs) == 1
        assert len(tool_msgs[0]["content"]) == 3

    def test_none_content_tool_handled(self):
        msg = _canonical("c1", None, "fn")
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            msg,
        ]
        formatted, _ = self.model._format_messages(msgs)
        tool_msgs = [m for m in formatted if "toolResult" in str(m.get("content", []))]
        assert len(tool_msgs) == 1


class TestDBRoundTripEdgeCases:
    def test_combined_with_dict_content_survives_round_trip(self):
        msg = Message(
            role="tool",
            content=[{"key": "value"}, {"key2": "value2"}],
            tool_name="a, b",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "a", "content": "compressed1"},
                {"tool_call_id": "c2", "tool_name": "b", "content": "compressed2"},
            ],
        )
        serialized = msg.to_dict()
        restored = Message.from_dict(serialized)

        from agno.utils.models.tool_messages import normalize_tool_result_messages

        result = normalize_tool_result_messages([restored])
        assert len(result) == 2
        assert result[0].tool_call_id == "c1"
        assert result[1].tool_call_id == "c2"

    def test_canonical_with_compressed_content_survives_round_trip(self):
        msg = Message(
            role="tool",
            content="original full",
            compressed_content="short",
            tool_call_id="c1",
            tool_name="fn",
        )
        serialized = msg.to_dict()
        restored = Message.from_dict(serialized)

        assert restored.content == "original full"
        assert restored.compressed_content == "short"
        assert restored.tool_call_id == "c1"
        assert restored.get_content(use_compressed_content=True) == "short"
        assert restored.get_content(use_compressed_content=False) == "original full"

    def test_compressed_content_none_falls_back_to_original(self):
        msg = Message(
            role="tool",
            content="original",
            compressed_content=None,
            tool_call_id="c1",
            tool_name="fn",
        )
        assert msg.get_content(use_compressed_content=True) == "original"

    def test_full_cross_provider_round_trip_with_compression(self):
        from agno.models.openai.chat import OpenAIChat
        from agno.utils.models.tool_messages import normalize_tool_result_messages

        combined = Message(
            role="tool",
            content=["ORIG1", "ORIG2"],
            tool_name="add, mul",
            tool_calls=[
                {"tool_call_id": "c1", "tool_name": "add", "content": "COMP1"},
                {"tool_call_id": "c2", "tool_name": "mul", "content": "COMP2"},
            ],
        )
        # DB round-trip
        restored = Message.from_dict(combined.to_dict())

        # Normalize with compression
        normalized = normalize_tool_result_messages([restored], compress_tool_results=True)
        assert normalized[0].content == "ORIG1"
        assert normalized[0].compressed_content == "COMP1"
        assert normalized[1].content == "ORIG2"
        assert normalized[1].compressed_content == "COMP2"

        # OpenAI Chat formats the combined message directly (without normalization)
        model = OpenAIChat(id="gpt-4o-mini")
        # With compression
        fmt_compressed = model._format_messages([restored], compress_tool_results=True)
        assert fmt_compressed[0]["content"] == "COMP1"
        assert fmt_compressed[1]["content"] == "COMP2"
        # Without compression
        fmt_original = model._format_messages([restored], compress_tool_results=False)
        assert fmt_original[0]["content"] == "ORIG1"
        assert fmt_original[1]["content"] == "ORIG2"


@requires_anthropic
class TestReasoningContentCrossProvider:
    def test_claude_reasoning_preserved_for_claude(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="Think about this"),
            Message(
                role="assistant",
                content="The answer is 42",
                reasoning_content="Let me think step by step...",
                provider_data={"signature": "sig_abc123"},
            ),
        ]
        chat_msgs, _ = format_messages(msgs)
        assistant_content = chat_msgs[1]["content"]
        # Should have ThinkingBlock + TextBlock
        assert len(assistant_content) == 2
        assert assistant_content[0].type == "thinking"
        assert assistant_content[0].thinking == "Let me think step by step..."
        assert assistant_content[1].type == "text"

    def test_foreign_reasoning_no_signature_skipped_for_claude(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            Message(
                role="assistant",
                content="The answer",
                reasoning_content="OpenAI reasoning trace",
            ),
        ]
        chat_msgs, _ = format_messages(msgs)
        assistant_content = chat_msgs[1]["content"]
        # No provider_data with signature → no ThinkingBlock
        assert len(assistant_content) == 1
        assert assistant_content[0].type == "text"


class TestReasoningOpenAI:
    def test_reasoning_does_not_break_openai(self):
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        msgs = [
            Message(role="user", content="hello"),
            Message(
                role="assistant",
                content="The answer",
                reasoning_content="Claude reasoning trace",
                provider_data={"signature": "sig_abc"},
            ),
        ]
        formatted = model._format_messages(msgs)
        assistant = next(m for m in formatted if m.get("role") == "assistant")
        assert assistant["content"] == "The answer"


@requires_anthropic
class TestCompressionCrossProvider:
    def test_compressed_content_used_by_claude(self):
        from agno.utils.models.claude import format_messages

        msg = Message(
            role="tool",
            content="Very long original result...",
            compressed_content="Short summary",
            tool_call_id="c1",
            tool_name="func",
        )
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["func"]),
            msg,
        ]
        chat_msgs, _ = format_messages(msgs, compress_tool_results=True)
        tool_result = chat_msgs[2]["content"][0]
        assert tool_result["content"] == "Short summary"

    def test_original_content_when_compression_disabled(self):
        from agno.utils.models.claude import format_messages

        msg = Message(
            role="tool",
            content="Very long original result...",
            compressed_content="Short summary",
            tool_call_id="c1",
            tool_name="func",
        )
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["func"]),
            msg,
        ]
        chat_msgs, _ = format_messages(msgs, compress_tool_results=False)
        tool_result = chat_msgs[2]["content"][0]
        assert tool_result["content"] == "Very long original result..."


@requires_mistral
class TestMistralEmptyToolCalls:
    def test_empty_tool_calls_not_passed_through(self):
        from agno.utils.models.mistral import format_messages

        msg = Message(role="assistant", content="response", tool_calls=[])
        result = format_messages([msg])
        # Mistral SDK uses Unset() sentinel instead of None for unset fields.
        # We just need to verify it's not a non-empty list.
        tc = result[0].tool_calls
        assert tc is None or (not isinstance(tc, list)) or len(tc) == 0

    def test_non_empty_tool_calls_preserved(self):
        from agno.utils.models.mistral import format_messages

        msg = Message(
            role="assistant",
            content="response",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "fn", "arguments": "{}"}}],
        )
        result = format_messages([msg])
        assert result[0].tool_calls is not None
        assert len(result[0].tool_calls) > 0


@requires_boto3
class TestBedrockNoneContent:
    def test_none_content_becomes_empty_string(self):
        from unittest.mock import patch

        with patch("agno.models.aws.bedrock.AwsClient"), patch("agno.models.aws.bedrock.Session"):
            from agno.models.aws.bedrock import AwsBedrock

            model = AwsBedrock(id="anthropic.claude-sonnet-4-20250514-v1:0")

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content=None, tool_call_id="c1", tool_name="fn"),
        ]
        formatted, _ = model._format_messages(msgs)
        tool_msgs = [m for m in formatted if "toolResult" in str(m.get("content", []))]
        tool_result = tool_msgs[0]["content"][0]["toolResult"]
        assert tool_result["content"][0]["json"]["result"] is not None
        assert tool_result["content"][0]["json"]["result"] == ""


@requires_boto3
class TestBedrockNoneToolCallId:
    def test_none_tool_call_id_passes_through(self):
        from unittest.mock import patch

        with patch("agno.models.aws.bedrock.AwsClient"), patch("agno.models.aws.bedrock.Session"):
            from agno.models.aws.bedrock import AwsBedrock

            model = AwsBedrock(id="anthropic.claude-sonnet-4-20250514-v1:0")

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content="result", tool_call_id=None, tool_name="fn"),
        ]
        formatted, _ = model._format_messages(msgs)
        tool_msgs = [m for m in formatted if "toolResult" in str(m.get("content", []))]
        tool_result = tool_msgs[0]["content"][0]["toolResult"]
        assert tool_result["toolUseId"] is None


@requires_anthropic
class TestClaudeNoneToolCallId:
    def test_none_tool_use_id_passes_through(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content="result", tool_call_id=None, tool_name="fn"),
        ]
        chat_msgs, _ = format_messages(msgs)
        for msg in chat_msgs:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        assert block["tool_use_id"] is None


@requires_anthropic
class TestClaudeNoneContent:
    def test_none_content_becomes_empty_string(self):
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content=None, tool_call_id="c1", tool_name="fn"),
        ]
        chat_msgs, _ = format_messages(msgs)
        for msg in chat_msgs:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        assert block["content"] == ""


@requires_google_genai
class TestGeminiNoneToolName:
    def test_canonical_with_none_tool_name_creates_function_response(self):
        from unittest.mock import patch

        with patch("agno.models.google.gemini.GeminiClient"):
            from agno.models.google.gemini import Gemini

            model = Gemini(id="gemini-2.0-flash")

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content="result_data", tool_call_id="c1", tool_name=None),
        ]
        formatted, _ = model._format_messages(msgs)
        found_func_response = False
        for content in formatted:
            if hasattr(content, "parts"):
                for part in content.parts:
                    if hasattr(part, "function_response") and part.function_response is not None:
                        found_func_response = True
        assert found_func_response


@requires_google_genai
class TestGeminiNoneContent:
    def test_canonical_with_none_content_creates_function_response(self):
        from unittest.mock import patch

        with patch("agno.models.google.gemini.GeminiClient"):
            from agno.models.google.gemini import Gemini

            model = Gemini(id="gemini-2.0-flash")

        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content=None, tool_call_id="c1", tool_name="fn"),
        ]
        formatted, _ = model._format_messages(msgs)
        found_func_response = False
        for content in formatted:
            if hasattr(content, "parts"):
                for part in content.parts:
                    if hasattr(part, "function_response") and part.function_response is not None:
                        found_func_response = True
                        assert part.function_response.response["result"] == ""
        assert found_func_response


class TestOpenAIChatCompressedContentNotOverwritten:
    def test_compressed_content_preserved_when_content_none(self):
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        msg = Message(
            role="tool",
            content=None,
            compressed_content="Short summary",
            tool_call_id="c1",
            tool_name="fn",
        )
        fmt = model._format_message(msg, compress_tool_results=True)
        assert fmt["content"] == "Short summary"

    def test_non_compressed_none_content_still_empty_string(self):
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        msg = Message(
            role="tool",
            content=None,
            tool_call_id="c1",
            tool_name="fn",
        )
        fmt = model._format_message(msg, compress_tool_results=False)
        assert fmt["content"] == ""

    def test_non_tool_none_content_still_empty_string(self):
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        msg = Message(role="user", content=None)
        fmt = model._format_message(msg)
        assert fmt["content"] == ""


class TestOpenAIResponsesNoneContentNotDropped:
    def test_canonical_none_content_emits_output(self):
        from agno.models.openai.responses import OpenAIResponses

        model = OpenAIResponses(id="gpt-4o")
        msgs = [
            Message(role="user", content="hello"),
            _assistant_with_tool_calls(["c1"], ["fn"]),
            Message(role="tool", content=None, tool_call_id="c1", tool_name="fn"),
        ]
        fmt = model._format_messages(msgs)
        tool_outputs = [m for m in fmt if isinstance(m, dict) and m.get("type") == "function_call_output"]
        assert len(tool_outputs) == 1
        assert tool_outputs[0]["output"] == ""
