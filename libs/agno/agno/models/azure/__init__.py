from agno.models.azure.ai_foundry import AzureAIFoundry

try:
    from agno.models.azure.openai_chat import AzureOpenAI
except ImportError:

    class AzureOpenAI:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install it via `pip install openai`")


__all__ = [
    "AzureAIFoundry",
    "AzureOpenAI",
]
