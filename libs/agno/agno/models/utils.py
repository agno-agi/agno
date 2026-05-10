from typing import Dict, List, Optional, Tuple, Union

from agno.models.base import Model

# Prefix-based sniffing for bare model IDs (no explicit ``<provider>:`` prefix).
#
# Each entry is a (prefix, provider) pair. The first matching prefix wins, so
# keep longer / more specific prefixes above shorter ones that could collide
# (e.g. ``open-mistral-`` above any hypothetical ``open-`` prefix).
#
# Only unambiguous prefixes belong here. Model families hosted on multiple
# providers (Llama on Meta/Bedrock/Vertex, Claude on Anthropic/Bedrock/Vertex)
# are intentionally *not* sniffed: the direct provider is the default for
# Claude because ``claude-*`` IDs are Anthropic's canonical scheme, but users
# on wrapped providers (AWS Bedrock, Azure, Vertex) must still pass a
# pre-constructed ``Model`` or use an explicit ``<provider>:<id>`` string.
_PROVIDER_PREFIXES: List[Tuple[str, str]] = [
    # OpenAI — GPT family
    ("gpt-", "openai"),
    ("chatgpt-", "openai"),
    # Anthropic (direct API; Bedrock/Vertex Claude needs explicit prefix)
    ("claude-", "anthropic"),
    # Google
    ("gemini-", "google"),
    # Mistral family (all variants route to mistral)
    ("open-mistral-", "mistral"),
    ("open-mixtral-", "mistral"),
    ("mistral-", "mistral"),
    ("ministral-", "mistral"),
    ("codestral-", "mistral"),
    ("mixtral-", "mistral"),
    ("pixtral-", "mistral"),
    ("magistral-", "mistral"),
    ("devstral-", "mistral"),
    # DeepSeek
    ("deepseek-", "deepseek"),
    # Cohere Command
    ("command-", "cohere"),
    # xAI Grok
    ("grok-", "xai"),
]

# Exact model IDs (no dash variant) that are unambiguous.
_PROVIDER_EXACT: Dict[str, str] = {
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
}


def _sniff_provider(model_id: str) -> Optional[str]:
    """Infer the provider slug from a bare model ID.

    Returns the provider slug (e.g. ``"openai"``, ``"anthropic"``) if the
    model ID starts with a recognised prefix, otherwise ``None``.

    Only unambiguous prefixes are recognised. Users on wrapped providers
    (Bedrock, Vertex, Azure-*) must still use an explicit ``<provider>:<id>``
    string or pass a pre-constructed ``Model`` instance.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return None
    if model_id in _PROVIDER_EXACT:
        return _PROVIDER_EXACT[model_id]
    # Match against ``o1-``, ``o3-``, ``o4-`` reasoning variants before the
    # generic ``gpt-`` check; these deserve their own slot because ``o`` is
    # otherwise a very ambiguous single-letter prefix.
    for reasoning_prefix in ("o1-", "o3-", "o4-"):
        if model_id.startswith(reasoning_prefix):
            return "openai"
    for prefix, provider in _PROVIDER_PREFIXES:
        if model_id.startswith(prefix):
            return provider
    return None


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

    elif model_provider == "azure-foundry-claude":
        from agno.models.azure import AzureFoundryClaude

        return AzureFoundryClaude(id=model_id)

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


def _parse_model_string(model_string: str) -> Model:
    if not model_string or not isinstance(model_string, str):
        raise ValueError(f"Model string must be a non-empty string, got: {model_string}")

    if ":" not in model_string:
        # Bare model ID — attempt provider sniffing from the prefix.
        sniffed_provider = _sniff_provider(model_string)
        if sniffed_provider is not None:
            return _get_model_class(model_string.strip(), sniffed_provider)
        raise ValueError(
            f"Invalid model string format: '{model_string}'. "
            "Use '<provider>:<model_id>' (e.g. 'openai:gpt-4o', 'anthropic:claude-sonnet-4-5'), "
            "or pass a bare model ID with a recognised prefix "
            "(gpt-*, claude-*, gemini-*, mistral-*, deepseek-*, command-*, grok-*, o1/o3/o4)."
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
