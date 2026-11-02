from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Otari(OpenAILike):
    """
    A class for interacting with models through Otari, an open-source, OpenAI-compatible LLM gateway.

    The model id is passed to the gateway unchanged: a "provider:model" selector such as
    "openai:gpt-4o", or an alias or routing policy name configured on the gateway.

    Attributes:
        id (str): The model id. Defaults to "openai:gpt-4o".
        name (str): The model name. Defaults to "Otari".
        provider (str): The provider name. Defaults to "Otari".
        api_key (Optional[str]): The Otari API key. Defaults to the OTARI_API_KEY environment variable.
        base_url (str): The gateway base URL. Defaults to the OTARI_BASE_URL environment variable,
            or "https://api.otari.ai/api/v1" when it is not set.
    """

    id: str = "openai:gpt-4o"
    name: str = "Otari"
    provider: str = "Otari"
    api_key: Optional[str] = field(default_factory=lambda: getenv("OTARI_API_KEY"))
    base_url: str = field(default_factory=lambda: getenv("OTARI_BASE_URL", "https://api.otari.ai/api/v1"))

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for OTARI_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("OTARI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="OTARI_API_KEY not set. Please set the OTARI_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
