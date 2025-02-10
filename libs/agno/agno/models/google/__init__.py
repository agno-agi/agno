from agno.models.google.gemini import Gemini

try:
    from agno.models.google.gemini_openai import GeminiOpenAI
except ImportError:

    class GeminiOpenAIChat:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("GeminiOpenAI requires the 'openai' library. Please install it via `pip install openai`")
