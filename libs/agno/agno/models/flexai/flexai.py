from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class FlexAI(OpenAILike):
    """
    A class for interacting with the FlexAI Inference API, an OpenAI-compatible endpoint
    serving open-weight models.

    Attributes:
        id (str): The id of the FlexAI model to use. Default is "DeepSeek-V4-Flash-0731".
        name (str): The name of this chat model instance. Default is "FlexAI".
        provider (str): The provider of the model. Default is "FlexAI".
        api_key (str): The api key to authorize request to FlexAI.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.flex.ai/v1".
    """

    id: str = "DeepSeek-V4-Flash-0731"
    name: str = "FlexAI"
    provider: str = "FlexAI"
    api_key: Optional[str] = field(default_factory=lambda: getenv("FLEXAI_API_KEY"))
    base_url: str = "https://api.flex.ai/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for FLEXAI_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("FLEXAI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="FLEXAI_API_KEY not set. Please set the FLEXAI_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
