from dataclasses import dataclass
from typing import Optional

from agno.models.base import Model
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

    # OpenAI-compatible servers that emit usage on every streaming chunk do so
    # cumulatively (e.g. vLLM with --enable-force-include-usage), so only
    # collect metrics on the final chunk. Servers that send usage only on the
    # last chunk are unaffected.
    collect_metrics_on_completion: bool = True

    default_role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }

    def get_provider(self) -> str:
        return Model.get_provider(self)
