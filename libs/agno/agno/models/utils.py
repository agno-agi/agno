from agno.models.anthropic.claude import Claude
from agno.models.base import Model
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat


# TODO: add all supported models
def get_model(model_id: str, model_provider: str) -> Model:
    """Return the right Agno model instance given a pair of model provider and id"""
    if model_provider == "openai":
        return OpenAIChat(id=model_id)
    elif model_provider == "anthropic":
        return Claude(id=model_id)
    elif model_provider == "gemini":
        return Gemini(id=model_id)
    else:
        raise ValueError(f"Model provider {model_provider} not supported")
