from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug


@dataclass
class VLLM(OpenAILike):
    """
    Class for interacting with vLLM models via OpenAI-compatible API.

    Attributes:
        id: Model identifier
        name: API name
        provider: API provider
        base_url: vLLM server URL
        temperature: Sampling temperature
        top_p: Nucleus sampling probability
        presence_penalty: Penalize tokens already present in the generated text
        repetition_penalty: Penalize tokens from the prompt and generated text
        top_k: Top-k sampling
        min_p: Minimum token probability relative to the most likely token
        enable_thinking: Special mode flag
    """

    id: str = "not-set"
    name: str = "VLLM"
    provider: str = "VLLM"

    api_key: Optional[str] = None
    base_url: Optional[str] = None

    temperature: float = 0.7
    top_p: float = 0.8
    presence_penalty: float = 1.5
    top_k: Optional[int] = None
    enable_thinking: Optional[bool] = None
    repetition_penalty: Optional[float] = None
    min_p: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        model_dict = super().to_dict()
        if self.repetition_penalty is not None:
            model_dict["repetition_penalty"] = self.repetition_penalty
        if self.min_p is not None:
            model_dict["min_p"] = self.min_p
        return model_dict

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for VLLM_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("VLLM_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="VLLM_API_KEY not set. Please set the VLLM_API_KEY environment variable.",
                    model_name=self.name,
                )
        if not self.base_url:
            self.base_url = getenv("VLLM_BASE_URL", "http://localhost:8000/v1/")
        return super()._get_client_params()

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        request_kwargs = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        vllm_body: Dict[str, Any] = {}
        if self.top_k is not None:
            vllm_body["top_k"] = self.top_k
        if self.repetition_penalty is not None:
            vllm_body["repetition_penalty"] = self.repetition_penalty
        if self.min_p is not None:
            vllm_body["min_p"] = self.min_p
        if self.enable_thinking is not None:
            vllm_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = self.enable_thinking

        if vllm_body:
            existing_body = request_kwargs.get("extra_body") or {}
            request_kwargs["extra_body"] = {**existing_body, **vllm_body}

        if request_kwargs:
            log_debug(f"Calling {self.provider} with request parameters: {request_kwargs}", log_level=2)
        return request_kwargs
