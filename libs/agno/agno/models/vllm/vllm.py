from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.openai.like import OpenAILike


@dataclass
class vLLM(OpenAILike):
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
    base_url: Optional[str] = getenv("VLLM_BASE_URL", "http://localhost:8000/v1/")

    temperature: float = 0.7
    top_p: float = 0.8
    presence_penalty: float = 1.5
    top_k: Optional[int] = None
    enable_thinking: Optional[bool] = None

    def __post_init__(self):
        """Validate required configuration"""
        if not self.base_url:
            raise ValueError("VLLM_BASE_URL must be set via environment variable or explicit initialization")
        if self.id == "not-set":
            raise ValueError("Model ID must be set via environment variable or explicit initialization")

        body: Dict[str, Any] = {}
        if self.top_k is not None:
            body["top_k"] = self.top_k
        if self.enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        self.extra_body = body or None

    def get_request_kwargs(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        request_kwargs = super().get_request_kwargs(
            response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        vllm_body: Dict[str, Any] = {}
        if self.top_k is not None:
            vllm_body["top_k"] = self.top_k
        if self.enable_thinking is not None:
            vllm_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = self.enable_thinking

        if vllm_body:
            existing_body = request_kwargs.get("extra_body") or {}
            request_kwargs["extra_body"] = {**existing_body, **vllm_body}

        return request_kwargs
