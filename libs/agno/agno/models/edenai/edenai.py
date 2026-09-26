from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class EdenAI(OpenAILike):
    """
    A class for interacting with the Eden AI API.

    Eden AI exposes an OpenAI-compatible Chat Completions endpoint that routes requests
    to many underlying providers behind a single API key. Models are addressed as
    "<provider>/<model>", e.g. "openai/gpt-5.5" or "mistral/mistral-large-latest".

    Attributes:
        id (str): The id of the model to use. Default is "openai/gpt-5.5".
        name (str): The name of this chat model instance. Default is "EdenAI".
        provider (str): The provider of the model. Default is "EdenAI".
        api_key (str): The api key to authorize requests to Eden AI.
        base_url (str): The base url to which requests are sent. Defaults to "https://api.edenai.run/v3".
    """

    id: str = "openai/gpt-5.5"
    name: str = "EdenAI"
    provider: str = "EdenAI"
    api_key: Optional[str] = None
    base_url: str = "https://api.edenai.run/v3"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for EDENAI_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("EDENAI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="EDENAI_API_KEY not set. Please set the EDENAI_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
