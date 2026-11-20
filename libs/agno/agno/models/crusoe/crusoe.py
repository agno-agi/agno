from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Crusoe(OpenAILike):
    """
    A class for interacting with Crusoe Managed Inference, an OpenAI-compatible endpoint
    serving open-weight models.

    Attributes:
        id (str): The id of the Crusoe model to use. Default is "openai/gpt-oss-120b".
        name (str): The name of this chat model instance. Default is "Crusoe".
        provider (str): The provider of the model. Default is "Crusoe".
        api_key (str): The api key to authorize request to Crusoe.
        base_url (str): The base url for requests. Defaults to "https://api.inference.crusoecloud.com/v1".
    """

    id: str = "openai/gpt-oss-120b"
    name: str = "Crusoe"
    provider: str = "Crusoe"
    api_key: Optional[str] = field(default_factory=lambda: getenv("CRUSOE_API_KEY"))
    base_url: str = "https://api.inference.crusoecloud.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for CRUSOE_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("CRUSOE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="CRUSOE_API_KEY not set. Please set the CRUSOE_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
