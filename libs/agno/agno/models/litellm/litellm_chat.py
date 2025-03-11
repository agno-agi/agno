from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union, AsyncIterator

import litellm
from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger


@dataclass
class LiteLLM(Model):
    """
    A class for interacting with LiteLLM Python SDK.

    LiteLLM allows you to use a unified interface for various LLM providers.
    For more information, see: https://docs.litellm.ai/docs/
    """

    id: str = "gpt-4o"
    name: str = "LiteLLM"
    provider: str = "LiteLLM"

    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: float = 0.7
    top_p: float = 1.0
    request_params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize the model after the dataclass initialization."""
        super().__post_init__()
        self.model_name = self.id

        # Set up API key from environment variable if not already set
        if not self.api_key:
            self.api_key = getenv("LITELLM_API_KEY")
            if not self.api_key:
                logger.warning(
                    "LITELLM_API_KEY not set. Please set the LITELLM_API_KEY environment variable.")

    def invoke(self, messages: List[Message]) -> Any:
        """Sends a chat completion request to the LiteLLM API."""
        # Format messages properly including tool calls and results
        formatted_messages = []
        for m in messages:
            msg = {"role": m.role, "content": m.content if m.content is not None else ""}
            
            # Handle tool calls in assistant messages
            if m.role == "assistant" and m.tool_calls:
                msg["tool_calls"] = [{
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"]
                    }
                } for i, tc in enumerate(m.tool_calls)]
                
            # Handle tool responses
            if m.role == "tool":
                msg["tool_call_id"] = m.tool_call_id
                msg["name"] = m.name
                
            formatted_messages.append(msg)

        completion_kwargs = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        if self.max_tokens:
            completion_kwargs["max_tokens"] = self.max_tokens
        if self.api_key:
            completion_kwargs["api_key"] = self.api_key
        if self.api_base:
            completion_kwargs["api_base"] = self.api_base
        if self._tools:
            completion_kwargs["tools"] = self._tools
            completion_kwargs["tool_choice"] = "auto"

        return litellm.completion(**completion_kwargs)

    def invoke_stream(self, messages: List[Message]) -> Iterator[Any]:
        """Sends a streaming chat completion request to the LiteLLM API."""
        formatted_messages = [
            {"role": m.role, "content": m.content} for m in messages]

        completion_kwargs = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": True
        }

        if self.max_tokens:
            completion_kwargs["max_tokens"] = self.max_tokens
        if self.api_key:
            completion_kwargs["api_key"] = self.api_key
        if self.api_base:
            completion_kwargs["api_base"] = self.api_base
        if self._tools:
            completion_kwargs["tools"] = self._tools
            completion_kwargs["tool_choice"] = "auto"

        return litellm.completion(**completion_kwargs)

    async def ainvoke(self, messages: List[Message]) -> Any:
        """Sends an asynchronous chat request to the LiteLLM API."""
        formatted_messages = [
            {"role": m.role, "content": m.content} for m in messages]

        completion_kwargs = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        if self.max_tokens:
            completion_kwargs["max_tokens"] = self.max_tokens
        if self.api_key:
            completion_kwargs["api_key"] = self.api_key
        if self.api_base:
            completion_kwargs["api_base"] = self.api_base
        if self._tools:
            completion_kwargs["tools"] = self._tools
            completion_kwargs["tool_choice"] = "auto"

        return await litellm.acompletion(**completion_kwargs)

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[Any]:
        """Sends an asynchronous streaming chat request to the LiteLLM API."""
        formatted_messages = [
            {"role": m.role, "content": m.content} for m in messages]

        completion_kwargs = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": True
        }

        if self.max_tokens:
            completion_kwargs["max_tokens"] = self.max_tokens
        if self.api_key:
            completion_kwargs["api_key"] = self.api_key
        if self.api_base:
            completion_kwargs["api_base"] = self.api_base
        if self._tools:
            completion_kwargs["tools"] = self._tools
            completion_kwargs["tool_choice"] = "auto"

        async for chunk in await litellm.acompletion(**completion_kwargs):
            yield chunk

    def parse_provider_response(self, response: Any) -> ModelResponse:
        """Parse the provider response."""
        model_response = ModelResponse()

        response_message = response.choices[0].message

        if response_message.content is not None:
            model_response.content = response_message.content

        if hasattr(response_message, "tool_calls") and response_message.tool_calls:
            model_response.tool_calls = []
            for tool_call in response_message.tool_calls:
                model_response.tool_calls.append({
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })

        if hasattr(response, "usage"):
            model_response.response_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }

        model_response.raw = response
        return model_response

    def parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """Parse the provider response delta for streaming responses."""
        model_response = ModelResponse()

        if hasattr(response_delta, "choices") and len(response_delta.choices) > 0:
            delta = response_delta.choices[0].delta

            if hasattr(delta, "content") and delta.content is not None:
                model_response.content = delta.content

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                model_response.tool_calls = []
                for tool_call in delta.tool_calls:
                    if tool_call.type == "function":
                        model_response.tool_calls.append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        })

        model_response.raw = response_delta
        return model_response
