"""
Tests for append_trailing_user_message across Anthropic, Bedrock, and LiteLLM.

Verifies that:
- The trailing user message is appended when the flag is True and the
  conversation ends with an assistant turn.
- The trailing user message is NOT appended when the flag is False.
- The trailing user message is NOT appended when the conversation already
  ends with a user turn.
- Custom trailing_user_message_content is used when provided.
- The feature works for all three providers that support it.
- Auto-detection sets the flag for Claude 4.6+ models.
"""

import importlib

import pytest

from agno.models.message import Message

_has_boto3 = importlib.util.find_spec("boto3") is not None
_skip_boto3 = pytest.mark.skipif(not _has_boto3, reason="boto3 not installed")
_has_litellm = importlib.util.find_spec("litellm") is not None
_skip_litellm = pytest.mark.skipif(not _has_litellm, reason="litellm not installed")

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

    def _format(self, messages, append=False, content="continue"):
        from agno.utils.models.claude import format_messages

        formatted, _ = format_messages(
            messages,
            append_trailing_user_message=append,
            trailing_user_message_content=content,
        )
        return formatted

    def test_appends_when_ends_with_assistant(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=True)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"type": "text", "text": "continue"}]

    def test_no_append_when_flag_false(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=False)
        assert msgs[-1]["role"] == "assistant"

    def test_no_append_when_ends_with_user(self):
        msgs = self._format(ENDS_WITH_USER, append=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_custom_trailing_content(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=True, content="go on")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"type": "text", "text": "go on"}]

    def test_multi_assistant_appends_once(self):
        msgs = self._format(MULTI_ASSISTANT, append=True)
        assert msgs[-1]["role"] == "user"
        user_count = sum(1 for m in msgs if m["role"] == "user")
        # original 2 user messages + 1 appended
        assert user_count == 3

    def test_system_messages_excluded_from_check(self):
        msgs = self._format(SYSTEM_THEN_ASSISTANT, append=True)
        assert msgs[-1]["role"] == "user"

    def test_no_append_when_only_user(self):
        msgs = self._format(ONLY_SYSTEM_AND_USER, append=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_empty_messages(self):
        msgs = self._format([], append=True)
        assert len(msgs) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Bedrock (AwsBedrock._format_messages)
# ═══════════════════════════════════════════════════════════════════════════


@_skip_boto3
class TestBedrockFormatMessages:
    """Tests for AwsBedrock._format_messages trailing message."""

    def _format(self, messages, append=False, content="continue"):
        from agno.models.aws.bedrock import AwsBedrock

        model = AwsBedrock(
            id="us.anthropic.claude-sonnet-4-6",
            aws_region="us-east-1",
            append_trailing_user_message=append,
            trailing_user_message_content=content,
        )
        formatted, _ = model._format_messages(messages)
        return formatted

    def test_appends_when_ends_with_assistant(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=True)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"text": "continue"}]

    def test_no_append_when_flag_false(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=False)
        assert msgs[-1]["role"] == "assistant"

    def test_no_append_when_ends_with_user(self):
        msgs = self._format(ENDS_WITH_USER, append=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_custom_trailing_content(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=True, content="go on")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == [{"text": "go on"}]


# ═══════════════════════════════════════════════════════════════════════════
# LiteLLM (LiteLLM._format_messages)
# ═══════════════════════════════════════════════════════════════════════════


@_skip_litellm
class TestLiteLLMFormatMessages:
    """Tests for LiteLLM._format_messages trailing message."""

    def _format(self, messages, append=False, content="continue"):
        from agno.models.litellm.chat import LiteLLM

        model = LiteLLM(
            id="anthropic/claude-sonnet-4-6",
            append_trailing_user_message=append,
            trailing_user_message_content=content,
        )
        return model._format_messages(messages)

    def test_appends_when_ends_with_assistant(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=True)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "continue"

    def test_no_append_when_flag_false(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=False)
        assert msgs[-1]["role"] == "assistant"

    def test_no_append_when_ends_with_user(self):
        msgs = self._format(ENDS_WITH_USER, append=True)
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == 1

    def test_custom_trailing_content(self):
        msgs = self._format(ENDS_WITH_ASSISTANT, append=True, content="go on")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "go on"


# ═══════════════════════════════════════════════════════════════════════════
# Auto-detection (Claude.__post_init__)
# ═══════════════════════════════════════════════════════════════════════════


class TestSupportsPrefillHelper:
    """Tests for the shared supports_prefill() helper."""

    def test_anthropic_direct_prefill_supported(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("claude-sonnet-4-5-20250929") is True
        assert supports_prefill("claude-sonnet-4-0") is True
        assert supports_prefill("claude-opus-4-0") is True
        assert supports_prefill("claude-3-5-sonnet-20241022") is True

    def test_anthropic_direct_prefill_not_supported(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("claude-sonnet-4-6") is False
        assert supports_prefill("claude-opus-4-6") is False
        assert supports_prefill("claude-sonnet-5-0") is False

    def test_aliases_supported(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("claude-sonnet-4") is True
        assert supports_prefill("claude-opus-4") is True
        assert supports_prefill("claude-haiku-4") is True

    def test_bedrock_ids(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("us.anthropic.claude-sonnet-4-5-20250929-v1:0") is True
        assert supports_prefill("us.anthropic.claude-sonnet-4-6") is False
        assert supports_prefill("global.anthropic.claude-sonnet-4-6-v1:0") is False

    def test_vertex_ids(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("claude-sonnet-4@20250514") is True
        assert supports_prefill("claude-sonnet-4-6@20260401") is False

    def test_litellm_ids(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("anthropic/claude-sonnet-4-5") is True
        assert supports_prefill("anthropic/claude-sonnet-4-6") is False

    def test_non_claude_models(self):
        from agno.utils.models.claude import supports_prefill

        assert supports_prefill("gpt-4o") is True
        assert supports_prefill("gemini-2.0-flash") is True


class TestAutoDetection:
    """Tests for automatic append_trailing_user_message detection."""

    def test_sonnet_46_auto_enabled(self):
        from agno.models.anthropic import Claude

        assert Claude(id="claude-sonnet-4-6").append_trailing_user_message is True

    def test_opus_46_auto_enabled(self):
        from agno.models.anthropic import Claude

        assert Claude(id="claude-opus-4-6").append_trailing_user_message is True

    def test_sonnet_45_auto_disabled(self):
        from agno.models.anthropic import Claude

        assert Claude(id="claude-sonnet-4-5-20250929").append_trailing_user_message is False

    def test_sonnet_4_alias_auto_disabled(self):
        from agno.models.anthropic import Claude

        assert Claude(id="claude-sonnet-4").append_trailing_user_message is False

    def test_user_override_respected(self):
        from agno.models.anthropic import Claude

        assert Claude(id="claude-sonnet-4-6", append_trailing_user_message=False).append_trailing_user_message is False

    def test_future_model_auto_enabled(self):
        from agno.models.anthropic import Claude

        assert Claude(id="claude-sonnet-5-0").append_trailing_user_message is True


class TestAutoDetectionVertexAI:
    """Tests for VertexAI Claude auto-detection."""

    def test_vertex_sonnet_45_auto_disabled(self):
        from agno.models.vertexai.claude import Claude

        assert Claude(id="claude-sonnet-4-5@20250929").append_trailing_user_message is False

    def test_vertex_sonnet_46_auto_enabled(self):
        from agno.models.vertexai.claude import Claude

        assert Claude(id="claude-sonnet-4-6@20260401").append_trailing_user_message is True

    def test_vertex_alias_auto_disabled(self):
        from agno.models.vertexai.claude import Claude

        assert Claude(id="claude-sonnet-4@20250514").append_trailing_user_message is False


class TestAutoDetectionAwsClaude:
    """Tests for AWS Bedrock Claude (anthropic SDK) auto-detection."""

    def test_aws_sonnet_45_auto_disabled(self):
        from agno.models.aws.claude import Claude

        assert Claude(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0").append_trailing_user_message is False

    def test_aws_sonnet_46_auto_enabled(self):
        from agno.models.aws.claude import Claude

        assert Claude(id="us.anthropic.claude-sonnet-4-6").append_trailing_user_message is True

    def test_aws_global_prefix_auto_enabled(self):
        from agno.models.aws.claude import Claude

        assert Claude(id="global.anthropic.claude-sonnet-4-6-v1:0").append_trailing_user_message is True


@_skip_litellm
class TestAutoDetectionLiteLLM:
    """Tests for LiteLLM auto-detection."""

    def test_litellm_sonnet_45_auto_disabled(self):
        from agno.models.litellm.chat import LiteLLM

        assert LiteLLM(id="anthropic/claude-sonnet-4-5").append_trailing_user_message is False

    def test_litellm_sonnet_46_auto_enabled(self):
        from agno.models.litellm.chat import LiteLLM

        assert LiteLLM(id="anthropic/claude-sonnet-4-6").append_trailing_user_message is True

    def test_litellm_non_claude_auto_disabled(self):
        from agno.models.litellm.chat import LiteLLM

        assert LiteLLM(id="openai/gpt-4o").append_trailing_user_message is False
