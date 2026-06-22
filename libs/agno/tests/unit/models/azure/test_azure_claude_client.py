from unittest.mock import MagicMock, patch

from agno.models.azure import AzureFoundryClaude


class TestClientCached:
    def test_sync_client_cached(self):
        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="test-key",
            resource="my-resource",
        )

        with patch("agno.models.azure.claude.AnthropicFoundry") as MockFoundry:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockFoundry.return_value = mock_client

            client1 = model.get_client()
            client2 = model.get_client()

            assert MockFoundry.call_count == 1
            assert client1 is client2

    def test_async_client_cached(self):
        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="test-key",
            resource="my-resource",
        )

        with patch("agno.models.azure.claude.AsyncAnthropicFoundry") as MockAsyncFoundry:
            mock_client = MagicMock()
            mock_client.is_closed.return_value = False
            MockAsyncFoundry.return_value = mock_client

            client1 = model.get_async_client()
            client2 = model.get_async_client()

            assert MockAsyncFoundry.call_count == 1
            assert client1 is client2


class TestIsClosedRecreation:
    def test_closed_sync_client_is_recreated(self):
        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="test-key",
            resource="my-resource",
        )

        closed_client = MagicMock()
        closed_client.is_closed.return_value = True
        model.client = closed_client

        with patch("agno.models.azure.claude.AnthropicFoundry") as MockFoundry:
            new_client = MagicMock()
            new_client.is_closed.return_value = False
            MockFoundry.return_value = new_client

            result = model.get_client()

            assert result is new_client
            assert MockFoundry.call_count == 1

    def test_open_sync_client_is_reused(self):
        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="test-key",
            resource="my-resource",
        )

        open_client = MagicMock()
        open_client.is_closed.return_value = False
        model.client = open_client

        result = model.get_client()
        assert result is open_client

    def test_closed_async_client_is_recreated(self):
        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="test-key",
            resource="my-resource",
        )

        closed_client = MagicMock()
        closed_client.is_closed.return_value = True
        model.async_client = closed_client

        with patch("agno.models.azure.claude.AsyncAnthropicFoundry") as MockAsyncFoundry:
            new_client = MagicMock()
            new_client.is_closed.return_value = False
            MockAsyncFoundry.return_value = new_client

            result = model.get_async_client()

            assert result is new_client
            assert MockAsyncFoundry.call_count == 1

    def test_open_async_client_is_reused(self):
        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="test-key",
            resource="my-resource",
        )

        open_client = MagicMock()
        open_client.is_closed.return_value = False
        model.async_client = open_client

        result = model.get_async_client()
        assert result is open_client


class TestEnvVarFallbacks:
    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "env-api-key")
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)

        model = AzureFoundryClaude(id="claude-sonnet-4-5")
        params = model._get_client_params()

        assert params["api_key"] == "env-api-key"

    def test_resource_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "key")
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "my-resource")
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)

        model = AzureFoundryClaude(id="claude-sonnet-4-5")
        params = model._get_client_params()

        assert params["resource"] == "my-resource"

    def test_base_url_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "key")
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_BASE_URL", "https://custom.azure.com")
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)

        model = AzureFoundryClaude(id="claude-sonnet-4-5")
        params = model._get_client_params()

        assert params["base_url"] == "https://custom.azure.com"


class TestClientParams:
    def test_api_key_auth(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)

        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="explicit-key",
            resource="my-resource",
        )
        params = model._get_client_params()

        assert params["api_key"] == "explicit-key"
        assert params["resource"] == "my-resource"

    def test_token_provider_auth(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)

        def my_token_provider() -> str:
            return "azure-ad-token"

        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            azure_ad_token_provider=my_token_provider,
            resource="my-resource",
        )
        params = model._get_client_params()

        assert params["azure_ad_token_provider"] is my_token_provider
        assert "api_key" not in params

    def test_timeout_and_max_retries(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)

        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="key",
            timeout=30,
            max_retries=5,
        )
        params = model._get_client_params()

        assert params["timeout"] == 30
        assert params["max_retries"] == 5

    def test_default_headers(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)

        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="key",
            default_headers={"X-Custom": "value"},
        )
        params = model._get_client_params()

        assert params["default_headers"] == {"X-Custom": "value"}

    def test_client_params_merge(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)

        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="key",
            client_params={"custom_param": "custom_value"},
        )
        params = model._get_client_params()

        assert params["custom_param"] == "custom_value"
        assert params["api_key"] == "key"

    def test_explicit_params_override_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "env-key")
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "env-resource")
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)

        model = AzureFoundryClaude(
            id="claude-sonnet-4-5",
            api_key="explicit-key",
            resource="explicit-resource",
        )
        params = model._get_client_params()

        assert params["api_key"] == "explicit-key"
        assert params["resource"] == "explicit-resource"
