import importlib
from typing import Any, Dict, Optional, Tuple, Union

from agno.models.base import Model

# Single source of truth mapping a stable provider key to the (module, class name) that
# implements it. `_get_model_class` constructs from this and the round-trip resolver below
# maps a serialized model back to the correct key. Add new providers here only.
MODEL_PROVIDER_CLASSES: Dict[str, Tuple[str, str]] = {
    "aimlapi": ("agno.models.aimlapi", "AIMLAPI"),
    "anthropic": ("agno.models.anthropic", "Claude"),
    "aws-bedrock": ("agno.models.aws", "AwsBedrock"),
    "aws-claude": ("agno.models.aws", "Claude"),
    "azure-ai-foundry": ("agno.models.azure", "AzureAIFoundry"),
    "azure-foundry-claude": ("agno.models.azure", "AzureFoundryClaude"),
    "azure-openai": ("agno.models.azure", "AzureOpenAI"),
    "cerebras": ("agno.models.cerebras", "Cerebras"),
    "cerebras-openai": ("agno.models.cerebras", "CerebrasOpenAI"),
    "cohere": ("agno.models.cohere", "Cohere"),
    "cometapi": ("agno.models.cometapi", "CometAPI"),
    "cloudflare": ("agno.models.cloudflare", "Cloudflare"),
    "dashscope": ("agno.models.dashscope", "DashScope"),
    "deepinfra": ("agno.models.deepinfra", "DeepInfra"),
    "deepseek": ("agno.models.deepseek", "DeepSeek"),
    "fireworks": ("agno.models.fireworks", "Fireworks"),
    "google": ("agno.models.google", "Gemini"),
    "google-interactions": ("agno.models.google", "GeminiInteractions"),
    "groq": ("agno.models.groq", "Groq"),
    "huggingface": ("agno.models.huggingface", "HuggingFace"),
    "ibm": ("agno.models.ibm", "WatsonX"),
    "inception": ("agno.models.inception", "Inception"),
    "internlm": ("agno.models.internlm", "InternLM"),
    "langdb": ("agno.models.langdb", "LangDB"),
    "litellm": ("agno.models.litellm", "LiteLLM"),
    "litellm-openai": ("agno.models.litellm", "LiteLLMOpenAI"),
    "llama-cpp": ("agno.models.llama_cpp", "LlamaCpp"),
    "llama-openai": ("agno.models.meta", "LlamaOpenAI"),
    "lmstudio": ("agno.models.lmstudio", "LMStudio"),
    "meta": ("agno.models.meta", "Llama"),
    "minimax": ("agno.models.minimax", "MiniMax"),
    "mistral": ("agno.models.mistral", "MistralChat"),
    "moonshot": ("agno.models.moonshot", "MoonShot"),
    "n1n": ("agno.models.n1n", "N1N"),
    "nebius": ("agno.models.nebius", "Nebius"),
    "neosantara": ("agno.models.neosantara", "Neosantara"),
    "nexus": ("agno.models.nexus", "Nexus"),
    "nvidia": ("agno.models.nvidia", "Nvidia"),
    "ollama": ("agno.models.ollama", "Ollama"),
    "ollama-responses": ("agno.models.ollama", "OllamaResponses"),
    "openai": ("agno.models.openai", "OpenAIResponses"),
    "openai-chat": ("agno.models.openai", "OpenAIChat"),
    "openai-responses": ("agno.models.openai", "OpenAIResponses"),
    "open-responses": ("agno.models.openai", "OpenResponses"),
    "openrouter": ("agno.models.openrouter", "OpenRouter"),
    "openrouter-responses": ("agno.models.openrouter", "OpenRouterResponses"),
    "perplexity": ("agno.models.perplexity", "Perplexity"),
    "portkey": ("agno.models.portkey", "Portkey"),
    "requesty": ("agno.models.requesty", "Requesty"),
    "sambanova": ("agno.models.sambanova", "Sambanova"),
    "siliconflow": ("agno.models.siliconflow", "Siliconflow"),
    "together": ("agno.models.together", "Together"),
    "tuning-engines": ("agno.models.tuning_engines", "TuningEngines"),
    "vercel": ("agno.models.vercel", "V0"),
    "vertexai-claude": ("agno.models.vertexai.claude", "Claude"),
    "vllm": ("agno.models.vllm", "VLLM"),
    "xai": ("agno.models.xai", "xAI"),
    "xiaomi": ("agno.models.xiaomi", "MiMo"),
}

# Maps a serialized model `name` (the per-class default name attribute) to its provider key.
# `name` is the most specific discriminator and is needed when two providers share the same
# display `provider` string (e.g. all Azure models report provider "Azure"). Names that are
# shared across classes (e.g. "Claude", "LiteLLM") are intentionally omitted here and fall back
# to provider-based resolution.
_NAME_TO_PROVIDER_KEY: Dict[str, str] = {
    "AIMLAPI": "aimlapi",
    "AwsBedrock": "aws-bedrock",
    "AwsBedrockAnthropicClaude": "aws-claude",
    "AzureAIFoundry": "azure-ai-foundry",
    "AzureFoundryClaude": "azure-foundry-claude",
    "AzureOpenAI": "azure-openai",
    "Cerebras": "cerebras",
    "CerebrasOpenAI": "cerebras-openai",
    "Cloudflare": "cloudflare",
    "CometAPI": "cometapi",
    "cohere": "cohere",
    "Qwen": "dashscope",
    "DeepInfra": "deepinfra",
    "DeepSeek": "deepseek",
    "Fireworks": "fireworks",
    "Gemini": "google",
    "GeminiInteractions": "google-interactions",
    "Groq": "groq",
    "HuggingFace": "huggingface",
    "WatsonX": "ibm",
    "Inception": "inception",
    "InternLM": "internlm",
    "LangDB": "langdb",
    "LiteLLMOpenAI": "litellm-openai",
    "LlamaCpp": "llama-cpp",
    "LMStudio": "lmstudio",
    "Llama": "meta",
    "LlamaOpenAI": "llama-openai",
    "MiniMax": "minimax",
    "MistralChat": "mistral",
    "Moonshot": "moonshot",
    "N1N": "n1n",
    "Nebius": "nebius",
    "Neosantara": "neosantara",
    "Nexus": "nexus",
    "Nvidia": "nvidia",
    "Ollama": "ollama",
    "OllamaResponses": "ollama-responses",
    "OpenAIChat": "openai-chat",
    "OpenAIResponses": "openai-responses",
    "OpenResponses": "open-responses",
    "OpenRouter": "openrouter",
    "OpenRouterResponses": "openrouter-responses",
    "Perplexity": "perplexity",
    "Portkey": "portkey",
    "Requesty": "requesty",
    "Sambanova": "sambanova",
    "Siliconflow": "siliconflow",
    "Together": "together",
    "Tuning Engines": "tuning-engines",
    "v0": "vercel",
    "VLLM": "vllm",
    "xAI": "xai",
    "MiMo": "xiaomi",
}

# Maps a lowercased serialized `provider` display string to its provider key, for providers
# whose display string does not already equal a key. Used as a fallback when `name` is missing
# or shared. Keeps the string form (e.g. "azure:gpt-4o") working too.
_PROVIDER_ALIASES: Dict[str, str] = {
    "awsbedrock": "aws-bedrock",
    "azure": "azure-openai",
    "azurefoundry": "azure-foundry-claude",
    "cerebrasopenai": "cerebras-openai",
    "inceptionlabs": "inception",
    "llama": "meta",
    "llamacpp": "llama-cpp",
    "llamaopenai": "llama-openai",
    "openresponses": "open-responses",
    "tuning engines": "tuning-engines",
    "vertexai": "vertexai-claude",
    "xiaomi mimo": "xiaomi",
}


# The lowercased display `provider` string each key's class reports, listed only where it differs
# from the key itself (most keys equal their provider string). Several distinct classes share a
# provider string -- e.g. OpenAIResponses, OpenAIChat, and OpenAI-compatible providers like
# CometAPI all report "OpenAI" -- so this is what tells whether a serialized `name` legitimately
# belongs to the serialized provider.
_PROVIDER_DISPLAY_OVERRIDES: Dict[str, str] = {
    "openai-chat": "openai",
    "openai-responses": "openai",
    "cometapi": "openai",
    "google-interactions": "google",
    "openrouter-responses": "openrouter",
    "azure-openai": "azure",
    "azure-ai-foundry": "azure",
    "azure-foundry-claude": "azurefoundry",
    "aws-bedrock": "awsbedrock",
    "aws-claude": "awsbedrock",
    "ollama-responses": "ollama",
    "litellm-openai": "litellm",
    "cerebras-openai": "cerebrasopenai",
    "inception": "inceptionlabs",
    "llama-cpp": "llamacpp",
    "meta": "llama",
    "llama-openai": "llamaopenai",
    "vertexai-claude": "vertexai",
    "xiaomi": "xiaomi mimo",
    "open-responses": "openresponses",
    "tuning-engines": "tuning engines",
}


def _canonical_provider_display(key: str) -> str:
    """The lowercased display `provider` string a given provider key's class reports."""
    return _PROVIDER_DISPLAY_OVERRIDES.get(key, key)


def _resolve_provider_key(model_provider: Optional[str], model_name: Optional[str] = None) -> str:
    """Resolve a serialized (provider, name) pair to a stable provider key.

    The provider string is authoritative. `name` is used only to disambiguate among classes that
    report the same display `provider` (e.g. AzureOpenAI vs AzureAIFoundry, or OpenAIResponses vs
    the OpenAI-compatible CometAPI). A `name` whose class reports a different provider is treated
    as a user-supplied label and ignored, so e.g. OpenAIChat(name="Gemini") still resolves to
    OpenAI rather than Google.
    """
    provider = (model_provider or "").strip().lower()
    provider_key = provider if provider in MODEL_PROVIDER_CLASSES else _PROVIDER_ALIASES.get(provider)
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
