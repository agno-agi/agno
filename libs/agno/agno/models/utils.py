from typing import Optional, Union

from agno.models.base import Model


def _get_model_class(model_id: str, model_provider: str) -> Model:
    if model_provider == "aimlapi":
        from agno.models.aimlapi import AIMLAPI

        return AIMLAPI(id=model_id)

    elif model_provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id)

    elif model_provider == "aws-bedrock":
        from agno.models.aws import AwsBedrock

        return AwsBedrock(id=model_id)

    elif model_provider == "aws-claude":
        from agno.models.aws import Claude as AWSClaude

        return AWSClaude(id=model_id)

    elif model_provider == "azure-ai-foundry":
        from agno.models.azure import AzureAIFoundry

        return AzureAIFoundry(id=model_id)

    elif model_provider == "azure-openai":
        from agno.models.azure import AzureOpenAI

        return AzureOpenAI(id=model_id)

    elif model_provider == "cerebras":
        from agno.models.cerebras import Cerebras

        return Cerebras(id=model_id)

    elif model_provider == "cerebras-openai":
        from agno.models.cerebras import CerebrasOpenAI

        return CerebrasOpenAI(id=model_id)

    elif model_provider == "cohere":
        from agno.models.cohere import Cohere

        return Cohere(id=model_id)

    elif model_provider == "cometapi":
        from agno.models.cometapi import CometAPI

        return CometAPI(id=model_id)

    elif model_provider == "dashscope":
        from agno.models.dashscope import DashScope

        return DashScope(id=model_id)

    elif model_provider == "deepinfra":
        from agno.models.deepinfra import DeepInfra

        return DeepInfra(id=model_id)

    elif model_provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(id=model_id)

    elif model_provider == "fireworks":
        from agno.models.fireworks import Fireworks

        return Fireworks(id=model_id)

    elif model_provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=model_id)

    elif model_provider == "groq":
        from agno.models.groq import Groq

        return Groq(id=model_id)

    elif model_provider == "huggingface":
        from agno.models.huggingface import HuggingFace

        return HuggingFace(id=model_id)

    elif model_provider == "ibm":
        from agno.models.ibm import WatsonX

        return WatsonX(id=model_id)

    elif model_provider == "internlm":
        from agno.models.internlm import InternLM

        return InternLM(id=model_id)

    elif model_provider == "langdb":
        from agno.models.langdb import LangDB

        return LangDB(id=model_id)

    elif model_provider == "litellm":
        from agno.models.litellm import LiteLLM

        return LiteLLM(id=model_id)

    elif model_provider == "litellm-openai":
        from agno.models.litellm import LiteLLMOpenAI

        return LiteLLMOpenAI(id=model_id)

    elif model_provider == "llama-cpp":
        from agno.models.llama_cpp import LlamaCpp

        return LlamaCpp(id=model_id)

    elif model_provider == "llama-openai":
        from agno.models.meta import LlamaOpenAI

        return LlamaOpenAI(id=model_id)

    elif model_provider == "lmstudio":
        from agno.models.lmstudio import LMStudio

        return LMStudio(id=model_id)

    elif model_provider == "meta":
        from agno.models.meta import Llama

        return Llama(id=model_id)

    elif model_provider == "mistral":
        from agno.models.mistral import MistralChat

        return MistralChat(id=model_id)

    elif model_provider == "moonshot":
        from agno.models.moonshot import MoonShot

        return MoonShot(id=model_id)

    elif model_provider == "nebius":
        from agno.models.nebius import Nebius

        return Nebius(id=model_id)

    elif model_provider == "neosantara":
        from agno.models.neosantara import Neosantara

        return Neosantara(id=model_id)

    elif model_provider == "nexus":
        from agno.models.nexus import Nexus

        return Nexus(id=model_id)

    elif model_provider == "nvidia":
        from agno.models.nvidia import Nvidia

        return Nvidia(id=model_id)

    elif model_provider == "ollama":
        from agno.models.ollama import Ollama

        return Ollama(id=model_id)

    elif model_provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id)

    elif model_provider == "openai-responses":
        from agno.models.openai import OpenAIResponses

        return OpenAIResponses(id=model_id)

    elif model_provider == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(id=model_id)

    elif model_provider == "perplexity":
        from agno.models.perplexity import Perplexity

        return Perplexity(id=model_id)

    elif model_provider == "portkey":
        from agno.models.portkey import Portkey

        return Portkey(id=model_id)

    elif model_provider == "requesty":
        from agno.models.requesty import Requesty

        return Requesty(id=model_id)

    elif model_provider == "sambanova":
        from agno.models.sambanova import Sambanova

        return Sambanova(id=model_id)

    elif model_provider == "siliconflow":
        from agno.models.siliconflow import Siliconflow

        return Siliconflow(id=model_id)

    elif model_provider == "together":
        from agno.models.together import Together

        return Together(id=model_id)

    elif model_provider == "vercel":
        from agno.models.vercel import V0

        return V0(id=model_id)

    elif model_provider == "vertexai-claude":
        from agno.models.vertexai.claude import Claude as VertexAIClaude

        return VertexAIClaude(id=model_id)

    elif model_provider == "vllm":
        from agno.models.vllm import VLLM

        return VLLM(id=model_id)

    elif model_provider == "xai":
        from agno.models.xai import xAI

        return xAI(id=model_id)

    else:
        raise ValueError(f"Model provider '{model_provider}' is not supported.")


# Mapping from runtime model provider names (as stored in Model.provider) to the
# canonical lowercase keys accepted by _get_model_class().  This ensures that
# model strings serialised from live model instances (e.g. by AgentOS / Studio)
# can be safely parsed back with get_model() / _parse_model_string() — i.e. the
# round-trip "model_instance → provider:id string → model_instance" always works.
#
# Keys are the lowercased runtime provider value; values are the canonical key.
_PROVIDER_ALIAS_MAP: dict = {
    # OpenAI family
    "openai": "openai",
    "openairesponses": "openai-responses",
    "openresponses": "openai-responses",
    # Azure family
    "azure": "azure-openai",
    "azureopenai": "azure-openai",
    "azureaifoundry": "azure-ai-foundry",
    # AWS
    "awsbedrock": "aws-bedrock",
    "awsclaude": "aws-claude",
    # Google / VertexAI
    "vertexai": "vertexai-google",
    # Llama / Meta
    "llamacpp": "llama-cpp",
    "llamaopenai": "llama-openai",
    "llama": "meta",
    # Cerebras
    "cerebrasopenai": "cerebras-openai",
    # LiteLLM
    "litellmopenai": "litellm-openai",
    # Misc pass-through – lowercased names already match canonical keys;
    # these entries are listed explicitly for documentation purposes.
    "anthropic": "anthropic",
    "google": "google",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere",
    "deepseek": "deepseek",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "perplexity": "perplexity",
    "huggingface": "huggingface",
    "fireworks": "fireworks",
    "together": "together",
    "nebius": "nebius",
    "nvidia": "nvidia",
    "deepinfra": "deepinfra",
    "ibm": "ibm",
    "internlm": "internlm",
    "siliconflow": "siliconflow",
    "sambanova": "sambanova",
    "aimlapi": "aimlapi",
    "lmstudio": "lmstudio",
    "langdb": "langdb",
    "portkey": "portkey",
    "requesty": "requesty",
    "moonshot": "moonshot",
    "xai": "xai",
    "vllm": "vllm",
    "vercel": "vercel",
    "litellm": "litellm",
    "nexus": "nexus",
    "dashscope": "dashscope",
    "neosantara": "neosantara",
    "n1n": "n1n",
    "cerebras": "cerebras",
}


def _normalize_provider(provider: str) -> str:
    """Normalise a provider string to the canonical key used by ``_get_model_class``.

    Accepts both runtime provider values (e.g. ``"OpenAI"``, ``"Azure"``,
    ``"LMStudio"``) and already-canonical keys (e.g. ``"openai"``,
    ``"azure-openai"``, ``"lmstudio"``).  Unknown values are returned lowercased
    so that newly-added providers continue to work without updating this helper.
    """
    lowered = provider.strip().lower()
    # Strip hyphens for alias map lookup so that canonical keys like
    # "azure-openai" also resolve correctly.
    normalized = _PROVIDER_ALIAS_MAP.get(lowered, None)
    if normalized is None:
        # Fall back: try with hyphens stripped (canonical keys already use hyphens
        # so we preserve them when they exist in the map; otherwise just use the
        # lowercased value as-is).
        normalized = lowered
    return normalized


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
    model_provider = _normalize_provider(model_provider)
    model_id = model_id.strip()

    if not model_provider or not model_id:
        raise ValueError(
            f"Invalid model string format: '{model_string}'. Model strings should be in format '<provider>:<model_id>' e.g. 'openai:gpt-4o'"
        )

    return _get_model_class(model_id, model_provider)


def get_model(model: Union[Model, str, None]) -> Optional[Model]:
    if model is None:
        return None
    elif isinstance(model, Model):
        return model
    elif isinstance(model, str):
        return _parse_model_string(model)
    else:
        raise ValueError("Model must be a Model instance, string, or None")
