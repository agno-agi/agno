from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Sarvam(OpenAILike):
    """
    A class for interacting with Sarvam AI Token Factory models.

    Sarvam exposes an OpenAI-compatible Chat Completions API at
    https://api.sarvam.ai/v2. Reasoning is returned in `reasoning_content` and
    controlled with `reasoning_effort`; the accepted values depend on the model.
    See https://docs.sarvam.ai/api/token-factory/chat-completions for the model
    list and the per-model reasoning levels.

    Attributes:
        id (str): The model id. Defaults to "sarvam-105b".
        name (str): The model name. Defaults to "Sarvam".
        provider (str): The provider name. Defaults to "Sarvam".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.sarvam.ai/v2".
    """

    id: str = "sarvam-105b"
    name: str = "Sarvam"
    provider: str = "Sarvam"

    api_key: Optional[str] = field(default_factory=lambda: getenv("SARVAM_API_KEY"))
    base_url: str = "https://api.sarvam.ai/v2"

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("SARVAM_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="SARVAM_API_KEY not set. Please set the SARVAM_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()
