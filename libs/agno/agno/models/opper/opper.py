from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Opper(OpenAILike):
    """
    A class for using models hosted on Opper, an EU-hosted OpenAI-compatible
    gateway that serves models from several vendors behind a single endpoint.

    Model ids are bare pool names, where a pool is every provider serving that
    model and Opper picks the route per request. A "provider/model" id such as
    "azure/gpt-5.5" pins one provider or region instead.

    Attributes:
        id (str): The model id. Defaults to "claude-sonnet-4-6".
        name (str): The name of this chat model instance. Defaults to "Opper".
        provider (str): The provider name. Defaults to "Opper".
        api_key (Optional[str]): The API key to authorize requests to Opper.
        base_url (str): The base URL. Defaults to "https://api.opper.ai/v3/compat".
    """

    id: str = "claude-sonnet-4-6"
    name: str = "Opper"
    provider: str = "Opper"

    api_key: Optional[str] = field(default_factory=lambda: getenv("OPPER_API_KEY"))
    base_url: str = "https://api.opper.ai/v3/compat"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for OPPER_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("OPPER_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="OPPER_API_KEY not set. Please set the OPPER_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
