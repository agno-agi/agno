"""
Tests for inject_trailing_user_message across Anthropic, Bedrock, and LiteLLM.

Verifies that:
- The trailing user message is injected when the flag is True and the
  conversation ends with an assistant turn.
- The trailing user message is NOT injected when the flag is False.
- The trailing user message is NOT injected when the conversation already
  ends with a user turn.
- Custom trailing_user_message_content is used when provided.
- The feature works for all three providers that support it.
"""

from agno.models.message import Message

# ---------------------------------------------------------------------------
# Shared test messages
# ---------------------------------------------------------------------------

ENDS_WITH_ASSISTANT = [
    Message(role="user", content="Classify this ticket: checkout is broken"),
    Message(role="assistant", content='{"priority":'),
]

ENDS_WITH_USER = [
    Message(role="user", content="What is 2+2?"),
]

MULTI_ASSISTANT = [
    Message(role="user", content="Hello"),
    Message(role="assistant", content="Hi there!"),
    Message(role="user", content="Tell me a joke"),
    Message(role="assistant", content="Why did the chicken"),
]

SYSTEM_THEN_ASSISTANT = [
    Message(role="system", content="You are helpful."),
    Message(role="user", content="Hello"),
    Message(role="assistant", content="Hi!"),
]

ONLY_SYSTEM_AND_USER = [
    Message(role="system", content="You are helpful."),
    Message(role="user", content="Hello"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Anthropic (format_messages in utils/models/claude.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicFormatMessages:
    """Tests for the shared Anthropic format_messages utility."""

    def _format(self, messages, inject=False, content="."):
        from agno.utils.models.claude import format_messages

        formatted, _ = format_messages(
            messages,
            inject_trailing_user_message=inject,
            trailing_user_message_content=content,
        )
        return formatted

    def test_injects_when_ends_with_assistant(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=True)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"type": "text", "text": "."}]

    def test_no_inject_when_flag_false(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=False)
        assert msgs[-1]["role"] == "assistant"

    def test_no_inject_when_ends_with_user(self):
        msgs = self._format(ENDS_WITH_USER, inject=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_custom_trailing_content(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=True, content="continue")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"type": "text", "text": "continue"}]

    def test_multi_assistant_injects_once(self):
        msgs = self._format(MULTI_ASSISTANT, inject=True)
        assert msgs[-1]["role"] == "user"
        user_count = sum(1 for m in msgs if m["role"] == "user")
        # original 2 user messages + 1 injected
        assert user_count == 3

    def test_system_messages_excluded_from_check(self):
        msgs = self._format(SYSTEM_THEN_ASSISTANT, inject=True)
        assert msgs[-1]["role"] == "user"

    def test_no_inject_when_only_user(self):
        msgs = self._format(ONLY_SYSTEM_AND_USER, inject=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_empty_messages(self):
        msgs = self._format([], inject=True)
        assert len(msgs) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Bedrock (AwsBedrock._format_messages)
# ═══════════════════════════════════════════════════════════════════════════


class TestBedrockFormatMessages:
    """Tests for AwsBedrock._format_messages injection."""

    def _format(self, messages, inject=False, content="."):
        from agno.models.aws.bedrock import AwsBedrock

        model = AwsBedrock(
            id="us.anthropic.claude-sonnet-4-6",
            aws_region="us-east-1",
            inject_trailing_user_message=inject,
            trailing_user_message_content=content,
        )
        formatted, _ = model._format_messages(
            messages,
            inject_trailing_user_message=model.inject_trailing_user_message,
            trailing_user_message_content=model.trailing_user_message_content,
        )
        return formatted

    def test_injects_when_ends_with_assistant(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=True)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"text": "."}]

    def test_no_inject_when_flag_false(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=False)
        assert msgs[-1]["role"] == "assistant"

    def test_no_inject_when_ends_with_user(self):
        msgs = self._format(ENDS_WITH_USER, inject=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_custom_trailing_content(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=True, content="continue")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"text": "continue"}]


# ═══════════════════════════════════════════════════════════════════════════
# LiteLLM (LiteLLM._format_messages)
# ═══════════════════════════════════════════════════════════════════════════


class TestLiteLLMFormatMessages:
    """Tests for LiteLLM._format_messages injection."""

    def _format(self, messages, inject=False, content="."):
        from agno.models.litellm.chat import LiteLLM

        model = LiteLLM(
            id="anthropic/claude-sonnet-4-6",
            inject_trailing_user_message=inject,
            trailing_user_message_content=content,
        )
        return model._format_messages(
            messages,
            inject_trailing_user_message=model.inject_trailing_user_message,
            trailing_user_message_content=model.trailing_user_message_content,
        )

    def test_injects_when_ends_with_assistant(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=True)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "."

    def test_no_inject_when_flag_false(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=False)
        assert msgs[-1]["role"] == "assistant"

    def test_no_inject_when_ends_with_user(self):
        msgs = self._format(ENDS_WITH_USER, inject=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_custom_trailing_content(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, inject=True, content="continue")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "continue"
