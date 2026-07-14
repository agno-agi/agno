from unittest.mock import MagicMock, patch

import pytest
from boto3.session import Session

from agno.models.aws import AwsBedrock


def _make_frozen_creds(access_key="ASIATEMP", secret_key="secret", token="token"):
    frozen = MagicMock()
    frozen.access_key = access_key
    frozen.secret_key = secret_key
    frozen.token = token
    return frozen


def _make_mock_session(access_key="ASIATEMP", secret_key="secret", token="token", region="us-east-1"):
    mock_session = MagicMock(spec=Session)
    mock_session.region_name = region
    mock_session.profile_name = None
    mock_creds = MagicMock()
    mock_creds.get_frozen_credentials.return_value = _make_frozen_creds(access_key, secret_key, token)
    mock_session.get_credentials.return_value = mock_creds
    mock_client = MagicMock()
    mock_session.client.return_value = mock_client
    return mock_session, mock_creds, mock_client


class TestSessionClientNotCached:
    def test_sync_client_recreated_each_call(self):
        mock_session, _, _ = _make_mock_session()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        model.get_client()
        model.get_client()

        assert mock_session.client.call_count == 2

    def test_sync_client_passes_region(self):
        mock_session, _, _ = _make_mock_session(region="eu-west-1")
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        model.get_client()

        mock_session.client.assert_called_with("bedrock-runtime", region_name="eu-west-1")


class TestStaticKeyClientCached:
    def test_sync_client_cached(self):
        model = AwsBedrock(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key_id="AKIA_STATIC",
            aws_secret_access_key="secret",
            aws_region="us-east-1",
        )

        with patch("agno.models.aws.bedrock.AwsClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            client1 = model.get_client()
            client2 = model.get_client()

            assert MockClient.call_count == 1
            assert client1 is client2


class TestSessionTokenEnv:
    def test_session_token_read_from_env(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIATEMP")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "my-session-token")
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

        with patch("agno.models.aws.bedrock.AwsClient") as MockClient:
            MockClient.return_value = MagicMock()
            model.get_client()

            call_kwargs = MockClient.call_args[1]
            assert call_kwargs["aws_session_token"] == "my-session-token"
            assert call_kwargs["aws_access_key_id"] == "ASIATEMP"

    def test_session_token_explicit_param(self):
        model = AwsBedrock(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key_id="ASIATEMP",
            aws_secret_access_key="secret",
            aws_session_token="explicit-token",
            aws_region="us-east-1",
        )

        with patch("agno.models.aws.bedrock.AwsClient") as MockClient:
            MockClient.return_value = MagicMock()
            model.get_client()

            call_kwargs = MockClient.call_args[1]
            assert call_kwargs["aws_session_token"] == "explicit-token"

    def test_no_session_token_when_not_set(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_STATIC")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

        with patch("agno.models.aws.bedrock.AwsClient") as MockClient:
            MockClient.return_value = MagicMock()
            model.get_client()

            call_kwargs = MockClient.call_args[1]
            assert call_kwargs["aws_session_token"] is None


class TestSessionNullCredentials:
    def test_async_raises_on_null_credentials(self):
        try:
            import aioboto3  # noqa: F401
        except ImportError:
            pytest.skip("aioboto3 not installed")

        mock_session = MagicMock(spec=Session)
        mock_session.region_name = "us-east-1"
        mock_session.get_credentials.return_value = None

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with pytest.raises(ValueError, match="boto3 session has no credentials"):
            model.get_async_client()
