from dataclasses import dataclass
from typing import Optional

from agno.models.openai.responses import OpenAIResponses


@dataclass
class OpenAIResponsesLike(OpenAIResponses):
    """
    A base class for interacting with any provider using the OpenAI Responses API schema.

    This class provides a foundation for providers that implement OpenAI's Responses API
    specification (e.g., Ollama, OpenRouter). It extends OpenAIResponses with configurable
    defaults suitable for third-party providers.

    Key differences from OpenAIResponses:
    - Configurable base_url for pointing to different API endpoints
    - Stateless by default (no previous_response_id chaining)
    - Flexible api_key handling for providers that don't require authentication

    Args:
        id (str): The model id. Defaults to "not-provided".
        name (str): The model name. Defaults to "OpenAIResponsesLike".
        api_key (Optional[str]): The API key. Defaults to "not-provided".
    """

    id: str = "not-provided"
    name: str = "OpenAIResponsesLike"
    provider: str = "OpenAIResponsesLike"
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
