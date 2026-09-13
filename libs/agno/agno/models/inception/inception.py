from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Inception(OpenAILike):
    """
    Class for interacting with the Inception Labs API.

    Inception serves the Mercury family of diffusion LLMs (mercury, mercury-2,
    mercury-coder-small) through an OpenAI-compatible API.

    Attributes:
        id (str): The ID of the language model. Defaults to "mercury-2".
        name (str): The name of the API. Defaults to "Inception".
        provider (str): The provider of the API. Defaults to "InceptionLabs".
        api_key (Optional[str]): The API key for the Inception Labs API.
        base_url (str): The base URL for the Inception Labs API. Defaults to "https://api.inceptionlabs.ai/v1".
    """

    id: str = "mercury-2"
    name: str = "Inception"
    provider: str = "InceptionLabs"

    api_key: Optional[str] = field(default_factory=lambda: getenv("INCEPTION_API_KEY"))
    base_url: str = "https://api.inceptionlabs.ai/v1"

    # Inception's OpenAI-compatible endpoint does not implement native json_schema
    # structured outputs, so output_schema needs use_json_mode=True.
    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        # Resolve the API key from INCEPTION_API_KEY and fail fast with a clear
        # message. Without this, the base class falls back to OPENAI_API_KEY,
        # which would silently send an OpenAI key to the Inception endpoint.
        if not self.api_key:
            self.api_key = getenv("INCEPTION_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="INCEPTION_API_KEY not set. Please set the INCEPTION_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
