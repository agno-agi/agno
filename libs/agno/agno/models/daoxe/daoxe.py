from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class DaoXE(OpenAILike):
    """
    Multi-model multi-protocol gateway via OpenAI-compatible Chat Completions.

    DaoXE exposes Chat Completions at ``https://daoxe.com/v1``. Use an API key from
    the DaoXE dashboard and an exact model ID from your account catalog
    (``GET /v1/models``). Do not hardcode a public model price list.

    DaoXE also exposes OpenAI Responses and Anthropic Messages for other clients;
    this provider uses the Chat Completions path through ``OpenAILike``.

    Not available in mainland China.

    Attributes:
        id (str): Exact account model ID. Defaults to ``DAOXE_MODEL`` env, else
            ``"not-provided"``.
        name (str): Display name. Defaults to ``"DaoXE"``.
        provider (str): Provider name. Defaults to ``"DaoXE"``.
        api_key (Optional[str]): API key. Defaults to ``DAOXE_API_KEY`` env.
        base_url (str): Defaults to ``https://daoxe.com/v1``.
    """

    id: str = field(default_factory=lambda: getenv("DAOXE_MODEL") or "not-provided")
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
