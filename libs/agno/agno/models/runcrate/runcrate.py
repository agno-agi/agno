from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Runcrate(OpenAILike):
    """
    A class for interacting with Runcrate models.

    Attributes:
        id (str): The model id. Defaults to "deepseek-ai/DeepSeek-V4.1-Flash".
        name (str): The model name. Defaults to "Runcrate".
        provider (str): The provider name. Defaults to "Runcrate".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.runcrate.com/v1".
    """

    id: str = "deepseek-ai/DeepSeek-V4.1-Flash"
    name: str = "Runcrate"
    provider: str = "Runcrate"

    api_key: Optional[str] = field(default_factory=lambda: getenv("RUNCRATE_API_KEY"))
    base_url: str = "https://api.runcrate.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for RUNCRATE_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("RUNCRATE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="RUNCRATE_API_KEY not set. Please set the RUNCRATE_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
