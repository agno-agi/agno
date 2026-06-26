import importlib
from collections import Counter
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

from agno.models.base import Model

if TYPE_CHECKING:
    from agno.registry.registry import Registry

# Single source of truth for every supported model provider. One row per stable provider key:
#   key -> (module, class_name, default_name, default_provider_display)
# `default_name` and `default_provider_display` are the class's default `name` and (lowercased)
# `provider` attributes. The construction registry and the (provider, name) resolution indices
# below are all derived from this table, so adding a provider means adding exactly one row here.
_PROVIDERS: Dict[str, Tuple[str, str, str, str]] = {
    "aimlapi": ("agno.models.aimlapi", "AIMLAPI", "AIMLAPI", "aimlapi"),
    "anthropic": ("agno.models.anthropic", "Claude", "Claude", "anthropic"),
    "aws-bedrock": ("agno.models.aws", "AwsBedrock", "AwsBedrock", "awsbedrock"),
    "aws-claude": ("agno.models.aws", "Claude", "AwsBedrockAnthropicClaude", "awsbedrock"),
    "azure-ai-foundry": ("agno.models.azure", "AzureAIFoundry", "AzureAIFoundry", "azure"),
    "azure-foundry-claude": ("agno.models.azure", "AzureFoundryClaude", "AzureFoundryClaude", "azurefoundry"),
    "azure-openai": ("agno.models.azure", "AzureOpenAI", "AzureOpenAI", "azure"),
    "cerebras": ("agno.models.cerebras", "Cerebras", "Cerebras", "cerebras"),
    "cerebras-openai": ("agno.models.cerebras", "CerebrasOpenAI", "CerebrasOpenAI", "cerebrasopenai"),
    "cohere": ("agno.models.cohere", "Cohere", "cohere", "cohere"),
    "cometapi": ("agno.models.cometapi", "CometAPI", "CometAPI", "openai"),
    "cloudflare": ("agno.models.cloudflare", "Cloudflare", "Cloudflare", "cloudflare"),
    "dashscope": ("agno.models.dashscope", "DashScope", "Qwen", "dashscope"),
    "deepinfra": ("agno.models.deepinfra", "DeepInfra", "DeepInfra", "deepinfra"),
    "deepseek": ("agno.models.deepseek", "DeepSeek", "DeepSeek", "deepseek"),
    "fireworks": ("agno.models.fireworks", "Fireworks", "Fireworks", "fireworks"),
    "google": ("agno.models.google", "Gemini", "Gemini", "google"),
    "google-interactions": ("agno.models.google", "GeminiInteractions", "GeminiInteractions", "google"),
    "groq": ("agno.models.groq", "Groq", "Groq", "groq"),
    "huggingface": ("agno.models.huggingface", "HuggingFace", "HuggingFace", "huggingface"),
    "ibm": ("agno.models.ibm", "WatsonX", "WatsonX", "ibm"),
    "inception": ("agno.models.inception", "Inception", "Inception", "inceptionlabs"),
    "internlm": ("agno.models.internlm", "InternLM", "InternLM", "internlm"),
    "langdb": ("agno.models.langdb", "LangDB", "LangDB", "langdb"),
    "litellm": ("agno.models.litellm", "LiteLLM", "LiteLLM", "litellm"),
    "litellm-openai": ("agno.models.litellm", "LiteLLMOpenAI", "LiteLLMOpenAI", "litellm"),
    "llama-cpp": ("agno.models.llama_cpp", "LlamaCpp", "LlamaCpp", "llamacpp"),
    "llama-openai": ("agno.models.meta", "LlamaOpenAI", "LlamaOpenAI", "llamaopenai"),
    "lmstudio": ("agno.models.lmstudio", "LMStudio", "LMStudio", "lmstudio"),
    "meta": ("agno.models.meta", "Llama", "Llama", "llama"),
    "minimax": ("agno.models.minimax", "MiniMax", "MiniMax", "minimax"),
    "mistral": ("agno.models.mistral", "MistralChat", "MistralChat", "mistral"),
    "moonshot": ("agno.models.moonshot", "MoonShot", "Moonshot", "moonshot"),
    "n1n": ("agno.models.n1n", "N1N", "N1N", "n1n"),
    "nebius": ("agno.models.nebius", "Nebius", "Nebius", "nebius"),
    "neosantara": ("agno.models.neosantara", "Neosantara", "Neosantara", "neosantara"),
    "nexus": ("agno.models.nexus", "Nexus", "Nexus", "nexus"),
    "nvidia": ("agno.models.nvidia", "Nvidia", "Nvidia", "nvidia"),
    "ollama": ("agno.models.ollama", "Ollama", "Ollama", "ollama"),
    "ollama-responses": ("agno.models.ollama", "OllamaResponses", "OllamaResponses", "ollama"),
    "openai": ("agno.models.openai", "OpenAIResponses", "OpenAIResponses", "openai"),
    "openai-chat": ("agno.models.openai", "OpenAIChat", "OpenAIChat", "openai"),
    "openai-responses": ("agno.models.openai", "OpenAIResponses", "OpenAIResponses", "openai"),
    "open-responses": ("agno.models.openai", "OpenResponses", "OpenResponses", "openresponses"),
    "openrouter": ("agno.models.openrouter", "OpenRouter", "OpenRouter", "openrouter"),
    "openrouter-responses": ("agno.models.openrouter", "OpenRouterResponses", "OpenRouterResponses", "openrouter"),
    "perplexity": ("agno.models.perplexity", "Perplexity", "Perplexity", "perplexity"),
    "portkey": ("agno.models.portkey", "Portkey", "Portkey", "portkey"),
    "requesty": ("agno.models.requesty", "Requesty", "Requesty", "requesty"),
    "sambanova": ("agno.models.sambanova", "Sambanova", "Sambanova", "sambanova"),
    "siliconflow": ("agno.models.siliconflow", "Siliconflow", "Siliconflow", "siliconflow"),
    "together": ("agno.models.together", "Together", "Together", "together"),
    "tuning-engines": ("agno.models.tuning_engines", "TuningEngines", "Tuning Engines", "tuning engines"),
    "vercel": ("agno.models.vercel", "V0", "v0", "vercel"),
    "vertexai-claude": ("agno.models.vertexai.claude", "Claude", "Claude", "vertexai"),
    "vllm": ("agno.models.vllm", "VLLM", "VLLM", "vllm"),
    "xai": ("agno.models.xai", "xAI", "xAI", "xai"),
    "xiaomi": ("agno.models.xiaomi", "MiMo", "MiMo", "xiaomi mimo"),
}

# key -> (module, class_name): the construction registry consumed by `_get_model_class`, the
# CONTRIBUTING guide, and the registry-drift test.
MODEL_PROVIDER_CLASSES: Dict[str, Tuple[str, str]] = {key: (mod, cls) for key, (mod, cls, _n, _p) in _PROVIDERS.items()}

# key -> lowercased display `provider` string the class reports.
_KEY_TO_PROVIDER: Dict[str, str] = {key: prov for key, (_m, _c, _n, prov) in _PROVIDERS.items()}

# Serialized `name` -> key, but only for names that identify exactly one provider. Names shared
# across classes (e.g. "Claude") are ambiguous and omitted, so those fall back to the provider.
_name_counts = Counter(name for (_m, _c, name, _p) in _PROVIDERS.values())
_NAME_TO_PROVIDER_KEY: Dict[str, str] = {
    name: key for key, (_m, _c, name, _p) in _PROVIDERS.items() if _name_counts[name] == 1
}

# Default key for a display `provider` string that is not itself a key. Where several classes
# share such a string (e.g. "azure" -> AzureOpenAI/AzureAIFoundry), the default is the variant
# used when `name` does not disambiguate.
_AMBIGUOUS_PROVIDER_DEFAULTS: Dict[str, str] = {"azure": "azure-openai", "awsbedrock": "aws-bedrock"}


def _build_provider_to_key() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for key, (_m, _c, _n, prov) in _PROVIDERS.items():
        if prov not in MODEL_PROVIDER_CLASSES:  # display strings that already equal a key resolve directly
            mapping.setdefault(prov, key)
    mapping.update(_AMBIGUOUS_PROVIDER_DEFAULTS)
    return mapping


# Display `provider` string -> key, used as a fallback when `name` is missing or shared.
_PROVIDER_TO_KEY: Dict[str, str] = _build_provider_to_key()


def _canonical_provider_display(key: str) -> str:
    """The lowercased display `provider` string a given provider key's class reports."""
    return _KEY_TO_PROVIDER.get(key, key)


def _resolve_provider_key(model_provider: Optional[str], model_name: Optional[str] = None) -> str:
    """Resolve a serialized (provider, name) pair to a stable provider key.

    The provider string is authoritative. `name` is used only to disambiguate among classes that
    report the same display `provider` (e.g. AzureOpenAI vs AzureAIFoundry, or OpenAIResponses vs
    the OpenAI-compatible CometAPI). A `name` whose class reports a different provider is treated
    as a user-supplied label and ignored, so e.g. OpenAIChat(name="Gemini") still resolves to
    OpenAI rather than Google.
    """
    provider = (model_provider or "").strip().lower()
    provider_key = provider if provider in MODEL_PROVIDER_CLASSES else _PROVIDER_TO_KEY.get(provider)
    name_key = _NAME_TO_PROVIDER_KEY.get(model_name) if model_name else None

    if provider_key is None:
        # An empty provider string (older data, or a model whose provider was never set) leaves the
        # name as the only signal. A non-empty but unrecognized provider stays authoritative so an
        # unsupported/custom provider is rejected by _get_model_class rather than being silently
        # re-routed to a built-in class by a colliding name.
        return (name_key or provider) if not provider else provider

    # Otherwise trust the name only when its class reports this same provider string.
    if name_key is not None and _canonical_provider_display(name_key) == provider:
        return name_key
    return provider_key


def _get_model_class(model_id: str, model_provider: str) -> Model:
    entry = MODEL_PROVIDER_CLASSES.get(model_provider)
    if entry is None:
        # Allow alias forms (e.g. "azure", "inceptionlabs") to resolve too.
        resolved = _resolve_provider_key(model_provider)
        entry = MODEL_PROVIDER_CLASSES.get(resolved)
    if entry is None:
        raise ValueError(f"Model provider '{model_provider}' is not supported.")

    module_path, class_name = entry
    module = importlib.import_module(module_path)
    model_class = getattr(module, class_name)
    return model_class(id=model_id)


def _parse_model_string(model_string: str) -> Model:
    if not model_string or not isinstance(model_string, str):
        raise ValueError(f"Model string must be a non-empty string, got: {model_string}")

    if ":" not in model_string:
        raise ValueError(
            f"Invalid model string format: '{model_string}'. Model strings should be in format '<provider>:<model_id>' e.g. 'openai:gpt-4o'"
        )

    parts = model_string.split(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid model string format: '{model_string}'. Model strings should be in format '<provider>:<model_id>' e.g. 'openai:gpt-4o'"
        )

    model_provider, model_id = parts
    model_provider = model_provider.strip().lower()
    model_id = model_id.strip()

    if not model_provider or not model_id:
        raise ValueError(
            f"Invalid model string format: '{model_string}'. Model strings should be in format '<provider>:<model_id>' e.g. 'openai:gpt-4o'"
        )

    return _get_model_class(model_id, _resolve_provider_key(model_provider))


def get_model(model: Union[Model, str, None]) -> Optional[Model]:
    if model is None:
        return None
    elif isinstance(model, Model):
        return model
    elif isinstance(model, str):
        return _parse_model_string(model)
    else:
        raise ValueError("Model must be a Model instance, string, or None")


def get_model_from_dict(model_data: Dict[str, Any]) -> Optional[Model]:
    """Reconstruct a Model from its serialized dict (as produced by ``Model.to_dict``).

    Uses both the serialized ``provider`` and ``name`` to resolve the exact provider class,
    which is required for providers that share a display ``provider`` string (e.g. Azure).
    """
    if not isinstance(model_data, dict):
        raise ValueError("Model data must be a dictionary")

    model_id = model_data.get("id")
    if not model_id:
        raise ValueError(f"Model data is missing an 'id': {model_data}")

    provider_key = _resolve_provider_key(model_data.get("provider"), model_data.get("name"))
    return _get_model_class(model_id, provider_key)


def resolve_model(model_data: Any, registry: Optional["Registry"] = None) -> Any:
    """Reconstruct a model from its serialized config, preferring a registered live instance.

    Rebuilding from a serialized dict only round-trips ``id``/``name``/``provider`` (see
    ``Model.to_dict``), so connection params like ``azure_endpoint``/``base_url`` and any
    credentials are lost. When the model is present in the registry, its live, fully-configured
    instance is reused; otherwise we fall back to rebuilding from the dict (or a ``provider:id``
    string). Values that are neither a model dict nor a string are returned unchanged.

    Shared by Agent and Team reconstruction so both resolve models identically.
    """
    if isinstance(model_data, dict) and "id" in model_data:
        if registry is not None:
            registered_model = registry.get_model(
                model_data["id"],
                provider=model_data.get("provider"),
                name=model_data.get("name"),
            )
            if registered_model is not None:
                return registered_model
        return get_model_from_dict(model_data)
    elif isinstance(model_data, str):
        return get_model(model_data)
    return model_data
