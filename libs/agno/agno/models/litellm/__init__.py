from agno.models.litellm.chat import LiteLLM


try:
    from agno.models.litellm.responses import LiteLLMResponses
    from agno.models.litellm.litellm_openai import LiteLLMOpenAI, LiteLLMOpenResponses
except ImportError:
    class LiteLLMResponses:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

    class LiteLLMOpenAI:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

    class LiteLLMOpenResponses:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install using `pip install openai`")


__all__ = [
    "LiteLLM",
    "LiteLLMResponses",
    "LiteLLMOpenAI",
    "LiteLLMOpenResponses",
]
