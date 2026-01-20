from dataclasses import dataclass
from typing import Optional

from agno.models.openai.responses import OpenAIResponses


@dataclass
class OpenResponses(OpenAIResponses):
    """
    A base class for interacting with any provider using the Open Responses API specification.

    Open Responses is an open-source specification for building multi-provider, interoperable
    LLM interfaces based on the OpenAI Responses API. This class provides a foundation for
    providers that implement the spec (e.g., Ollama, OpenRouter).

    For more information, see: https://openresponses.org

    Key differences from OpenAIResponses:
    - Configurable base_url for pointing to different API endpoints
    - Stateless by default (no previous_response_id chaining)
    - Flexible api_key handling for providers that don't require authentication

    Args:
        id (str): The model id. Defaults to "not-provided".
        name (str): The model name. Defaults to "OpenResponses".
        api_key (Optional[str]): The API key. Defaults to "not-provided".
    """

    id: str = "not-provided"
    name: str = "OpenResponses"
    provider: str = "OpenResponses"
    api_key: Optional[str] = "not-provided"

    # Disable stateful features by default for compatible providers
    # Most OpenAI-compatible providers don't support previous_response_id chaining
    store: Optional[bool] = False

    def _using_reasoning_model(self) -> bool:
        """
        Override to disable reasoning model detection for compatible providers.

        Most compatible providers don't support OpenAI's reasoning models,
        so we disable the special handling by default. Subclasses can override
        this if they support specific reasoning models.
        """
        return False
