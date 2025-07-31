from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat


def get_model_from_id(model_id: str):
    if model_id.startswith("openai:"):
        return OpenAIChat(id=model_id.split("openai:")[1])
    elif model_id.startswith("anthropic:"):
        return Claude(id=model_id.split("anthropic:")[1])
    else:
        return OpenAIChat(id="gpt-4o")
