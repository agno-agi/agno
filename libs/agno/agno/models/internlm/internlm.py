from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class InternLM(OpenAILike):
    """
    Class for interacting with the InternLM API.

    Attributes:
        id (str): The ID of the language model. Defaults to "internlm2.5-latest".
        name (str): The name of the model. Defaults to "InternLM".
        provider (str): The provider of the model. Defaults to "InternLM".
        api_key (Optional[str]): The API key for the InternLM API.
        base_url (Optional[str]): The base URL for the InternLM API.
    """

    id: str = "internlm2.5-latest"
    name: str = "InternLM"
    provider: str = "InternLM"

    api_key: Optional[str] = field(default_factory=lambda: getenv("INTERNLM_API_KEY"))
    base_url: Optional[str] = "https://internlm-chat.intern-ai.org.cn/puyu/api/v1/chat/completions"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for INTERNLM_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("INTERNLM_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="INTERNLM_API_KEY not set. Please set the INTERNLM_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
