from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class TuningEngines(OpenAILike):
    """
    Class for interacting with Tuning Engines as an OpenAI-compatible endpoint.

    Tuning Engines provides a governed AI control plane with OpenAI-compatible
    model access, routing, policy controls, traces, and usage reporting.

    Attributes:
        id (str): The model alias to use. Defaults to "gpt-4o".
        name (str): The name of the API. Defaults to "Tuning Engines".
        provider (str): The provider name. Defaults to "Tuning Engines".
        api_key (Optional[str]): The Tuning Engines inference key.
        base_url (str): The API base URL. Defaults to "https://api.tuningengines.com/v1".
    """

    id: str = "gpt-4o"
    name: str = "Tuning Engines"
    provider: str = "Tuning Engines"

    api_key: Optional[str] = field(default_factory=lambda: getenv("TUNING_ENGINES_API_KEY"))
    base_url: str = field(default_factory=lambda: getenv("TUNING_ENGINES_BASE_URL", "https://api.tuningengines.com/v1"))

    def _get_client_params(self) -> Dict[str, Any]:
        # Resolve the API key from TUNING_ENGINES_API_KEY and fail fast with a clear
        # message. Without this, the base class falls back to OPENAI_API_KEY,
        # which would silently send an OpenAI key to the Tuning Engines endpoint.
        if not self.api_key:
            self.api_key = getenv("TUNING_ENGINES_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message=(
                        "TUNING_ENGINES_API_KEY not set. Please set the TUNING_ENGINES_API_KEY environment variable."
                    ),
                    model_name=self.name,
                )
        return super()._get_client_params()
