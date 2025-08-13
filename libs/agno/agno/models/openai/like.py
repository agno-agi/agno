from dataclasses import dataclass
from typing import Optional

from agno.models.openai.chat import OpenAIChat


@dataclass
class OpenAILike(OpenAIChat):
    """
    A class for to interact with any provider using the OpenAI API schema.

    Args:
        id (str): The id of the OpenAI model to use. Defaults to "not-provided".
        name (str): The name of the OpenAI model to use. Defaults to "OpenAILike".
        api_key (Optional[str]): The API key to use. Defaults to "not-provided".
    """

    id: str = "not-provided"
    name: str = "OpenAILike"
    api_key: Optional[str] = "not-provided"

    default_role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }
