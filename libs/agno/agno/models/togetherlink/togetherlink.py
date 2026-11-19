from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class TogetherLink(OpenAILike):
    """
    A class for interacting with models through the TogetherLink gateway, an OpenAI-compatible
    router in front of Together AI models.

    TogetherLink authenticates with a standard Together API key. The default model id "auto"
    lets the gateway pick a fast or frontier model per request.

    Attributes:
        id (str): The model id. Defaults to "auto".
        name (str): The model name. Defaults to "TogetherLink".
        provider (str): The provider name. Defaults to "TogetherLink".
        api_key (Optional[str]): The Together API key. Defaults to the TOGETHER_API_KEY environment variable.
        base_url (str): The base URL. Defaults to "https://gateway.togetherlink.dev/v1".
    """

    id: str = "auto"
    name: str = "TogetherLink"
    provider: str = "TogetherLink"

    api_key: Optional[str] = field(default_factory=lambda: getenv("TOGETHER_API_KEY"))
    base_url: str = "https://gateway.togetherlink.dev/v1"

    # Gateway models reason before answering. With a bare json_schema response_format they never see
    # the schema while reasoning, and constrained decoding then fills fields with unrelated text.
    # Putting the schema in the system prompt (JSON mode) keeps output_schema reliable.
    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            raise ModelAuthenticationError(
                message="TOGETHER_API_KEY not set. Please set the TOGETHER_API_KEY environment variable.",
                model_name=self.name,
            )
        return super()._get_client_params()
