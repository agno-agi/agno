from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Vllm(OpenAILike):
    """
    Class for interacting with vLLM models via OpenAI-compatible API.

    Attributes:
        id: Model identifier
        name: API name
        provider: API provider
        base_url: vLLM server URL
        temperature: Sampling temperature
        top_p: Nucleus sampling probability
        presence_penalty: Repetition penalty
        top_k: Top-k sampling
        enable_thinking: Special mode flag
    """

    id: str = "not-set"
    name: str = "vLLM"
    provider: str = "vLLM"

    api_key: Optional[str] = getenv("VLLM_API_KEY") or "EMPTY"
    base_url: str = getenv("VLLM_BASE_URL")

    temperature: float = 0.7
    top_p: float = 0.8
    presence_penalty: float = 1.5
    top_k: Optional[int] = None
    enable_thinking: Optional[bool] = None

    def __post_init__(self):
        """Validate required configuration"""
        if not self.base_url:
            raise ValueError(
                "VLLM_BASE_URL must be set via environment variable or explicit initialization"
            )
        if self.id == "not-set":
            raise ValueError(
                "Model ID must be set via environment variable or explicit initialization"
            )

    @property
    def extra_body(self) -> Optional[Dict[str, Any]]:
        """Dynamic parameters for vLLM API calls"""
        body: Dict[str, Any] = {}
        if self.top_k is not None:
            body["top_k"] = self.top_k
        if self.enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        return body or None

    @extra_body.setter
    def extra_body(self, value: Any) -> None:
        """Dummy setter to handle potential parent class expectations"""
        pass  # Explicitly ignore assignment attempts
