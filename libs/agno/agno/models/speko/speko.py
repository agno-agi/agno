from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Speko(OpenAILike):
    """
    A class for interacting with LLMs via the Speko voice router.

    Speko exposes an OpenAI-compatible chat completions endpoint that routes
    model="auto" requests to the best available provider by live benchmarks,
    or passes pinned "provider:model" IDs (e.g. "openai:gpt-4.1-mini") through
    to that provider. Available models: GET https://api.speko.ai/v1/models

    Attributes:
        id (str): The id of the model to use. Default is "auto" (benchmark-routed).
        name (str): The name of this chat model instance. Default is "Speko".
        provider (str): The provider of the model. Default is "Speko".
        api_key (str): The api key to authorize request to Speko.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.speko.ai/v1".
    """

    id: str = "auto"
    name: str = "Speko"
    provider: str = "Speko"
    api_key: Optional[str] = None
    base_url: str = "https://api.speko.ai/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for SPEKO_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("SPEKO_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="SPEKO_API_KEY not set. Please set the SPEKO_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
