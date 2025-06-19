import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning

try:
    from cerebras.cloud.sdk import AsyncCerebras as AsyncCerebrasClient
    from cerebras.cloud.sdk import Cerebras as CerebrasClient
    from cerebras.cloud.sdk.types.chat import ChatCompletion
    from cerebras.cloud.sdk.types.chat.chat_completion import (
        ChatChunkResponse,
        ChatChunkResponseChoice,
        ChatChunkResponseChoiceDelta,
        ChatCompletionResponse,
        ChatCompletionResponseChoice,
        ChatCompletionResponseChoiceMessage,
    )
except (ImportError, ModuleNotFoundError):
    raise ImportError("`cerebras-cloud-sdk` not installed. Please install using `pip install cerebras-cloud-sdk`")


@dataclass
class Cerebras(Model):
    """
    A class for interacting with models using the Cerebras API.
    """

    id: str = "llama-4-scout-17b-16e-instruct"
    name: str = "Cerebras"
    provider: str = "Cerebras"

    supports_native_structured_outputs: bool = False
    supports_json_schema_outputs: bool = True

    # Request parameters
    parallel_tool_calls: bool = False
    max_completion_tokens: Optional[int] = None
    repetition_penalty: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    extra_body: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # Cerebras clients
    client: Optional[CerebrasClient] = None
    async_client: Optional[AsyncCerebrasClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("CEREBRAS_API_KEY")
            if not self.api_key:
                log_error("CEREBRAS_API_KEY not set. Please set the CEREBRAS_API_KEY environment variable.")

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> CerebrasClient:
        """
        Returns a Cerebras client.

        Returns:
            CerebrasClient: An instance of the Cerebras client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        self.client = CerebrasClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncCerebrasClient:
        """
        Returns an asynchronous Cerebras client.

        Returns:
            AsyncCerebras: An instance of the asynchronous Cerebras client.
        """
        if self.async_client:
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )
        self.async_client = AsyncCerebrasClient(**client_params)
        return self.async_client

    def get_request_kwargs(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "max_completion_tokens": self.max_completion_tokens,
            "repetition_penalty": self.repetition_penalty,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
            "extra_body": self.extra_body,
            "request_params": self.request_params,
        }

        # Filter out None values
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}

        # Add tools
        if tools is not None and len(tools) > 0:
            request_params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["function"]["name"],
                        "strict": True,  # Ensure strict adherence to expected outputs
                        "description": tool["function"]["description"],
                        "parameters": tool["function"]["parameters"],
                    },
                }
                for tool in tools
            ]
            # Cerebras requires parallel_tool_calls=False for llama-4-scout-17b-16e-instruct
            request_params["parallel_tool_calls"] = self.parallel_tool_calls

        # Handle response format for structured outputs
        if response_format is not None:
            if (
                isinstance(response_format, dict)
                and response_format.get("type") == "json_schema"
                and isinstance(response_format.get("json_schema"), dict)
            ):
                # Ensure json_schema has strict=True as required by Cerebras API
                schema = response_format["json_schema"]
                if isinstance(schema.get("schema"), dict) and "strict" not in schema:
                    schema["strict"] = True

                request_params["response_format"] = response_format

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        """
        Send a chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            CompletionResponse: The chat completion response from the API.
        """
        return self.get_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m) for m in messages],  # type: ignore
            **self.get_request_kwargs(response_format=response_format, tools=tools),
        )

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        """
        Sends an asynchronous chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        return await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m) for m in messages],  # type: ignore
            **self.get_request_kwargs(response_format=response_format, tools=tools),
        )

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[ChatChunkResponse]:
        """
        Send a streaming chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatChunkResponse]: An iterator of chat completion chunks.
        """
        yield from self.get_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.get_request_kwargs(response_format=response_format, tools=tools),
        )  # type: ignore

    async def ainvoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[ChatChunkResponse]:
        """
        Sends an asynchronous streaming chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AsyncIterator[ChatChunkResponse]: An asynchronous iterator of chat completion chunks.
        """
        async_stream = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.get_request_kwargs(response_format=response_format, tools=tools),
        )
        async for chunk in async_stream:  # type: ignore
            yield chunk  # type: ignore

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by the Cerebras API.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        # Basic message content
        message_dict: Dict[str, Any] = {
            "role": message.role,
            "content": message.content if message.content is not None else "",
        }

        # Add name if present
        if message.name:
            message_dict["name"] = message.name

        # Handle tool calls
        if message.tool_calls:
            # Ensure tool_calls is properly formatted
            message_dict["tool_calls"] = [
                {
                    "id": tool_call["id"],
                    "type": tool_call["type"],
                    "function": {
                        "name": tool_call["function"]["name"],
                        "arguments": json.dumps(tool_call["function"]["arguments"])
                        if isinstance(tool_call["function"]["arguments"], (dict, list))
                        else tool_call["function"]["arguments"],
                    },
                }
                for tool_call in message.tool_calls
            ]

        # Handle tool responses
        if message.role == "tool" and message.tool_call_id:
            message_dict = {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content if message.content is not None else "",
            }

        # Ensure no None values in the message
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        return message_dict

    def parse_provider_response(self, response: ChatCompletionResponse, **kwargs) -> ModelResponse:
        """
        Parse the Cerebras response into a ModelResponse.

        Args:
            response (CompletionResponse): The response from the Cerebras API.

        Returns:
            ModelResponse: The parsed response.
        """
        model_response = ModelResponse()

        # Get the first choice (assuming single response)
        choice: ChatCompletionResponseChoice = response.choices[0]
        message: ChatCompletionResponseChoiceMessage = choice.message

        # Add role
        if message.role is not None:
            model_response.role = message.role

        # Add content
        if message.content is not None:
            model_response.content = message.content

        # Add tool calls
        if message.tool_calls is not None:
            try:
                model_response.tool_calls = [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in message.tool_calls
                ]
            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        # Add usage metrics
        if response.usage:
            model_response.response_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatChunkResponse) -> ModelResponse:
        """
        Parse the streaming response from the Cerebras API into a ModelResponse.

        Args:
            response_delta (ChatChunkResponse): The streaming response chunk.

        Returns:
            ModelResponse: The parsed response.
        """
        model_response = ModelResponse()

        # Get the first choice (assuming single response)
        if response_delta.choices is not None:
            choice: ChatChunkResponseChoice = response_delta.choices[0]
            delta: ChatChunkResponseChoiceDelta = choice.delta

            # Add content
            if delta.content:
                model_response.content = delta.content

            # Add tool calls
            if delta.tool_calls:
                model_response.tool_calls = [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in delta.tool_calls
                ]

        # Add usage metrics
        if response_delta.usage:
            model_response.response_usage = {
                "input_tokens": response_delta.usage.prompt_tokens,
                "output_tokens": response_delta.usage.completion_tokens,
                "total_tokens": response_delta.usage.total_tokens,
            }

        return model_response
