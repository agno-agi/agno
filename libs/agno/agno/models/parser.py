"""
Model string parser for converting 'provider:id' strings to model instances.

Supports the syntax: Agent(model="openai:gpt-4o") which is equivalent to Agent(model=OpenAIChat(id="gpt-4o"))
"""

from typing import Dict, Type, Union, Optional
from agno.models.base import Model


# Provider name to model class mapping
MODEL_MAPPING: Dict[str, Type[Model]] = {}


def register_model_mapping():
    """Register all available model classes to their provider names."""
    # Import all model classes
    try:
        from agno.models.openai.chat import OpenAIChat
        MODEL_MAPPING["openai"] = OpenAIChat
    except ImportError:
        pass

    try:
        from agno.models.anthropic.claude import Claude
        MODEL_MAPPING["anthropic"] = Claude
    except ImportError:
        pass

    try:
        from agno.models.azure.openai_chat import AzureOpenAI
        MODEL_MAPPING["azure_openai"] = AzureOpenAI
    except ImportError:
        pass

    try:
        from agno.models.meta.llama_openai import LlamaOpenAI
        MODEL_MAPPING["llama"] = LlamaOpenAI
        MODEL_MAPPING["meta"] = LlamaOpenAI
    except ImportError:
        pass

    try:
        from agno.models.google.gemini import Gemini
        MODEL_MAPPING["google"] = Gemini
        MODEL_MAPPING["gemini"] = Gemini
    except ImportError:
        pass

    try:
        from agno.models.cohere.chat import Cohere
        MODEL_MAPPING["cohere"] = Cohere
    except ImportError:
        pass

    try:
        from agno.models.groq.groq import Groq
        MODEL_MAPPING["groq"] = Groq
    except ImportError:
        pass

    try:
        from agno.models.mistral.mistral import Mistral
        MODEL_MAPPING["mistral"] = Mistral
    except ImportError:
        pass

    try:
        from agno.models.cerebras.cerebras import Cerebras
        MODEL_MAPPING["cerebras"] = Cerebras
    except ImportError:
        pass

    try:
        from agno.models.xai.xai import xAI
        MODEL_MAPPING["xai"] = xAI
    except ImportError:
        pass

    try:
        from agno.models.perplexity.perplexity import Perplexity
        MODEL_MAPPING["perplexity"] = Perplexity
    except ImportError:
        pass

    try:
        from agno.models.ollama.chat import Ollama
        MODEL_MAPPING["ollama"] = Ollama
    except ImportError:
        pass

    try:
        from agno.models.huggingface.huggingface import HuggingFace
        MODEL_MAPPING["huggingface"] = HuggingFace
        MODEL_MAPPING["hf"] = HuggingFace
    except ImportError:
        pass

    try:
        from agno.models.together.together import Together
        MODEL_MAPPING["together"] = Together
    except ImportError:
        pass

    try:
        from agno.models.fireworks.fireworks import Fireworks
        MODEL_MAPPING["fireworks"] = Fireworks
    except ImportError:
        pass

    try:
        from agno.models.deepseek.deepseek import DeepSeek
        MODEL_MAPPING["deepseek"] = DeepSeek
    except ImportError:
        pass

    try:
        from agno.models.deepinfra.deepinfra import DeepInfra
        MODEL_MAPPING["deepinfra"] = DeepInfra
    except ImportError:
        pass

    try:
        from agno.models.sambanova.sambanova import SambaNova
        MODEL_MAPPING["sambanova"] = SambaNova
    except ImportError:
        pass

    try:
        from agno.models.nvidia.nvidia import Nvidia
        MODEL_MAPPING["nvidia"] = Nvidia
    except ImportError:
        pass

    try:
        from agno.models.portkey.portkey import Portkey
        MODEL_MAPPING["portkey"] = Portkey
    except ImportError:
        pass

    try:
        from agno.models.openrouter.openrouter import OpenRouter
        MODEL_MAPPING["openrouter"] = OpenRouter
    except ImportError:
        pass

    try:
        from agno.models.lmstudio.lmstudio import LMStudio
        MODEL_MAPPING["lmstudio"] = LMStudio
    except ImportError:
        pass

    try:
        from agno.models.vllm.vllm import VLLM
        MODEL_MAPPING["vllm"] = VLLM
    except ImportError:
        pass

    try:
        from agno.models.aws.bedrock import BedrockChat
        MODEL_MAPPING["aws"] = BedrockChat
        MODEL_MAPPING["bedrock"] = BedrockChat
    except ImportError:
        pass

    try:
        from agno.models.aws.claude import AWSClaude
        MODEL_MAPPING["aws_claude"] = AWSClaude
    except ImportError:
        pass

    try:
        from agno.models.litellm.chat import LiteLLM
        MODEL_MAPPING["litellm"] = LiteLLM
    except ImportError:
        pass

    try:
        from agno.models.nebius.nebius import Nebius
        MODEL_MAPPING["nebius"] = Nebius
    except ImportError:
        pass

    try:
        from agno.models.dashscope.dashscope import DashScope
        MODEL_MAPPING["dashscope"] = DashScope
        MODEL_MAPPING["qwen"] = DashScope
    except ImportError:
        pass

    try:
        from agno.models.internlm.internlm import InternLM
        MODEL_MAPPING["internlm"] = InternLM
    except ImportError:
        pass

    try:
        from agno.models.aimlapi.aimlapi import AIMLAPI
        MODEL_MAPPING["aimlapi"] = AIMLAPI
    except ImportError:
        pass

    try:
        from agno.models.ibm.watsonx import WatsonX
        MODEL_MAPPING["watsonx"] = WatsonX
        MODEL_MAPPING["ibm"] = WatsonX
    except ImportError:
        pass

    try:
        from agno.models.langdb.langdb import LangDB
        MODEL_MAPPING["langdb"] = LangDB
    except ImportError:
        pass

    try:
        from agno.models.vercel.v0 import V0
        MODEL_MAPPING["vercel"] = V0
        MODEL_MAPPING["v0"] = V0
    except ImportError:
        pass

    try:
        from agno.models.cerebras.cerebras_openai import CerebrasOpenAI
        MODEL_MAPPING["cerebras_openai"] = CerebrasOpenAI
    except ImportError:
        pass


def parse_model_string(model_str: str) -> Model:
    """
    Parse a model string in the format 'provider:id' and return a model instance.
    
    Args:
        model_str: String in format 'provider:id' (e.g., 'openai:gpt-4o', 'anthropic:claude-3-sonnet')
        
    Returns:
        Model: Instantiated model with the specified id
    """
    if ":" not in model_str:
        raise ValueError(
            f"Invalid model string format: '{model_str}'. Expected format: 'provider:id' "
            f"(e.g., 'openai:gpt-4o', 'anthropic:claude-3-sonnet')"
        )
    
    # Ensure mapping is registered
    if not MODEL_MAPPING:
        register_model_mapping()
    
    provider, model_id = model_str.split(":", 1)
    provider = provider.lower().strip()
    model_id = model_id.strip()
    
    if not provider or not model_id:
        raise ValueError(
            f"Invalid model string format: '{model_str}'. Both provider and id must be non-empty"
        )
    
    if provider not in MODEL_MAPPING:
        available_providers = sorted(MODEL_MAPPING.keys())
        raise ValueError(
            f"Unknown model provider: '{provider}'. Available providers: {', '.join(available_providers)}"
        )
    
    model_class = MODEL_MAPPING[provider]
    
    try:
        return model_class(id=model_id)
    except Exception as e:
        raise ValueError(f"Failed to instantiate {provider} model with id '{model_id}': {e}")


def get_model_string(model: Model) -> str:
    """
    Convert a model instance to its string representation.
    
    Args:
        model: Model instance
        
    Returns:
        str: String in format 'provider:id'
    """
    # Ensure mapping is registered
    if not MODEL_MAPPING:
        register_model_mapping()
    
    # Find the provider name for this model class
    model_class = model.__class__
    
    # First try direct class match
    for provider, cls in MODEL_MAPPING.items():
        if cls == model_class:
            return f"{provider}:{model.id}"
    
    # If no direct match, try using the model's provider attribute
    if hasattr(model, 'provider') and model.provider:
        provider_lower = model.provider.lower()
        # Try to find a matching provider in our mapping
        for mapped_provider in MODEL_MAPPING.keys():
            if mapped_provider in provider_lower or provider_lower in mapped_provider:
                return f"{mapped_provider}:{model.id}"
    
    # Fallback: use class name lowercased
    class_name = model_class.__name__.lower()
    # Try to match against known providers
    for provider in MODEL_MAPPING.keys():
        if provider in class_name or class_name.startswith(provider):
            return f"{provider}:{model.id}"
    
    # Final fallback: use the class name
    return f"{class_name}:{model.id}"


def resolve_model(model: Union[str, Model, None]) -> Optional[Model]:
    """
    Resolve a model specification to a Model instance.
    
    Args:
        model: Either a model string (e.g., 'openai:gpt-4o'), a Model instance, or None
        
    Returns:
        Model: The resolved Model instance, or None if input is None
    """
    if model is None:
        return None
    elif isinstance(model, str):
        return parse_model_string(model)
    elif isinstance(model, Model):
        return model
    else:
        raise ValueError(f"Invalid model type: {type(model)}. Expected str, Model instance, or None")


# Register model mapping on module import
register_model_mapping()
