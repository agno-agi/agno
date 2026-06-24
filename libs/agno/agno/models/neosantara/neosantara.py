from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Neosantara(OpenAILike):
    """
    A class for interacting with Neosantara API.

    Attributes:
        id (str): The id of the Neosantara model to use. Default is "grok-4.1-fast-non-reasoning".
        name (str): The name of this chat model instance. Default is "Neosantara"
        provider (str): The provider of the model. Default is "Neosantara".
        api_key (str): The api key to authorize request to Neosantara.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.neosantara.xyz/v1".
    """

    id: str = "grok-4.1-fast-non-reasoning"
    name: str = "Neosantara"
    provider: str = "Neosantara"
    api_key: Optional[str] = None
    base_url: str = "https://api.neosantara.xyz/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for NEOSANTARA_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("NEOSANTARA_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="NEOSANTARA_API_KEY not set. Please set the NEOSANTARA_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
