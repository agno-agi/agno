"""Utilities for model provider normalization."""

# Canonical alias map: keys are lowercase, stripped of hyphens and underscores.
# Values are the canonical provider identifiers expected by _get_model_class().
PROVIDER_ALIASES: dict[str, str] = {
    # OpenAI
    "openai": "openai",
    "openaichat": "openai",
    "openairesponses": "openai-responses",
    "openresponses": "openai-responses",
    # Anthropic
    "anthropic": "anthropic",
    # AWS
    "awsbedrock": "aws-bedrock",
    "awsclaude": "aws-claude",
    # Azure
    "azure": "azure-openai",
    "azureopenai": "azure-openai",
    "azureaifoundry": "azure-ai-foundry",
    # Cerebras
    "cerebras": "cerebras",
    "cerebrasopenai": "cerebras-openai",
    # Cohere
    "cohere": "cohere",
    # DashScope
    "dashscope": "dashscope",
    # DeepInfra
    "deepinfra": "deepinfra",
    # DeepSeek
    "deepseek": "deepseek",
    # Fireworks
    "fireworks": "fireworks",
    # Google
    "google": "google",
    # Groq
    "groq": "groq",
    # HuggingFace
    "huggingface": "huggingface",
    # IBM
    "ibm": "ibm",
    # InternLM
    "internlm": "internlm",
    # LangDB
    "langdb": "langdb",
    # LiteLLM
    "litellm": "litellm",
    "litellmopenai": "litellm-openai",
    # LlamaCpp
    "llamacpp": "llama-cpp",
    # LM Studio
    "lmstudio": "lmstudio",
    # Meta / Llama
    "llamaopenai": "llama-openai",
    # Mistral
    "mistral": "mistral",
    # Moonshot
    "moonshot": "moonshot",
    # Nebius
    "nebius": "nebius",
    # Neosantara
    "neosantara": "neosantara",
    # Nexus
    "nexus": "nexus",
    # Nvidia
    "nvidia": "nvidia",
    # Ollama
    "ollama": "ollama",
    # OpenRouter
    "openrouter": "openrouter",
    # Perplexity
    "perplexity": "perplexity",
    # Portkey
    "portkey": "portkey",
    # Requesty
    "requesty": "requesty",
    # Sambanova
    "sambanova": "sambanova",
    # Siliconflow
    "siliconflow": "siliconflow",
    # Together
    "together": "together",
    # Vercel
    "vercel": "vercel",
    # VLLM
    "vllm": "vllm",
    # xAI
    "xai": "xai",
    # AIMLAPI
    "aimlapi": "aimlapi",
    # CometAPI
    "cometapi": "cometapi",
    # AIML
    "aiml": "aimlapi",
}


def normalize_provider(provider: str) -> str:
    """Normalize a provider string to its canonical form.

    Handles inconsistencies between the ``provider`` field exposed by runtime
    model instances (e.g. ``"OpenAI"``, ``"Azure"``, ``"LMStudio"``) and the
    canonical identifiers expected by ``_parse_model_string()`` / ``get_model()``
    (e.g. ``"openai"``, ``"azure-openai"``, ``"lmstudio"``).

    The lookup key is derived by lowercasing the input and stripping all
    hyphens and underscores so that ``"azure-openai"``, ``"Azure_OpenAI"``,
    and ``"AzureOpenAI"`` all resolve to the same canonical form.

    Args:
        provider: Raw provider string (may be mixed-case or hyphenated).

    Returns:
        Canonical provider identifier suitable for use with ``get_model()``.

    Examples::

        >>> normalize_provider("OpenAI")
        'openai'
        >>> normalize_provider("Azure")
        'azure-openai'
        >>> normalize_provider("LMStudio")
        'lmstudio'
        >>> normalize_provider("Siliconflow")
        'siliconflow'
        >>> normalize_provider("AwsBedrock")
        'aws-bedrock'
    """
    key = provider.lower().replace("-", "").replace("_", "")
    return PROVIDER_ALIASES.get(key, provider.lower())
