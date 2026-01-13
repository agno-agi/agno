from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Siliconflow(OpenAILike):
    """
    A class for interacting with Siliconflow API.

    Attributes:
        id (str): The id of the Siliconflow model to use. Default is "Qwen/QwQ-32B".
        name (str): The name of this chat model instance. Default is "Siliconflow".
        provider (str): The provider of the model. Default is "Siliconflow".
        api_key (str): The api key to authorize request to Siliconflow.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.siliconflow.cn/v1".
    """

    id: str = "Qwen/QwQ-32B"
    name: str = "Siliconflow"
    provider: str = "Siliconflow"
    api_key: Optional[str] = None
    base_url: str = "https://api.siliconflow.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for SILICONFLOW_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("SILICONFLOW_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="SILICONFLOW_API_KEY not set. Please set the SILICONFLOW_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
