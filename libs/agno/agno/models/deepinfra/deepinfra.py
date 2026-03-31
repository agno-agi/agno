from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class DeepInfra(OpenAILike):
    """
    A class for interacting with DeepInfra models.

    Attributes:
        id (str): The model id. Defaults to "meta-llama/Llama-2-70b-chat-hf".
        name (str): The model name. Defaults to "DeepInfra".
        provider (str): The provider name. Defaults to "DeepInfra".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.deepinfra.com/v1/openai".
    """

    id: str = "meta-llama/Llama-2-70b-chat-hf"
    name: str = "DeepInfra"
    provider: str = "DeepInfra"

    api_key: Optional[str] = field(default_factory=lambda: getenv("DEEPINFRA_API_KEY"))
    base_url: str = "https://api.deepinfra.com/v1/openai"

    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for DEEPINFRA_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("DEEPINFRA_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="DEEPINFRA_API_KEY not set. Please set the DEEPINFRA_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
