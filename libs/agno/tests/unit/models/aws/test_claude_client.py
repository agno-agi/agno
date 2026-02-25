from unittest.mock import MagicMock, patch

import pytest
from boto3.session import Session

from agno.models.aws import Claude


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
    return mock_session, mock_creds


class TestSessionClientNotCached:
    def test_sync_client_recreated_each_call(self):
        mock_session, _ = _make_mock_session()
        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with patch("agno.models.aws.claude.AnthropicBedrock") as MockBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockBedrock.return_value = mock_client

            model.get_client()
            model.get_client()

            assert MockBedrock.call_count == 2

    def test_async_client_recreated_each_call(self):
        mock_session, _ = _make_mock_session()
        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with patch("agno.models.aws.claude.AsyncAnthropicBedrock") as MockAsyncBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockAsyncBedrock.return_value = mock_client

            model.get_async_client()
            model.get_async_client()

            assert MockAsyncBedrock.call_count == 2


class TestSessionCredsReadEachTime:
    def test_fresh_creds_on_each_sync_get_client(self):
        mock_session, mock_creds = _make_mock_session(access_key="KEY_V1", token="TOKEN_V1")
        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with patch("agno.models.aws.claude.AnthropicBedrock") as MockBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockBedrock.return_value = mock_client

            model.get_client()
            first_call_kwargs = MockBedrock.call_args
            assert first_call_kwargs[1]["aws_access_key"] == "KEY_V1"
            assert first_call_kwargs[1]["aws_session_token"] == "TOKEN_V1"

            # Simulate credential rotation
            mock_creds.get_frozen_credentials.return_value = _make_frozen_creds("KEY_V2", "secret", "TOKEN_V2")

            model.get_client()
            second_call_kwargs = MockBedrock.call_args
            assert second_call_kwargs[1]["aws_access_key"] == "KEY_V2"
            assert second_call_kwargs[1]["aws_session_token"] == "TOKEN_V2"

    def test_fresh_creds_on_each_async_get_client(self):
        mock_session, mock_creds = _make_mock_session(access_key="KEY_V1", token="TOKEN_V1")
        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with patch("agno.models.aws.claude.AsyncAnthropicBedrock") as MockAsyncBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockAsyncBedrock.return_value = mock_client

            model.get_async_client()
            first_call_kwargs = MockAsyncBedrock.call_args
            assert first_call_kwargs[1]["aws_access_key"] == "KEY_V1"
            assert first_call_kwargs[1]["aws_session_token"] == "TOKEN_V1"

            # Simulate credential rotation
            mock_creds.get_frozen_credentials.return_value = _make_frozen_creds("KEY_V2", "secret", "TOKEN_V2")

            model.get_async_client()
            second_call_kwargs = MockAsyncBedrock.call_args
            assert second_call_kwargs[1]["aws_access_key"] == "KEY_V2"
            assert second_call_kwargs[1]["aws_session_token"] == "TOKEN_V2"


class TestStaticKeyClientCached:
    def test_sync_client_cached(self):
        model = Claude(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key="AKIA_STATIC",
            aws_secret_key="secret",
            aws_region="us-east-1",
        )

        with patch("agno.models.aws.claude.AnthropicBedrock") as MockBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockBedrock.return_value = mock_client

            client1 = model.get_client()
            client2 = model.get_client()

            assert MockBedrock.call_count == 1
            assert client1 is client2

    def test_async_client_cached(self):
        model = Claude(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key="AKIA_STATIC",
            aws_secret_key="secret",
            aws_region="us-east-1",
        )

        with patch("agno.models.aws.claude.AsyncAnthropicBedrock") as MockAsyncBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockAsyncBedrock.return_value = mock_client

            client1 = model.get_async_client()
            client2 = model.get_async_client()

            assert MockAsyncBedrock.call_count == 1
            assert client1 is client2


class TestAsyncIsClosedCheck:
    def test_closed_async_client_is_recreated(self):
        model = Claude(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key="AKIA_STATIC",
            aws_secret_key="secret",
            aws_region="us-east-1",
        )

        with patch("agno.models.aws.claude.AsyncAnthropicBedrock") as MockAsyncBedrock:
            closed_client = MagicMock()
            closed_client.is_closed.return_value = True
            model.async_client = closed_client

            new_client = MagicMock()
            new_client.is_closed.return_value = False
            MockAsyncBedrock.return_value = new_client

            result = model.get_async_client()

            assert result is new_client
            assert MockAsyncBedrock.call_count == 1

    def test_open_async_client_is_reused(self):
        model = Claude(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key="AKIA_STATIC",
            aws_secret_key="secret",
            aws_region="us-east-1",
        )

        open_client = MagicMock()
        open_client.is_closed.return_value = False
        model.async_client = open_client

        result = model.get_async_client()
        assert result is open_client


class TestSessionTokenEnv:
    def test_session_token_read_from_env(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIATEMP")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "my-session-token")
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        monkeypatch.delenv("AWS_BEDROCK_API_KEY", raising=False)

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0")
        params = model._get_client_params()

        assert params["aws_session_token"] == "my-session-token"
        assert params["aws_access_key"] == "ASIATEMP"
        assert params["aws_region"] == "us-west-2"

    def test_session_token_explicit_param(self, monkeypatch):
        monkeypatch.delenv("AWS_BEDROCK_API_KEY", raising=False)

        model = Claude(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            aws_access_key="ASIATEMP",
            aws_secret_key="secret",
            aws_session_token="explicit-token",
            aws_region="us-east-1",
        )
        params = model._get_client_params()

        assert params["aws_session_token"] == "explicit-token"

    def test_no_session_token_when_not_set(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_STATIC")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
        monkeypatch.delenv("AWS_BEDROCK_API_KEY", raising=False)

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0")
        params = model._get_client_params()

        assert params["aws_session_token"] is None


class TestApiKeyPath:
    def test_api_key_client_cached(self, monkeypatch):
        monkeypatch.setenv("AWS_BEDROCK_API_KEY", "br-api-key-123")
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0")

        with patch("agno.models.aws.claude.AnthropicBedrock") as MockBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockBedrock.return_value = mock_client

            client1 = model.get_client()
            client2 = model.get_client()

            assert MockBedrock.call_count == 1
            assert client1 is client2

    def test_api_key_params(self, monkeypatch):
        monkeypatch.setenv("AWS_BEDROCK_API_KEY", "br-api-key-123")
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0")
        params = model._get_client_params()

        assert params["api_key"] == "br-api-key-123"
        assert params["aws_region"] == "us-west-2"
        assert "aws_session_token" not in params


class TestSessionNullCredentials:
    def test_raises_on_null_credentials(self):
        mock_session = MagicMock(spec=Session)
        mock_session.region_name = "us-east-1"
        mock_session.profile_name = None
        mock_session.get_credentials.return_value = None

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with pytest.raises(ValueError, match="boto3 session has no credentials"):
            model._get_client_params()
