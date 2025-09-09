from agno.models.base import Model


# TODO: add all supported models
def get_model(model_id: str, model_provider: str) -> Model:
    """Return the right Agno model instance given a pair of model provider and id"""
    if model_provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id)
    elif model_provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id)
    elif model_provider == "gemini":
        from agno.models.google import Gemini

        return Gemini(id=model_id)
    else:
        raise ValueError(f"Model provider {model_provider} not supported")
