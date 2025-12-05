from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class V0(OpenAILike):
    """
    Class for interacting with the v0 API.

    Attributes:
        id (str): The ID of the language model. Defaults to "v0-1.0-md".
        name (str): The name of the API. Defaults to "v0".
        provider (str): The provider of the API. Defaults to "v0".
        api_key (Optional[str]): The API key for the v0 API.
        base_url (Optional[str]): The base URL for the v0 API. Defaults to "https://v0.dev/chat/settings/keys".
    """

    id: str = "v0-1.0-md"
    name: str = "v0"
    provider: str = "Vercel"

    api_key: Optional[str] = None
    base_url: str = "https://api.v0.dev/v1/"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for V0_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("V0_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="V0_API_KEY not set. Please set the V0_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
