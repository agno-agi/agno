from unittest.mock import MagicMock, patch

import pytest
from boto3.session import Session

from agno.models.aws import AwsBedrock
from agno.models.message import Message


class FakeAsyncClient:
    """Async Bedrock client without the async context manager protocol."""

    def __init__(self):
        self.converse_calls = 0

    async def converse(self, **kwargs):
        self.converse_calls += 1
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "hello"}]}},
            "stopReason": "end_turn",
        }


class FakeContextManagedAsyncClient(FakeAsyncClient):
    """Async Bedrock client that is also an async context manager, as aiobotocore clients are."""

    def __init__(self):
        super().__init__()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.closed = True


class FakeStreamingAsyncClient(FakeAsyncClient):
    """Async Bedrock client that also serves the streaming and token-count request paths."""

    def __init__(self):
        super().__init__()
        self.converse_stream_calls = 0
        self.count_tokens_calls = 0

    async def converse_stream(self, **kwargs):
        self.converse_stream_calls += 1

        async def chunks():
            yield {"contentBlockDelta": {"delta": {"text": "hel"}}}
            yield {"contentBlockDelta": {"delta": {"text": "lo"}}}

        return {"stream": chunks()}

    async def count_tokens(self, **kwargs):
        self.count_tokens_calls += 1
        return {"inputTokens": 42}


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


class TestProvidedAsyncClient:
    @pytest.mark.asyncio
    async def test_async_client_does_not_require_aioboto3(self):
        provided = FakeAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        with patch("agno.models.aws.bedrock.AIOBOTO3_AVAILABLE", False):
            async with model._async_client() as client:
                assert client is provided

    @pytest.mark.asyncio
    async def test_async_client_takes_precedence_over_session(self):
        mock_session, mock_creds, _ = _make_mock_session()
        provided = FakeAsyncClient()
        model = AwsBedrock(
            id="anthropic.claude-3-sonnet-20240229-v1:0",
            session=mock_session,
            async_client=provided,
        )

        async with model._async_client() as client:
            assert client is provided

        mock_session.get_credentials.assert_not_called()
        mock_creds.get_frozen_credentials.assert_not_called()

    def test_get_async_client_ignores_provided_client(self):
        """`get_async_client` is a factory: it builds a model-owned client regardless of injection."""
        provided = FakeAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        with patch("agno.models.aws.bedrock.AIOBOTO3_AVAILABLE", False):
            with pytest.raises(ImportError, match="aioboto3"):
                model.get_async_client()

    def test_async_client_not_created_when_none_provided(self):
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

        with patch("agno.models.aws.bedrock.AIOBOTO3_AVAILABLE", False):
            with pytest.raises(ImportError, match="aioboto3"):
                model.get_async_client()


class TestProvidedAsyncClientLifecycle:
    @pytest.mark.asyncio
    async def test_plain_client_used_without_entering_context(self):
        """A provided client that is not an async context manager is usable as-is."""
        provided = FakeAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        async with model._async_client() as client:
            assert client is provided

    @pytest.mark.asyncio
    async def test_ainvoke_with_plain_client(self):
        provided = FakeAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        response = await model.ainvoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
        )

        assert response.content == "hello"
        assert provided.converse_calls == 1

    @pytest.mark.asyncio
    async def test_provided_client_not_closed_and_reusable(self):
        """A caller-owned client stays open across requests."""
        provided = FakeContextManagedAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        for _ in range(2):
            await model.ainvoke(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
            )

        assert provided.closed is False
        assert provided.converse_calls == 2

    def test_client_context_manager_rejected(self):
        """An unentered client context manager is single use, so it is rejected with guidance."""
        provided = MagicMock(spec=["__aenter__", "__aexit__"])

        with pytest.raises(ValueError, match="must be an initialized async Bedrock client.*Enter it first"):
            AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

    @pytest.mark.asyncio
    async def test_owned_client_is_entered_and_closed(self):
        """Clients created by the model are still entered and closed per request."""
        owned = FakeContextManagedAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

        with patch.object(model, "get_async_client", return_value=owned):
            async with model._async_client() as client:
                assert client is owned
                assert owned.closed is False

        assert owned.closed is True


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


class TestAsyncClientGuard:
    """Anything that cannot serve `await client.converse(...)` is rejected when the model is built."""

    def test_sync_boto3_client_rejected_at_construction(self):
        sync_client = Session().client(
            "bedrock-runtime", region_name="us-east-1", aws_access_key_id="k", aws_secret_access_key="s"
        )

        with pytest.raises(ValueError, match="must be an initialized async Bedrock client.*BedrockRuntime"):
            AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=sync_client)

    def test_session_object_rejected_at_construction(self):
        with pytest.raises(ValueError, match="must be an initialized async Bedrock client.*Session"):
            AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=Session())

    @pytest.mark.asyncio
    async def test_client_assigned_after_construction_is_validated(self):
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        model.async_client = Session()

        with pytest.raises(ValueError, match="must be an initialized async Bedrock client"):
            async with model._async_client():
                pass

    @pytest.mark.asyncio
    async def test_entered_aiobotocore_client_accepted(self):
        try:
            import aioboto3
        except ImportError:
            pytest.skip("aioboto3 not installed")
        from contextlib import AsyncExitStack

        async with AsyncExitStack() as stack:
            entered = await stack.enter_async_context(
                aioboto3.Session().client("bedrock-runtime", region_name="us-east-1")
            )
            model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=entered)

            async with model._async_client() as client:
                assert client is entered


class TestProvidedAsyncClientOtherPaths:
    @pytest.mark.asyncio
    async def test_ainvoke_stream_with_provided_client(self):
        provided = FakeStreamingAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        deltas = [
            delta
            async for delta in model.ainvoke_stream(
                messages=[Message(role="user", content="hi")], assistant_message=Message(role="assistant")
            )
        ]

        assert "".join(delta.content for delta in deltas if delta.content) == "hello"
        assert provided.converse_stream_calls == 1

    @pytest.mark.asyncio
    async def test_acount_tokens_with_provided_client(self):
        provided = FakeStreamingAsyncClient()
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", async_client=provided)

        tokens = await model.acount_tokens(messages=[Message(role="user", content="hi")])

        assert tokens == 42
        assert provided.count_tokens_calls == 1
