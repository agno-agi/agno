from typing import Union

from agno.models.base import Model

PROVIDERS = {
    "openai": ("agno.models.openai", "OpenAIChat"),
    "anthropic": ("agno.models.anthropic", "Claude"),
    "google": ("agno.models.google", "Gemini"),
    "groq": ("agno.models.groq", "Groq"),
    "ollama": ("agno.models.ollama", "Ollama"),
    "aws": ("agno.models.aws", "AwsBedrock"),
    "aws-bedrock": ("agno.models.aws", "AwsBedrock"),
    "aws-claude": ("agno.models.aws", "Claude"),
    "azure": ("agno.models.azure", "AzureOpenAI"),
    "azure-openai": ("agno.models.azure", "AzureOpenAI"),
    "azure-ai-foundry": ("agno.models.azure", "AzureAIFoundry"),
    "mistral": ("agno.models.mistral", "MistralChat"),
    "cohere": ("agno.models.cohere", "Cohere"),
    "together": ("agno.models.together", "Together"),
    "fireworks": ("agno.models.fireworks", "Fireworks"),
    "perplexity": ("agno.models.perplexity", "Perplexity"),
    "openrouter": ("agno.models.openrouter", "OpenRouter"),
    "meta": ("agno.models.meta", "Llama"),
    "llama": ("agno.models.meta", "Llama"),
    "llama-openai": ("agno.models.meta", "LlamaOpenAI"),
    "cerebras": ("agno.models.cerebras", "Cerebras"),
    "xai": ("agno.models.xai", "xAI"),
    "deepseek": ("agno.models.deepseek", "DeepSeek"),
    "nvidia": ("agno.models.nvidia", "Nvidia"),
    "sambanova": ("agno.models.sambanova", "Sambanova"),
    "deepinfra": ("agno.models.deepinfra", "DeepInfra"),
    "nebius": ("agno.models.nebius", "Nebius"),
    "internlm": ("agno.models.internlm", "InternLM"),
    "dashscope": ("agno.models.dashscope", "DashScope"),
    "huggingface": ("agno.models.huggingface", "HuggingFace"),
    "ibm": ("agno.models.ibm", "WatsonX"),
    "litellm": ("agno.models.litellm", "LiteLLM"),
    "lmstudio": ("agno.models.lmstudio", "LMStudio"),
    "portkey": ("agno.models.portkey", "Portkey"),
    "vllm": ("agno.models.vllm", "VLLM"),
    "vercel": ("agno.models.vercel", "V0"),
    "langdb": ("agno.models.langdb", "LangDB"),
    "aimlapi": ("agno.models.aimlapi", "AIMLAPI"),
}


def create_model(model: Union[Model, str]) -> Model:
    """Create a model instance from either a Model object or model string.
    Args:
        model: Either a Model instance or a string in format 'provider:model_id'

    Returns:
        Model instance
    """
    # Handle existing Model objects
    if isinstance(model, Model):
        return model

    # Handle string-based model creation
    if isinstance(model, str):
        # Parse model string
        if ":" not in model:
            raise ValueError(f"Model string must be 'provider:model_id', got: {model}")

        provider, model_id = model.split(":", 1)
        provider = provider.lower().strip()
        model_id = model_id.strip()

        if not provider or not model_id:
            raise ValueError(f"Both provider and model_id must be non-empty, got: {model}")

        # Validate provider
        if provider not in PROVIDERS:
            available = ", ".join(sorted(PROVIDERS.keys()))
            raise ValueError(f"Provider '{provider}' not supported. Available: {available}")

        # Create model instance
        module_path, class_name = PROVIDERS[provider]

        try:
            import importlib

            module = importlib.import_module(module_path)
            model_class = getattr(module, class_name)
            return model_class(id=model_id)
        except ImportError as e:
            raise ImportError(
                f"Failed to import {class_name} from {module_path}. "
                f"Install required dependencies for {provider}. Original error: {e}"
            ) from e
        except AttributeError as e:
            raise ValueError(f"Model class {class_name} not found in {module_path}") from e

    # Invalid type
    raise TypeError(f"Model must be Model instance or string, got {type(model)}")


def get_model_string(model: Model) -> str:
    """Generate model string from model instance.

    Args:
        model: Model instance

    Returns:
        String in format 'provider:model_id'
    """
    class_name = model.__class__.__name__

    # Reverse lookup from PROVIDERS mapping
    for provider, (_, cls) in PROVIDERS.items():
        if cls == class_name:
            return f"{provider}:{model.id}"

    # Fallback for custom models
    provider = getattr(model, "provider", class_name.lower())
    return f"{provider}:{model.id}"
