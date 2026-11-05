from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Heabsy(OpenAILike):
    """
    A class for interacting with Heabsy, an OpenAI-compatible inference API for open models.

    Attributes:
        id (str): The id of the Heabsy model to use. Default is "qwen38".
        name (str): The name of this chat model instance. Default is "Heabsy".
        provider (str): The provider of the model. Default is "Heabsy".
        api_key (str): The api key to authorize request to Heabsy.
        base_url (str): The base url to which the requests are sent.
            Defaults to "https://api.heabsy.com/v1".
    """

    id: str = "qwen38"
    name: str = "Heabsy"
    provider: str = "Heabsy"
    api_key: Optional[str] = field(default_factory=lambda: getenv("HEABSY_API_KEY"))
    base_url: str = "https://api.heabsy.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for HEABSY_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("HEABSY_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="HEABSY_API_KEY not set. Please set the HEABSY_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
