from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Sambanova(OpenAILike):
    """
    A class for interacting with Sambanova API.

    Attributes:
        id (str): The id of the Sambanova model to use. Default is "Meta-Llama-3.1-8B-Instruct".
        name (str): The name of this chat model instance. Default is "Sambanova"
        provider (str): The provider of the model. Default is "Sambanova".
        api_key (str): The api key to authorize request to Sambanova.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.sambanova.ai/v1".
    """

    id: str = "Meta-Llama-3.1-8B-Instruct"
    name: str = "Sambanova"
    provider: str = "Sambanova"

    api_key: Optional[str] = None
    base_url: str = "https://api.sambanova.ai/v1"

    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for SAMBANOVA_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("SAMBANOVA_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="SAMBANOVA_API_KEY not set. Please set the SAMBANOVA_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
