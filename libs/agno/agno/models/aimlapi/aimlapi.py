from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.aimlapi.constants import AIMLAPI_HEADERS
from agno.models.openai.like import OpenAILike


@dataclass
class AIMLAPI(OpenAILike):
    """
    A class for using models hosted on AIMLAPI.

    Attributes:
        id (str): The model id. Defaults to "gpt-5.6-luna".
        name (str): The model name. Defaults to "AIMLAPI".
        provider (str): The provider name. Defaults to "AIMLAPI".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.aimlapi.com/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 4096.
    """

    id: str = "gpt-5.6-luna"
    name: str = "AIMLAPI"
    provider: str = "AIMLAPI"

    api_key: Optional[str] = field(default_factory=lambda: getenv("AIMLAPI_API_KEY"))
    base_url: str = "https://api.aimlapi.com/v1"
    max_tokens: int = 4096

    def __post_init__(self):
        super().__post_init__()

        # Merge the attribution headers into the instance once, at construction,
        # so they are visible on the model itself and reach every client built
        # from it. dict() normalizes any header shape the OpenAI SDK accepts
        # (mapping, httpx.Headers, iterable of pairs); the caller wins on a
        # clash, matched case-insensitively because httpx.Headers lowercases
        # its keys. Building a new dict keeps AIMLAPI_HEADERS itself unchanged
        # across model instances.
        overrides = dict(self.default_headers) if self.default_headers is not None else {}
        overridden_keys = {key.lower() for key in overrides}
        merged = {key: value for key, value in AIMLAPI_HEADERS.items() if key.lower() not in overridden_keys}
        merged.update(overrides)
        self.default_headers = merged

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for AIMLAPI_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("AIMLAPI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="AIMLAPI_API_KEY not set. Please set the AIMLAPI_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()
