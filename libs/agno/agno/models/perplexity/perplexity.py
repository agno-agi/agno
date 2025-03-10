from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from pydantic import BaseModel

from agno.models.openai.like import OpenAILike


@dataclass
class Perplexity(OpenAILike):
    """
    A class for using models hosted on Perplexity.

    Attributes:
        id (str): The model id. Defaults to "sonar".
        name (str): The model name. Defaults to "Perplexity".
        provider (str): The provider name. Defaults to "Perplexity: " + id.
        api_key (Optional[str]): The API key. Defaults to None.
        base_url (str): The base URL. Defaults to "https://api.perplexity.ai/chat/completions".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "sonar"
    name: str = "Perplexity"
    provider: str = "Perplexity"

    api_key: Optional[str] = getenv("PERPLEXITY_API_KEY")
    base_url: str = "https://api.perplexity.ai/"
    max_tokens: int = 1024
    top_k: Optional[float] = None

    supports_structured_outputs: bool = True

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params: Dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
        }

        if (
            self.response_format
            and isinstance(self.response_format, type)
            and issubclass(self.response_format, BaseModel)
        ):
            base_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"schema": self.response_format.model_json_schema()},
            }

        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}
        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params
