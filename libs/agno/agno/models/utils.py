from typing import Union
from agno.models.base import Model


# Comprehensive mapping of provider strings to their main model classes
PROVIDER_MODEL_MAP = {
    "openai": ("agno.models.openai", "OpenAIChat"),
    "anthropic": ("agno.models.anthropic", "Claude"),
    "google": ("agno.models.google", "Gemini"),
    "gemini": ("agno.models.google", "Gemini"),  # Alias for backward compatibility
    "groq": ("agno.models.groq", "Groq"),
    "ollama": ("agno.models.ollama", "Ollama"),
    "mistral": ("agno.models.mistral", "MistralChat"),
    "cohere": ("agno.models.cohere", "Cohere"),
    "aws": ("agno.models.aws", "AwsBedrock"),
    "aws-bedrock": ("agno.models.aws", "AwsBedrock"),
    "aws-claude": ("agno.models.aws", "Claude"),
    "azure": ("agno.models.azure", "AzureOpenAI"),
    "azure-openai": ("agno.models.azure", "AzureOpenAI"),
    "azure-ai-foundry": ("agno.models.azure", "AzureAIFoundry"),
    "together": ("agno.models.together", "Together"),
    "meta": ("agno.models.meta", "Llama"),
    "llama": ("agno.models.meta", "Llama"),
    "llama-openai": ("agno.models.meta", "LlamaOpenAI"),
    "cerebras": ("agno.models.cerebras", "Cerebras"),
    "xai": ("agno.models.xai", "xAI"),
    "deepseek": ("agno.models.deepseek", "DeepSeek"),
    "fireworks": ("agno.models.fireworks", "Fireworks"),
    "perplexity": ("agno.models.perplexity", "Perplexity"),
    "openrouter": ("agno.models.openrouter", "OpenRouter"),
    "nvidia": ("agno.models.nvidia", "Nvidia"),
    "sambanova": ("agno.models.sambanova", "SambaNova"),
    "deepinfra": ("agno.models.deepinfra", "DeepInfra"),
    "nebius": ("agno.models.nebius", "Nebius"),
    "internlm": ("agno.models.internlm", "InternLM"),
    "dashscope": ("agno.models.dashscope", "DashScope"),
    "huggingface": ("agno.models.huggingface", "HuggingFace"),
    "ibm": ("agno.models.ibm", "WatsonX"),
    "litellm": ("agno.models.litellm", "LiteLLMChat"),
    "lmstudio": ("agno.models.lmstudio", "LMStudio"),
    "portkey": ("agno.models.portkey", "Portkey"),
    "vllm": ("agno.models.vllm", "VLLM"),
    "vercel": ("agno.models.vercel", "V0"),
    "langdb": ("agno.models.langdb", "LangDB"),
    "aimlapi": ("agno.models.aimlapi", "AIMLAPI"),
}


def parse_model_string(model_string: str) -> tuple[str, str]:
    """Parse model string in format 'provider:model_id' into provider and model_id.
    
    Args:
        model_string: String in format 'provider:model_id'
        
    Returns:
        Tuple of (provider, model_id)
        
    Raises:
        ValueError: If string format is invalid
    """
    if ":" not in model_string:
        raise ValueError(
            f"Model string must be in format 'provider:model_id', got: {model_string}"
        )
    
    parts = model_string.split(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Model string must be in format 'provider:model_id', got: {model_string}"
        )
    
    provider, model_id = parts
    provider = provider.lower().strip()
    model_id = model_id.strip()
    
    if not provider or not model_id:
        raise ValueError(
            f"Both provider and model_id must be non-empty, got: {model_string}"
        )
    
    return provider, model_id


def get_model_from_string(model_string: str) -> Model:
    """Create a model instance from a model string.
    
    Args:
        model_string: String in format 'provider:model_id'
        
    Returns:
        Model instance
        
    Raises:
        ValueError: If provider is not supported or string format is invalid
        ImportError: If required dependencies are not installed
    """
    provider, model_id = parse_model_string(model_string)
    return get_model(model_id, provider)


def get_model(model_id: str, model_provider: str) -> Model:
    """Return the right Agno model instance given a pair of model provider and id.
    
    Args:
        model_id: The model ID to use
        model_provider: The provider name (case-insensitive)
        
    Returns:
        Model instance
        
    Raises:
        ValueError: If provider is not supported
        ImportError: If required dependencies are not installed
    """
    provider_key = model_provider.lower().strip()
    
    if provider_key not in PROVIDER_MODEL_MAP:
        supported_providers = ", ".join(sorted(set(
            key.split("-")[0] for key in PROVIDER_MODEL_MAP.keys()
        )))
        raise ValueError(
            f"Model provider '{model_provider}' not supported. "
            f"Supported providers: {supported_providers}"
        )
    
    module_path, class_name = PROVIDER_MODEL_MAP[provider_key]
    
    try:
        # Dynamic import to avoid loading all dependencies
        import importlib
        module = importlib.import_module(module_path)
        model_class = getattr(module, class_name)
        return model_class(id=model_id)
    except ImportError as e:
        raise ImportError(
            f"Failed to import {class_name} from {module_path}. "
            f"Please install the required dependencies for {model_provider}. "
            f"Original error: {e}"
        ) from e
    except AttributeError as e:
        raise ValueError(
            f"Model class {class_name} not found in {module_path}. "
            f"This might be a configuration error."
        ) from e


def create_model(model: Union[Model, str]) -> Model:
    """Create a model instance from either a Model object or model string.
    
    This is a convenience function that handles both the old object-based syntax
    and the new string-based syntax.
    
    Args:
        model: Either a Model instance or a string in format 'provider:model_id'
        
    Returns:
        Model instance
        
    Examples:
        >>> create_model("openai:gpt-4o")
        >>> create_model(OpenAIChat(id="gpt-4o"))
    """
    if isinstance(model, str):
        return get_model_from_string(model)
    elif isinstance(model, Model):
        return model
    else:
        raise TypeError(
            f"Model must be either a Model instance or a string, got {type(model)}"
        )
