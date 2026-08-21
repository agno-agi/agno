from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Kenari(OpenAILike):
    """
    A class for using models hosted on Kenari.

    Attributes:
        id (str): The model id. Defaults to "claude-sonnet-5".
        name (str): The model name. Defaults to "Kenari".
        provider (str): The provider name. Defaults to "Kenari".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://kenari.id/v1".
    """

    id: str = "claude-sonnet-5"
    name: str = "Kenari"
    provider: str = "Kenari"

    api_key: Optional[str] = field(default_factory=lambda: getenv("KENARI_API_KEY"))
    base_url: str = "https://kenari.id/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("KENARI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="KENARI_API_KEY not set. Please set the KENARI_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()
