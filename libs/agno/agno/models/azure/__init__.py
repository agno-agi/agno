try:
    from agno.models.azure.ai_foundry import AzureAIFoundry
except ImportError:

    class AzureAIFoundry:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "`azure-ai-inference` not installed. Please install it via `pip install azure-ai-inference aiohttp`"
            )


try:
    from agno.models.azure.openai_chat import AzureOpenAI
except ImportError:

    class AzureOpenAI:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install it via `pip install openai`")
