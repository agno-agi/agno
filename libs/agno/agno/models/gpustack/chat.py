"""GPUStack Chat Completions implementation."""

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.gpustack.base import GPUStackBaseModel
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_debug


@dataclass
class GPUStackChat(GPUStackBaseModel):
    """GPUStack Chat Completions model.

    This class implements the chat completions API for GPUStack,
    supporting conversational AI with various language models.

    API Endpoint: /v1/chat/completions
    """

    id: str = "llama3"  # Model ID on GPUStack
    name: str = "GPUStackChat"

    # Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    seed: Optional[int] = None
    n: Optional[int] = None

    # GPUStack specific parameters
    response_format: Optional[Dict[str, Any]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None

    def _prepare_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert Agno messages to GPUStack format."""
        formatted_messages = []

        for msg in messages:
            formatted_msg = {"role": msg.role, "content": msg.content or ""}

            # Add name if present
            if msg.name:
                formatted_msg["name"] = msg.name

            # Handle tool calls
            if msg.tool_calls:
                formatted_msg["tool_calls"] = msg.tool_calls

            # Handle tool responses
            if msg.tool_call_id:
                formatted_msg["tool_call_id"] = msg.tool_call_id

            formatted_messages.append(formatted_msg)

        return formatted_messages

    def _prepare_request(self, messages: List[Message], stream: bool = False, **kwargs) -> Dict[str, Any]:
        """Prepare request payload for GPUStack API."""
        request_data = {
            "model": self.id,
            "messages": self._prepare_messages(messages),
            "stream": stream,
        }

        # Add optional parameters
        if self.temperature is not None:
            request_data["temperature"] = self.temperature
        if self.max_tokens is not None:
            request_data["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            request_data["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            request_data["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            request_data["presence_penalty"] = self.presence_penalty
        if self.stop is not None:
            request_data["stop"] = self.stop
        if self.seed is not None:
            request_data["seed"] = self.seed
        if self.n is not None:
            request_data["n"] = self.n

        # Add response format if specified
        if kwargs.get("response_format") or self.response_format:
            request_data["response_format"] = kwargs.get("response_format") or self.response_format

        # Add tools if specified
        if kwargs.get("tools") or self.tools:
            request_data["tools"] = kwargs.get("tools") or self.tools

        # Add tool choice if specified
        if kwargs.get("tool_choice") or self.tool_choice:
            request_data["tool_choice"] = kwargs.get("tool_choice") or self.tool_choice

        return request_data

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Make a synchronous chat completion request."""
        log_debug(f"GPUStack Chat invoke with model: {self.id}")

        request_data = self._prepare_request(
            messages=messages,
            stream=False,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )

        response = self._make_request(
            method="POST",
            endpoint="/v1/chat/completions",
            json_data=request_data,
        )

        return response.json()

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Make an asynchronous chat completion request."""
        log_debug(f"GPUStack Chat async invoke with model: {self.id}")

        request_data = self._prepare_request(
            messages=messages,
            stream=False,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )

        response = await self._amake_request(
            method="POST",
            endpoint="/v1/chat/completions",
            json_data=request_data,
        )

        return response.json()

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[str]:
        """Stream chat completion responses."""
        log_debug(f"GPUStack Chat stream invoke with model: {self.id}")

        request_data = self._prepare_request(
            messages=messages,
            stream=True,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )

        client = self._get_client()

        with client.stream(
            method="POST",
            url="/v1/chat/completions",
            json=request_data,
        ) as response:
            if response.status_code >= 400:
                self._handle_error_response(response)

            for line in response.iter_lines():
                if line.startswith("data: "):
                    data = line[6:]  # Remove "data: " prefix
                    if data == "[DONE]":
                        break
                    yield data

    async def ainvoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion responses asynchronously."""
        log_debug(f"GPUStack Chat async stream invoke with model: {self.id}")

        request_data = self._prepare_request(
            messages=messages,
            stream=True,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )

        client = self._get_async_client()

        async with client.stream(
            method="POST",
            url="/v1/chat/completions",
            json=request_data,
        ) as response:
            if response.status_code >= 400:
                self._handle_error_response(response)

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]  # Remove "data: " prefix
                    if data == "[DONE]":
                        break
                    yield data

    def parse_provider_response(self, response: Dict[str, Any], **kwargs) -> ModelResponse:
        """Parse GPUStack chat completion response."""
        model_response = ModelResponse()

        # Extract the first choice (GPUStack follows OpenAI format)
        if "choices" in response and len(response["choices"]) > 0:
            choice = response["choices"][0]
            message = choice.get("message", {})

            # Set content
            model_response.content = message.get("content", "")

            # Set role
            model_response.role = message.get("role", "assistant")

            # Extract tool calls if present
            if "tool_calls" in message:
                model_response.tool_calls = message["tool_calls"]

            # Extract finish reason
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                model_response.extra = {"finish_reason": finish_reason}

        # Extract usage information
        if "usage" in response:
            model_response.response_usage = response["usage"]

        # Extract model information
        if "model" in response:
            if model_response.extra is None:
                model_response.extra = {}
            model_response.extra["model"] = response["model"]

        return model_response

    def parse_provider_response_delta(self, response_str: str) -> ModelResponse:
        """Parse streaming response delta from GPUStack."""
        model_response_delta = ModelResponse()

        try:
            response = json.loads(response_str)

            if "choices" in response and len(response["choices"]) > 0:
                choice = response["choices"][0]
                delta = choice.get("delta", {})

                # Extract content delta
                if "content" in delta:
                    model_response_delta.content = delta["content"]

                # Extract role if present in delta
                if "role" in delta:
                    model_response_delta.role = delta["role"]

                # Extract tool calls delta
                if "tool_calls" in delta:
                    model_response_delta.tool_calls = delta["tool_calls"]

                # Extract finish reason
                if "finish_reason" in choice and choice["finish_reason"]:
                    model_response_delta.extra = {"finish_reason": choice["finish_reason"]}

            # Extract usage (usually in the final chunk)
            if "usage" in response:
                model_response_delta.response_usage = response["usage"]

        except json.JSONDecodeError:
            log_debug(f"Failed to parse streaming response: {response_str}")

        return model_response_delta
