"""Tests for provider-key resolution used when reconstructing models from a serialized dict.

These guard the round-trip ``Model.to_dict() -> get_model_from_dict()`` so that a model loaded
from the database (e.g. the components table) rebuilds as the correct provider class, and so a
single unsupported/misconfigured provider no longer needs special-casing per call site.
"""

import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.utils import (
    MODEL_PROVIDER_CLASSES,
    _get_model_class,
    _resolve_provider_key,
    get_model_from_dict,
)

# Providers whose model classes require an optional SDK at construction time. We cannot
# instantiate them in the base test environment, so they are covered by the
# resolution-only test below using their known serialized (provider, name) pairs.
SDK_GATED_KEYS = {
    "aws-bedrock",
    "aws-claude",
    "azure-ai-foundry",
    "cerebras",
    "cerebras-openai",
    "cohere",
    "groq",
    "huggingface",
    "ibm",
    "litellm",
    "litellm-openai",
    "llama-openai",
    "meta",
    "mistral",
    "ollama",
    "ollama-responses",
    "portkey",
}

CONSTRUCTABLE_KEYS = [k for k in MODEL_PROVIDER_CLASSES if k not in SDK_GATED_KEYS]


@pytest.mark.parametrize("key", CONSTRUCTABLE_KEYS)
def test_to_dict_round_trip_preserves_class(key):
    """Every constructable provider rebuilds as the same class through to_dict/from_dict."""
    model = _get_model_class("test-id", key)
    rebuilt = get_model_from_dict(model.to_dict())
    assert type(rebuilt) is type(model)
    assert rebuilt.id == "test-id"


@pytest.mark.parametrize(
    "provider, name, expected_key",
    [
        # The crash from the components table: Azure models all report provider "Azure".
        ("Azure", "AzureOpenAI", "azure-openai"),
        ("Azure", "AzureAIFoundry", "azure-ai-foundry"),
        ("AzureFoundry", "AzureFoundryClaude", "azure-foundry-claude"),
        # SDK-gated providers, validated via their serialized (provider, name) pairs.
        ("AwsBedrock", "AwsBedrock", "aws-bedrock"),
        ("AwsBedrock", "AwsBedrockAnthropicClaude", "aws-claude"),
        ("Cerebras", "Cerebras", "cerebras"),
        ("CerebrasOpenAI", "CerebrasOpenAI", "cerebras-openai"),
        ("Cohere", "cohere", "cohere"),
        ("Groq", "Groq", "groq"),
        ("HuggingFace", "HuggingFace", "huggingface"),
        ("IBM", "WatsonX", "ibm"),
        ("LiteLLM", "LiteLLM", "litellm"),
        ("LiteLLM", "LiteLLMOpenAI", "litellm-openai"),
        ("Llama", "Llama", "meta"),
        ("LlamaOpenAI", "LlamaOpenAI", "llama-openai"),
        ("Mistral", "MistralChat", "mistral"),
        ("Ollama", "Ollama", "ollama"),
        ("Ollama", "OllamaResponses", "ollama-responses"),
        ("Portkey", "Portkey", "portkey"),
    ],
)
def test_resolve_sdk_gated_providers(provider, name, expected_key):
    assert _resolve_provider_key(provider, name) == expected_key


@pytest.mark.parametrize(
    "provider, name, expected_key",
    [
        # Display-string providers that differ from the registry key resolve via alias,
        # including the legacy/string path where no name is serialized.
        ("Azure", None, "azure-openai"),
        ("azure", None, "azure-openai"),
        ("InceptionLabs", None, "inception"),
        ("VertexAI", None, "vertexai-claude"),
        ("LlamaCpp", None, "llama-cpp"),
        ("Xiaomi MiMo", None, "xiaomi"),
        # CometAPI sets provider to "CometAPI (<id>)" via post-init; name still resolves it.
        ("CometAPI (gpt-x)", "CometAPI", "cometapi"),
        # Plain providers whose display string already equals the key.
        ("openai", None, "openai"),
        ("anthropic", None, "anthropic"),
    ],
)
def test_resolve_provider_aliases(provider, name, expected_key):
    assert _resolve_provider_key(provider, name) == expected_key


def test_unsupported_provider_raises():
    with pytest.raises(ValueError, match="is not supported"):
        _get_model_class("some-id", "definitely-not-a-provider")


def test_get_model_from_dict_requires_id():
    with pytest.raises(ValueError, match="missing an 'id'"):
        get_model_from_dict({"provider": "openai"})
