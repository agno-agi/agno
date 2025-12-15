from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Nvidia(OpenAILike):
    """
    A class for interacting with Nvidia models.

    Attributes:
        id (str): The id of the Nvidia model to use. Default is "nvidia/llama-3.1-nemotron-70b-instruct".
        name (str): The name of this chat model instance. Default is "Nvidia"
        provider (str): The provider of the model. Default is "Nvidia".
        api_key (str): The api key to authorize request to Nvidia.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "meta/llama-3.3-70b-instruct"
    name: str = "Nvidia"
    provider: str = "Nvidia"

    api_key: Optional[str] = None
    base_url: str = "https://integrate.api.nvidia.com/v1"

    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for NVIDIA_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("NVIDIA_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="NVIDIA_API_KEY not set. Please set the NVIDIA_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
