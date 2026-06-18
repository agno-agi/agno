from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Pinstripes(OpenAILike):
    """
    A class for interacting with the Pinstripes OpenAI-compatible inference API.

    Pinstripes (https://pinstripes.io) provides low-cost access to state-of-the-art
    open-weight models via an OpenAI-compatible REST API.

    Attributes:
        id (str): The model ID to use. Defaults to "ps/deepseek-v4-flash".
        name (str): The name of this model instance. Defaults to "Pinstripes".
        provider (str): The provider name. Defaults to "Pinstripes".
        api_key (Optional[str]): The Pinstripes API key. Reads from PINSTRIPES_API_KEY env var.
        base_url (str): The base URL for the API. Defaults to "https://pinstripes.io/v1".

    Available models (as of 2025):
        - ps/deepseek-v4-flash    DeepSeek V4 Flash        $0.10/M tokens
        - ps/glm-4.5-air          GLM-4.5-Air              $0.125/M tokens
        - ps/qwen3-35b            Qwen3-35B                $0.14/M tokens
        - ps/minimax-m2.7         MiniMax M2.7             $0.255/M tokens

    Example:
        >>> from agno.models.pinstripes import Pinstripes
        >>> model = Pinstripes(id="ps/deepseek-v4-flash")
    """

    id: str = "ps/deepseek-v4-flash"
    name: str = "Pinstripes"
    provider: str = "Pinstripes"

    api_key: Optional[str] = field(default_factory=lambda: getenv("PINSTRIPES_API_KEY"))
    base_url: str = "https://pinstripes.io/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for PINSTRIPES_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.

        Raises:
            ModelAuthenticationError: If PINSTRIPES_API_KEY is not set.
        """
        if not self.api_key:
            self.api_key = getenv("PINSTRIPES_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="PINSTRIPES_API_KEY not set. Please set the PINSTRIPES_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
