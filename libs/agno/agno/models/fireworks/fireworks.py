from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai import OpenAILike


@dataclass
class Fireworks(OpenAILike):
    """
    A class for interacting with models hosted on Fireworks.

    Attributes:
        id (str): The model name to use. Defaults to "accounts/fireworks/models/llama-v3p1-405b-instruct".
        name (str): The model name to use. Defaults to "Fireworks".
        provider (str): The provider to use. Defaults to "Fireworks".
        api_key (Optional[str]): The API key to use.
        base_url (str): The base URL to use. Defaults to "https://api.fireworks.ai/inference/v1".
    """

    id: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"
    name: str = "Fireworks"
    provider: str = "Fireworks"

    api_key: Optional[str] = field(default_factory=lambda: getenv("FIREWORKS_API_KEY"))
    base_url: str = "https://api.fireworks.ai/inference/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for FIREWORKS_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("FIREWORKS_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="FIREWORKS_API_KEY not set. Please set the FIREWORKS_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
