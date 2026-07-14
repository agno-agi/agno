import threading
from unittest.mock import MagicMock, patch

from boto3.session import Session

from agno.models.aws import Claude


def _make_frozen_creds(access_key="ASIATEMP", secret_key="secret", token="token"):
    frozen = MagicMock()
    frozen.access_key = access_key
    frozen.secret_key = secret_key
    frozen.token = token
    return frozen


class TestSessionNoSharedState:
    """Session-mode get_client() must not mutate self.client."""

    def test_session_get_client_does_not_mutate_self_client(self):
        mock_session = MagicMock(spec=Session)
        mock_session.region_name = "us-east-1"
        mock_session.profile_name = None
        mock_creds = MagicMock()
        mock_creds.get_frozen_credentials.return_value = _make_frozen_creds()
        mock_session.get_credentials.return_value = mock_creds

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        assert model.client is None

        with patch("agno.models.aws.claude.AnthropicBedrock") as MockBedrock:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockBedrock.return_value = mock_client

            returned = model.get_client()
            assert returned is mock_client
            assert model.client is None

    def test_session_get_async_client_does_not_mutate_self_async_client(self):
        mock_session = MagicMock(spec=Session)
        mock_session.region_name = "us-east-1"
        mock_session.profile_name = None
        mock_creds = MagicMock()
        mock_creds.get_frozen_credentials.return_value = _make_frozen_creds()
        mock_session.get_credentials.return_value = mock_creds

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        assert model.async_client is None

        with patch("agno.models.aws.claude.AsyncAnthropicBedrock") as MockAsync:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockAsync.return_value = mock_client

            returned = model.get_async_client()
            assert returned is mock_client
            assert model.async_client is None


class TestSessionConcurrencySafe:
    """Concurrent get_client() calls each get their own credentials."""

    def test_concurrent_calls_get_correct_credentials(self):
        call_count = {"n": 0}
        event_a_created = threading.Event()
        event_b_done = threading.Event()

        def rotating_frozen_creds():
            call_count["n"] += 1
            return _make_frozen_creds(
                access_key=f"KEY_{call_count['n']}",
                token=f"TOKEN_{call_count['n']}",
            )

        mock_session = MagicMock(spec=Session)
        mock_session.region_name = "us-east-1"
        mock_session.profile_name = None
        mock_creds = MagicMock()
        mock_creds.get_frozen_credentials.side_effect = rotating_frozen_creds
        mock_session.get_credentials.return_value = mock_creds

        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        results = {}

        with patch("agno.models.aws.claude.AnthropicBedrock") as MockBedrock:
            create_count = {"n": 0}

            def make_client(**kwargs):
                create_count["n"] += 1
                client = MagicMock()
                client.is_closed.return_value = False
                client._test_key = kwargs.get("aws_access_key", "unknown")
                if create_count["n"] == 1:
                    event_a_created.set()
                    event_b_done.wait(timeout=5)
                return client

            MockBedrock.side_effect = make_client

            def call_a():
                results["a"] = model.get_client()

            def call_b():
                event_a_created.wait(timeout=5)
                results["b"] = model.get_client()
                event_b_done.set()

            ta = threading.Thread(target=call_a)
            tb = threading.Thread(target=call_b)
            ta.start()
            tb.start()
            ta.join(timeout=10)
            tb.join(timeout=10)

            assert "a" in results and "b" in results
            assert results["a"]._test_key == "KEY_1", f"Thread A expected KEY_1 but got {results['a']._test_key}"
            assert results["b"]._test_key == "KEY_2", f"Thread B expected KEY_2 but got {results['b']._test_key}"
            assert results["a"] is not results["b"]
