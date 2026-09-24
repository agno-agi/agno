"""Unit tests for BedrockGuardrail."""

from unittest.mock import MagicMock, patch

import pytest

from agno.exceptions import InputCheckError, OutputCheckError
from agno.guardrails.bedrock import BedrockGuardrail


@pytest.fixture
def mock_boto3():
    return MagicMock()


@pytest.fixture
def mock_run_input():
    run_input = MagicMock()
    run_input.input_content_string.return_value = "Hello, how are you?"
    return run_input


# ---------------------------------------------------------------------------
# Init Tests
# ---------------------------------------------------------------------------


class TestBedrockGuardrailInit:
    def test_init_defaults(self):
        guard = BedrockGuardrail(guardrail_id="abc123")
        assert guard.guardrail_id == "abc123"
        assert guard.guardrail_version == "DRAFT"
        assert guard.source == "INPUT"
        assert guard.timeout == 10

    def test_init_custom(self):
        guard = BedrockGuardrail(
            guardrail_id="abc123",
            guardrail_version="1",
            source="OUTPUT",
            region="eu-west-1",
            timeout=30,
        )
        assert guard.guardrail_version == "1"
        assert guard.source == "OUTPUT"
        assert guard.region == "eu-west-1"
        assert guard.timeout == 30

    def test_init_with_credentials(self):
        guard = BedrockGuardrail(
            guardrail_id="abc123",
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret",
            aws_session_token="token",
        )
        assert guard.aws_access_key_id == "AKIA..."
        assert guard.aws_secret_access_key == "secret"
        assert guard.aws_session_token == "token"

    def test_region_from_env(self):
        with patch.dict("os.environ", {"AWS_DEFAULT_REGION": "ap-southeast-1"}):
            guard = BedrockGuardrail(guardrail_id="abc123")
            assert guard.region == "ap-southeast-1"


# ---------------------------------------------------------------------------
# Allow Tests
# ---------------------------------------------------------------------------


class TestAllowedContent:
    def test_allowed_input(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "NONE",
            "outputs": [],
            "assessments": [],
        }

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        # Should not raise
        guard.check(mock_run_input)

        mock_boto3.apply_guardrail.assert_called_once_with(
            guardrailIdentifier="abc123",
            guardrailVersion="DRAFT",
            source="INPUT",
            content=[{"text": {"text": "Hello, how are you?"}}],
        )

    def test_empty_content_skipped(self, mock_boto3):
        run_input = MagicMock()
        run_input.input_content_string.return_value = ""

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        guard.check(run_input)
        mock_boto3.apply_guardrail.assert_not_called()


# ---------------------------------------------------------------------------
# Block Tests
# ---------------------------------------------------------------------------


class TestBlockedContent:
    def test_blocked_input_raises_input_error(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "I cannot help with that request."}],
            "assessments": [
                {
                    "contentPolicy": {
                        "filters": [
                            {"type": "VIOLENCE", "confidence": "HIGH", "action": "BLOCKED"},
                        ]
                    }
                }
            ],
        }

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        with pytest.raises(InputCheckError) as exc_info:
            guard.check(mock_run_input)

        assert "I cannot help with that request." in str(exc_info.value)
        assert exc_info.value.additional_data["guardrail_id"] == "abc123"
        assert exc_info.value.additional_data["source"] == "INPUT"
        assert len(exc_info.value.additional_data["violations"]) == 1

    def test_blocked_output_raises_output_error(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "Content filtered."}],
            "assessments": [],
        }

        guard = BedrockGuardrail(guardrail_id="abc123", source="OUTPUT")
        guard._client = mock_boto3

        with pytest.raises(OutputCheckError) as exc_info:
            guard.check(mock_run_input)

        assert "Content filtered." in str(exc_info.value)
        assert exc_info.value.additional_data["source"] == "OUTPUT"

    def test_blocked_with_topic_violation(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "Denied topic detected."}],
            "assessments": [
                {
                    "topicPolicy": {
                        "topics": [
                            {"name": "Weapons", "type": "DENY", "action": "BLOCKED"},
                        ]
                    }
                }
            ],
        }

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        with pytest.raises(InputCheckError) as exc_info:
            guard.check(mock_run_input)

        violations = exc_info.value.additional_data["violations"]
        assert len(violations) == 1
        assert violations[0]["name"] == "Weapons"

    def test_blocked_with_no_output_text(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [],
            "assessments": [],
        }

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        with pytest.raises(InputCheckError, match="Content blocked by AWS Bedrock guardrail"):
            guard.check(mock_run_input)


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_api_error_does_not_block_by_default(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.side_effect = Exception("Service unavailable")

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        # Should not raise — fail-open by default
        guard.check(mock_run_input)

    def test_api_error_blocks_when_fail_closed(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.side_effect = Exception("Service unavailable")

        guard = BedrockGuardrail(guardrail_id="abc123", fail_closed=True)
        guard._client = mock_boto3

        with pytest.raises(InputCheckError, match="fail_closed"):
            guard.check(mock_run_input)

    def test_fail_closed_includes_error_details(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.side_effect = Exception("Timeout")

        guard = BedrockGuardrail(guardrail_id="abc123", fail_closed=True)
        guard._client = mock_boto3

        with pytest.raises(InputCheckError) as exc_info:
            guard.check(mock_run_input)

        assert exc_info.value.additional_data["guardrail_id"] == "abc123"
        assert "Timeout" in exc_info.value.additional_data["error"]


# ---------------------------------------------------------------------------
# Async Tests
# ---------------------------------------------------------------------------


class TestAsync:
    @pytest.mark.asyncio
    async def test_async_check_calls_sync(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "NONE",
            "outputs": [],
            "assessments": [],
        }

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        # Should not raise
        await guard.async_check(mock_run_input)
        mock_boto3.apply_guardrail.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_blocked_raises(self, mock_boto3, mock_run_input):
        mock_boto3.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "Blocked."}],
            "assessments": [],
        }

        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        with pytest.raises(InputCheckError):
            await guard.async_check(mock_run_input)


# ---------------------------------------------------------------------------
# Client Creation Tests
# ---------------------------------------------------------------------------


class TestClientCreation:
    def test_client_reused(self, mock_boto3):
        guard = BedrockGuardrail(guardrail_id="abc123")
        guard._client = mock_boto3

        client1 = guard._get_client()
        client2 = guard._get_client()
        assert client1 is client2

    def test_client_with_explicit_credentials(self):
        with patch("boto3.client") as mock_boto3_client:
            guard = BedrockGuardrail(
                guardrail_id="abc123",
                aws_access_key_id="AKIA_TEST",
                aws_secret_access_key="SECRET_TEST",
                aws_session_token="TOKEN_TEST",
                region="us-west-2",
            )
            guard._get_client()

            call_kwargs = mock_boto3_client.call_args[1]
            assert call_kwargs["aws_access_key_id"] == "AKIA_TEST"
            assert call_kwargs["aws_secret_access_key"] == "SECRET_TEST"
            assert call_kwargs["aws_session_token"] == "TOKEN_TEST"
            assert call_kwargs["region_name"] == "us-west-2"
