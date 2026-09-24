from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class DaoXE(OpenAILike):
    """
    A class for interacting with models served by the DaoXE gateway.

    DaoXE is an OpenAI-compatible gateway that fronts many upstream models. This
    provider uses the Chat Completions path through ``OpenAILike``. Model IDs are
    scoped to your account catalog, so list ``GET /v1/models`` (or set
    ``DAOXE_MODEL``) to pick one instead of assuming the default is enabled.

    Attributes:
        id (str): The model id. Defaults to ``DAOXE_MODEL`` env, else ``"gpt-5.5"``.
        name (str): The model name. Defaults to "DaoXE".
        provider (str): The provider name. Defaults to "DaoXE".
        api_key (Optional[str]): The API key. Defaults to ``DAOXE_API_KEY`` env.
        base_url (str): The base URL. Defaults to "https://daoxe.com/v1".
    """

    id: str = field(default_factory=lambda: getenv("DAOXE_MODEL") or "gpt-5.5")
    name: str = "DaoXE"
    provider: str = "DaoXE"

    api_key: Optional[str] = field(default_factory=lambda: getenv("DAOXE_API_KEY"))
    base_url: str = "https://daoxe.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for DAOXE_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("DAOXE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="DAOXE_API_KEY not set. Please set the DAOXE_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
