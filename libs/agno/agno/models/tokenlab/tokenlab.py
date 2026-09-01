from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class TokenLab(OpenAILike):
    """
    A class for using models hosted on TokenLab.

    Attributes:
        id (str): The model id. Defaults to "gpt-5.4-mini".
        name (str): The model name. Defaults to "TokenLab".
        provider (str): The provider name. Defaults to "TokenLab".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.tokenlab.sh/v1".
    """

    id: str = "gpt-5.4-mini"
    name: str = "TokenLab"
    provider: str = "TokenLab"

    api_key: Optional[str] = field(default_factory=lambda: getenv("TOKENLAB_API_KEY"))
    base_url: str = "https://api.tokenlab.sh/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("TOKENLAB_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="TOKENLAB_API_KEY not set. Please set the TOKENLAB_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()
