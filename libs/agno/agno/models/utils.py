from typing import Optional, Union

from agno.models.base import Model


def _get_model_class(model_id: str, model_provider: str) -> Model:
    provider = model_provider.lower()

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id)

    elif provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id)

    elif provider in ("gemini", "google"):
        from agno.models.google import Gemini

        return Gemini(id=model_id)

    elif provider == "groq":
        from agno.models.groq import Groq

        return Groq(id=model_id)

    elif provider == "fireworks":
        from agno.models.fireworks import Fireworks

        return Fireworks(id=model_id)

    elif provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(id=model_id)

    elif provider == "together":
        from agno.models.together import Together

        return Together(id=model_id)

    elif provider == "xai":
        from agno.models.xai import xAI

        return xAI(id=model_id)

    elif provider == "ollama":
        from agno.models.ollama import Ollama

        return Ollama(id=model_id)

    elif provider == "litellm":
        from agno.models.litellm import LiteLLM

        return LiteLLM(id=model_id)

    elif provider == "lmstudio":
        from agno.models.lmstudio import LMStudio

        return LMStudio(id=model_id)

    elif provider == "vllm":
        from agno.models.vllm import VLLM

        return VLLM(id=model_id)

    elif provider in ("azure", "azure-openai"):
        from agno.models.azure import AzureOpenAI

        return AzureOpenAI(id=model_id)

    elif provider == "azure-ai-foundry":
        from agno.models.azure import AzureAIFoundry

        return AzureAIFoundry(id=model_id)

    elif provider == "aws-bedrock":
        from agno.models.aws import AwsBedrock

        return AwsBedrock(id=model_id)

    elif provider == "aws-claude":
        from agno.models.aws import Claude as AWSClaude

        return AWSClaude(id=model_id)

    elif provider == "vertexai-claude":
        from agno.models.vertexai.claude import Claude as VertexAIClaude

        return VertexAIClaude(id=model_id)

    elif provider == "nvidia":
        from agno.models.nvidia import Nvidia

        return Nvidia(id=model_id)

    elif provider == "nebius":
        from agno.models.nebius import Nebius

        return Nebius(id=model_id)

    elif provider == "nexus":
        from agno.models.nexus import Nexus

        return Nexus(id=model_id)

    elif provider == "portkey":
        from agno.models.portkey import Portkey

        return Portkey(id=model_id)

    elif provider == "cohere":
        from agno.models.cohere import Cohere

        return Cohere(id=model_id)

    elif provider == "mistral":
        from agno.models.mistral import MistralChat

        return MistralChat(id=model_id)

    elif provider == "meta":
        from agno.models.meta import Llama

        return Llama(id=model_id)

    elif provider == "cerebras":
        from agno.models.cerebras import Cerebras

        return Cerebras(id=model_id)

    elif provider == "dashscope":
        from agno.models.dashscope import DashScope

        return DashScope(id=model_id)

    elif provider == "deepinfra":
        from agno.models.deepinfra import DeepInfra

        return DeepInfra(id=model_id)

    elif provider == "siliconflow":
        from agno.models.siliconflow import Siliconflow

        return Siliconflow(id=model_id)

    elif provider == "sambanova":
        from agno.models.sambanova import Sambanova

        return Sambanova(id=model_id)

    elif provider == "internlm":
        from agno.models.internlm import InternLM

        return InternLM(id=model_id)

    elif provider == "aimlapi":
        from agno.models.aimlapi import AIMLAPI

        return AIMLAPI(id=model_id)

    elif provider == "cometapi":
        from agno.models.cometapi import CometAPI

        return CometAPI(id=model_id)

    elif provider == "requesty":
        from agno.models.requesty import Requesty

        return Requesty(id=model_id)

    elif provider == "perplexity":
        from agno.models.perplexity import Perplexity

        return Perplexity(id=model_id)

    elif provider == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(id=model_id)

    elif provider == "vercel":
        from agno.models.vercel import V0

        return V0(id=model_id)

    elif provider == "huggingface":
        from agno.models.huggingface import HuggingFace

        return HuggingFace(id=model_id)

    elif provider == "ibm":
        from agno.models.ibm import WatsonX

        return WatsonX(id=model_id)

    elif provider == "langdb":
        from agno.models.langdb import LangDB

        return LangDB(id=model_id)

    elif provider == "llama-cpp":
        from agno.models.llama_cpp import LlamaCpp

        return LlamaCpp(id=model_id)

    else:
        raise ValueError(f"Model provider '{model_provider}' is not supported. ")


def _parse_model_string(model_string: str) -> Model:
    if not model_string or not isinstance(model_string, str):
        raise ValueError(f"Model string must be a non-empty string, got: {model_string}")

    if ":" not in model_string:
        raise ValueError(f"Invalid model string format: '{model_string}'")

    parts = model_string.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid model string format: '{model_string}'")

    provider, model_id = parts
    provider = provider.strip()
    model_id = model_id.strip()

    if not provider or not model_id:
        raise ValueError(f"Invalid model string format: '{model_string}'")

    return _get_model_class(model_id, provider)


def get_model(model: Union[Model, str, None]) -> Optional[Model]:
    if model is None:
        return None
    elif isinstance(model, Model):
        return model
    elif isinstance(model, str):
        return _parse_model_string(model)
    else:
        raise TypeError(f"Model must be a Model instance, string, or None. Got: {type(model).__name__}")
