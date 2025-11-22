"""
Model context window limits database.

Comprehensive database of context window sizes for various LLM models.
Used for token budget management, auto-trimming, and compression decisions.
"""

from typing import Optional

# Model context window limits (in tokens)
# Source: Official provider documentation
MODEL_CONTEXT_LIMITS = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4-turbo-preview": 128000,
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-3.5-turbo": 16385,
    "gpt-3.5-turbo-16k": 16385,
    "o1-preview": 200000,
    "o1-mini": 200000,
    "o1": 200000,
    "o3-mini": 200000,
    
    # Anthropic
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-2.1": 200000,
    "claude-2": 100000,
    "claude-instant-1": 100000,
    
    # Google
    "gemini-1.5-pro": 2000000,
    "gemini-1.5-flash": 1000000,
    "gemini-1.0-pro": 32760,
    "gemini-2.0-flash": 1000000,
    "gemini-exp": 2000000,
    
    # Cohere
    "command-r-plus": 128000,
    "command-r": 128000,
    "command": 4096,
    "command-light": 4096,
    
    # Mistral
    "mistral-large": 128000,
    "mistral-medium": 32000,
    "mistral-small": 32000,
    "mistral-tiny": 32000,
    "mixtral-8x7b": 32000,
    "mixtral-8x22b": 64000,
    
    # Meta Llama
    "llama-3.3-70b": 128000,
    "llama-3.1-405b": 128000,
    "llama-3.1-70b": 128000,
    "llama-3.1-8b": 128000,
    "llama-3-70b": 8192,
    "llama-3-8b": 8192,
    "llama-2-70b": 4096,
    "llama-2-13b": 4096,
    "llama-2-7b": 4096,
    
    # DeepSeek
    "deepseek-v3": 64000,
    "deepseek-coder": 16000,
    
    # xAI
    "grok-beta": 131072,
    "grok-2": 131072,
    "grok-1": 8192,
    
    # Alibaba Qwen
    "qwen-2.5-72b": 32768,
    "qwen-2.5-32b": 32768,
    "qwen-2-72b": 32768,
    
    # IBM WatsonX
    "ibm/granite": 8192,
    
    # Groq (OpenAI-compatible models)
    "groq/llama-3.1-70b": 128000,
    "groq/llama-3.1-8b": 128000,
    "groq/mixtral-8x7b": 32000,
    
    # Cerebras (OpenAI-compatible)
    "cerebras/llama-3.1-70b": 128000,
    "cerebras/llama-3.1-8b": 128000,
    
    # Together (OpenAI-compatible)
    "together/llama-3.1-405b": 128000,
    "together/llama-3.1-70b": 128000,
    
    # Fireworks (OpenAI-compatible)
    "fireworks/llama-3.1-405b": 128000,
    "fireworks/llama-3.1-70b": 128000,
    
    # Perplexity
    "perplexity/llama-3.1-70b": 128000,
}


def get_context_limit(model_id: str, provider: Optional[str] = None) -> Optional[int]:
    """
    Get context window limit for a model.
    
    Uses fuzzy matching to handle model version suffixes
    (e.g., "gpt-4o-2024-05-13" matches "gpt-4o")
    
    Args:
        model_id: Model identifier
        provider: Optional provider name for disambiguation
    
    Returns:
        Context limit in tokens, or None if unknown
    
    Examples:
        >>> get_context_limit("gpt-4o")
        128000
        >>> get_context_limit("gpt-4o-2024-05-13")
        128000
        >>> get_context_limit("claude-3-5-sonnet-20241022")
        200000
    """
    # Exact match first
    if model_id in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model_id]
    
    # Fuzzy match (handle version suffixes)
    # e.g., "gpt-4o-2024-05-13" → "gpt-4o"
    for key in MODEL_CONTEXT_LIMITS:
        if model_id.startswith(key):
            return MODEL_CONTEXT_LIMITS[key]
    
    # Provider-specific fuzzy matching with provider prefix
    if provider:
        provider_key = f"{provider}/{model_id}"
        if provider_key in MODEL_CONTEXT_LIMITS:
            return MODEL_CONTEXT_LIMITS[provider_key]
        
        # Fuzzy match with provider
        for key in MODEL_CONTEXT_LIMITS:
            if key.startswith(f"{provider}/") and model_id.startswith(key.split("/")[1]):
                return MODEL_CONTEXT_LIMITS[key]
    
    # Unknown model
    return None

