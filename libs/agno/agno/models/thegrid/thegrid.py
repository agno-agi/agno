from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class TheGrid(OpenAILike):
    """
    A class for using instruments served by The Grid.

    The Grid is a spot market for inference. An id names a market instrument -- a
    task type (text, code, agent) paired with a quality tier (standard, prime,
    max) -- rather than a fixed model, so the model that serves a request differs
    from the instrument that was requested.

    Attributes:
        id (str): The instrument id. Defaults to "text-standard".
        name (str): The model name. Defaults to "TheGrid".
        provider (str): The provider name. Defaults to "TheGrid".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.thegrid.ai/v1".
    """

    id: str = "text-standard"
    name: str = "TheGrid"
    provider: str = "TheGrid"

    api_key: Optional[str] = field(default_factory=lambda: getenv("THEGRID_API_KEY"))
    base_url: str = "https://api.thegrid.ai/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("THEGRID_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="THEGRID_API_KEY not set. Please set the THEGRID_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()
