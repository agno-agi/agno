from agno.models.litellm.chat import LiteLLM
from agno.models.litellm.responses import LiteLLMResponses

try:
    from agno.models.litellm.litellm_openai import LiteLLMOpenAI, LiteLLMOpenResponses
except ImportError:

    class LiteLLMOpenAI:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install using `pip install openai`")


__all__ = [
    "LiteLLM",
    "LiteLLMResponses",
    "LiteLLMOpenAI",
    "LiteLLMOpenResponses"
]
