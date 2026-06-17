from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Tzafon(OpenAILike):
    """
    A class for interacting with the Tzafon API.

    Attributes:
        id (str): The id of the Tzafon model to use. Default is "tzafon.sm-1".
        name (str): The name of this chat model instance. Default is "Tzafon".
        provider (str): The provider of the model. Default is "Tzafon".
        api_key (str): The api key to authorize requests to Tzafon.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.tzafon.ai/v1".
    """

    id: str = "tzafon.sm-1"
    name: str = "Tzafon"
    provider: str = "Tzafon"
    api_key: Optional[str] = None
    base_url: str = "https://api.tzafon.ai/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for TZAFON_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("TZAFON_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="TZAFON_API_KEY not set. Please set the TZAFON_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
