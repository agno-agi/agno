from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class FuturMix(OpenAILike):
    """
    A class for interacting with FuturMix API.

    Attributes:
        id (str): The id of the FuturMix model to use. Default is "claude-sonnet-4-20250514".
        name (str): The name of this chat model instance. Default is "FuturMix".
        provider (str): The provider of the model. Default is "FuturMix".
        api_key (str): The api key to authorize request to FuturMix.
        base_url (str): The base url to which the requests are sent. Defaults to "https://futurmix.ai/v1".
    """

    id: str = "claude-sonnet-4-20250514"
    name: str = "FuturMix"
    provider: str = "FuturMix"
    api_key: Optional[str] = None
    base_url: str = "https://futurmix.ai/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for FUTURMIX_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("FUTURMIX_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="FUTURMIX_API_KEY not set. Please set the FUTURMIX_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
