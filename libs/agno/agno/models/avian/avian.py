from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Avian(OpenAILike):
    """
    A class for interacting with Avian models.

    Avian provides an OpenAI-compatible API for accessing frontier LLMs
    including DeepSeek, Kimi, GLM, and MiniMax models.

    Attributes:
        id (str): The model id. Defaults to "deepseek/deepseek-v3.2".
        name (str): The model name. Defaults to "Avian".
        provider (str): The provider name. Defaults to "Avian".
        api_key (Optional[str]): The API key for authenticating with Avian.
        base_url (str): The base URL. Defaults to "https://api.avian.io/v1".
    """

    id: str = "deepseek/deepseek-v3.2"
    name: str = "Avian"
    provider: str = "Avian"
    api_key: Optional[str] = None
    base_url: str = "https://api.avian.io/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for AVIAN_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("AVIAN_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="AVIAN_API_KEY not set. Please set the AVIAN_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
