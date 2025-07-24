from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat


def get_model_from_id(model_id: str):
    if model_id.startswith("openai:"):
        return OpenAIChat(id=model_id.split("openai:")[1])
    elif model_id.startswith("anthropic:"):
        return Claude(id=model_id.split("anthropic:")[1])
    elif model_id.startswith("google:"):
        return Gemini(id=model_id.split("google:")[1])
    elif model_id.startswith("groq:"):
        return Groq(id=model_id.split("groq:")[1])
    else:
        return OpenAIChat(id="gpt-4o")
