from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class YAPI(OpenAILike):
    """
    A class for interacting with Y-API, an OpenAI-compatible gateway that serves
    models from several vendors behind a single endpoint.

    Attributes:
        id (str): The id of the Y-API model to use. Default is "deepseek/deepseek-v4-flash".
        name (str): The name of this chat model instance. Default is "YAPI".
        provider (str): The provider of the model. Default is "YAPI".
        api_key (str): The api key to authorize request to Y-API.
        base_url (str): The base url to which the requests are sent.
            Defaults to "https://api.y-api.bestvirtualgoods.com/v1".
    """

    id: str = "deepseek/deepseek-v4-flash"
    name: str = "YAPI"
    provider: str = "YAPI"
    api_key: Optional[str] = field(default_factory=lambda: getenv("YAPI_API_KEY"))
    base_url: str = "https://api.y-api.bestvirtualgoods.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for YAPI_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("YAPI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="YAPI_API_KEY not set. Please set the YAPI_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
