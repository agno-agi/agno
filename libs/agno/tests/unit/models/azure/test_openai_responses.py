import asyncio

import pytest
from openai import AsyncAzureOpenAI, AzureOpenAI

from agno.exceptions import ModelAuthenticationError
from agno.models.azure.openai_responses import AzureOpenAIResponses


def test_client_params_support_api_key(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        api_version="2025-03-01-preview",
        azure_endpoint="https://example.openai.azure.com",
    )

    params = model._get_client_params()

    assert params["api_key"] == "test-key"
    assert params["api_version"] == "2025-03-01-preview"
    assert params["azure_endpoint"] == "https://example.openai.azure.com"
    assert "azure_ad_token" not in params


def test_client_params_prefer_explicit_ad_token_over_key_environment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "environment-key")
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        azure_ad_token="explicit-token",
        api_version="2025-03-01-preview",
        azure_endpoint="https://example.openai.azure.com",
    )

    params = model._get_client_params()

    assert params["azure_ad_token"] == "explicit-token"
    assert "api_key" not in params


def test_client_params_load_azure_environment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://environment.openai.azure.com")
    monkeypatch.setenv("OPENAI_API_VERSION", "2025-03-01-preview")
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    model = AzureOpenAIResponses(id="environment-deployment")

    params = model._get_client_params()

    assert params["api_key"] == "environment-key"
    assert params["azure_endpoint"] == "https://environment.openai.azure.com"
    assert params["api_version"] == "2025-03-01-preview"


def test_missing_authentication_raises_model_error(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    model = AzureOpenAIResponses(id="reasoning-deployment")

    with pytest.raises(ModelAuthenticationError, match="Azure OpenAI authentication not configured"):
        model._get_client_params()


def test_responses_request_uses_full_deployment_name_as_model():
    model = AzureOpenAIResponses(id="my-full-azure-deployment", api_key="test-key")

    assert model._get_model_request_kwargs() == {"model": "my-full-azure-deployment"}


def test_sync_client_is_azure_and_cached():
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        api_version="2025-03-01-preview",
        azure_endpoint="https://example.openai.azure.com",
    )

    client = model.get_client()

    assert isinstance(client, AzureOpenAI)
    assert hasattr(client, "responses")
    assert model.get_client() is client
    client.close()


def test_async_client_is_azure_and_cached():
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        api_version="2025-03-01-preview",
        azure_endpoint="https://example.openai.azure.com",
    )

    client = model.get_async_client()

    assert isinstance(client, AsyncAzureOpenAI)
    assert hasattr(client, "responses")
    assert model.get_async_client() is client
    asyncio.run(client.close())


def test_api_version_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_API_VERSION", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        azure_endpoint="https://example.openai.azure.com",
    )

    params = model._get_client_params()

    assert params["api_version"] == "2025-04-01-preview"


def test_api_version_env_overrides_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_VERSION", "2025-03-01-preview")
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        azure_endpoint="https://example.openai.azure.com",
    )

    params = model._get_client_params()

    assert params["api_version"] == "2025-03-01-preview"


def test_id_is_required():
    with pytest.raises(ValueError, match="Azure deployment name"):
        AzureOpenAIResponses(api_key="test-key")  # type: ignore[call-arg]


def test_env_api_key_preferred_over_env_ad_token(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("AZURE_OPENAI_AD_TOKEN", "environment-token")
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        azure_endpoint="https://example.openai.azure.com",
    )

    params = model._get_client_params()

    assert params["api_key"] == "environment-key"
    assert "azure_ad_token" not in params


def test_base_url_skips_endpoint_env_fallback(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://environment.openai.azure.com")
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        base_url="https://example.openai.azure.com/openai/v1/",
    )

    params = model._get_client_params()

    assert params["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert "azure_endpoint" not in params


def test_reasoning_model_flag_overrides_deployment_name_heuristic():
    assert AzureOpenAIResponses(id="prod-reasoner", is_reasoning_model=True)._using_reasoning_model() is True
    assert AzureOpenAIResponses(id="gpt-5-deployment", is_reasoning_model=False)._using_reasoning_model() is False
    # None falls back to the deployment-name heuristic
    assert AzureOpenAIResponses(id="gpt-5-deployment")._using_reasoning_model() is True
    assert AzureOpenAIResponses(id="prod-reasoner")._using_reasoning_model() is False


def test_deepcopy_preserves_client_references():
    from copy import deepcopy

    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        azure_endpoint="https://example.openai.azure.com",
    )
    client = model.get_client()

    model_copy = deepcopy(model)

    assert model_copy.client is client
    client.close()
