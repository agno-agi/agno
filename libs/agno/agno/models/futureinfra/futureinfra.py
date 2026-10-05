from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class FutureInfra(OpenAILike):
    """
    A class for interacting with the FutureInfra AI API, an OpenAI-compatible router that serves
    models from several vendors behind a single endpoint.

    Attributes:
        id (str): The id of the FutureInfra model to use. Default is "openai/gpt-4o-mini".
        name (str): The name of this chat model instance. Default is "FutureInfra".
        provider (str): The provider of the model. Default is "FutureInfra".
        api_key (str): The api key to authorize request to FutureInfra.
        base_url (str): The base url to which the requests are sent.
            Defaults to "https://futureinfra.ai/v1/ai".
    """

    id: str = "openai/gpt-4o-mini"
    name: str = "FutureInfra"
    provider: str = "FutureInfra"
    api_key: Optional[str] = field(default_factory=lambda: getenv("FUTUREINFRA_API_KEY"))
    base_url: str = "https://futureinfra.ai/v1/ai"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for FUTUREINFRA_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("FUTUREINFRA_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="FUTUREINFRA_API_KEY not set. Please set the FUTUREINFRA_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
