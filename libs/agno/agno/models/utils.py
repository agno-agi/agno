from typing import Optional, Union

from agno.models.base import Model


def parse_model_string(model_string: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse model string into provider and model_id components."""
    if not model_string or ":" not in model_string:
        return None, None
    parts = model_string.split(":", 1)
    return parts[0], parts[1]


def get_model_from_string(model: Union[Model, str]) -> Model:
    """Create a model instance from either a Model object or model string."""
    if isinstance(model, Model):
        return model

    if isinstance(model, str):
        if ":" not in model:
            raise ValueError(f"Model string must be 'provider:model_id', got: {model}")

        provider, model_id = model.split(":", 1)
        provider = provider.lower().strip()
        model_id = model_id.strip()

        if not provider or not model_id:
            raise ValueError(f"Both provider and model_id must be non-empty, got: {model}")

        try:
            if provider == "openai":
                from agno.models.openai import OpenAIChat

                return OpenAIChat(id=model_id)
            elif provider == "openai-responses":
                from agno.models.openai import OpenAIResponses

                return OpenAIResponses(id=model_id)
            elif provider == "anthropic":
                from agno.models.anthropic import Claude

                return Claude(id=model_id)
            elif provider == "google":
                from agno.models.google import Gemini

                return Gemini(id=model_id)
            elif provider == "groq":
                from agno.models.groq import Groq

                return Groq(id=model_id)
            elif provider == "ollama":
                from agno.models.ollama import Ollama

                return Ollama(id=model_id)
            elif provider == "aws":
                from agno.models.aws import AwsBedrock

                return AwsBedrock(id=model_id)
            elif provider == "aws-claude":
                from agno.models.aws import Claude as AWSClaude

                return AWSClaude(id=model_id)
            elif provider == "azure":
                from agno.models.azure import AzureOpenAI

                return AzureOpenAI(id=model_id)
            elif provider == "azure-ai-foundry":
                from agno.models.azure import AzureAIFoundry

                return AzureAIFoundry(id=model_id)
            elif provider == "mistral":
                from agno.models.mistral import MistralChat

                return MistralChat(id=model_id)
            elif provider == "cohere":
                from agno.models.cohere import Cohere

                return Cohere(id=model_id)
            elif provider == "together":
                from agno.models.together import Together

                return Together(id=model_id)
            elif provider == "fireworks":
                from agno.models.fireworks import Fireworks

                return Fireworks(id=model_id)
            elif provider == "perplexity":
                from agno.models.perplexity import Perplexity

                return Perplexity(id=model_id)
            elif provider == "openrouter":
                from agno.models.openrouter import OpenRouter

                return OpenRouter(id=model_id)
            elif provider == "llama":
                from agno.models.meta import Llama

                return Llama(id=model_id)
            elif provider == "llama-openai":
                from agno.models.meta import LlamaOpenAI

                return LlamaOpenAI(id=model_id)
            elif provider == "cerebras":
                from agno.models.cerebras import Cerebras

                return Cerebras(id=model_id)
            elif provider == "cerebras-openai":
                from agno.models.cerebras import CerebrasOpenAI

                return CerebrasOpenAI(id=model_id)
            elif provider == "cometapi":
                from agno.models.cometapi import CometAPI

                return CometAPI(id=model_id)
            elif provider == "xai":
                from agno.models.xai import xAI

                return xAI(id=model_id)
            elif provider == "deepseek":
                from agno.models.deepseek import DeepSeek

                return DeepSeek(id=model_id)
            elif provider == "nvidia":
                from agno.models.nvidia import Nvidia

                return Nvidia(id=model_id)
            elif provider == "sambanova":
                from agno.models.sambanova import Sambanova

                return Sambanova(id=model_id)
            elif provider == "deepinfra":
                from agno.models.deepinfra import DeepInfra

                return DeepInfra(id=model_id)
            elif provider == "nebius":
                from agno.models.nebius import Nebius

                return Nebius(id=model_id)
            elif provider == "nexus":
                from agno.models.nexus import Nexus

                return Nexus(id=model_id)
            elif provider == "internlm":
                from agno.models.internlm import InternLM

                return InternLM(id=model_id)
            elif provider == "dashscope":
                from agno.models.dashscope import DashScope

                return DashScope(id=model_id)
            elif provider == "huggingface":
                from agno.models.huggingface import HuggingFace

                return HuggingFace(id=model_id)
            elif provider == "ibm":
                from agno.models.ibm import WatsonX

                return WatsonX(id=model_id)
            elif provider == "litellm":
                from agno.models.litellm import LiteLLM

                return LiteLLM(id=model_id)
            elif provider == "litellm-openai":
                from agno.models.litellm import LiteLLMOpenAI

                return LiteLLMOpenAI(id=model_id)
            elif provider == "llama-cpp":
                from agno.models.llama_cpp import LlamaCpp

                return LlamaCpp(id=model_id)
            elif provider == "lmstudio":
                from agno.models.lmstudio import LMStudio

                return LMStudio(id=model_id)
            elif provider == "portkey":
                from agno.models.portkey import Portkey

                return Portkey(id=model_id)
            elif provider == "requesty":
                from agno.models.requesty import Requesty

                return Requesty(id=model_id)
            elif provider == "siliconflow":
                from agno.models.siliconflow import Siliconflow

                return Siliconflow(id=model_id)
            elif provider == "vllm":
                from agno.models.vllm import VLLM

                return VLLM(id=model_id)
            elif provider == "vercel":
                from agno.models.vercel import V0

                return V0(id=model_id)
            elif provider == "vertexai":
                from agno.models.vertexai import Claude as VertexAIClaude

                return VertexAIClaude(id=model_id)
            elif provider == "langdb":
                from agno.models.langdb import LangDB

                return LangDB(id=model_id)
            elif provider == "aimlapi":
                from agno.models.aimlapi import AIMLAPI

                return AIMLAPI(id=model_id)
            else:
                raise ValueError(f"Provider '{provider}' not supported")
        except ImportError as e:
            raise ImportError(f"Install dependencies for {provider}: {e}") from e

    raise TypeError(f"Model must be Model instance or string, got {type(model)}")
