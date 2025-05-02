from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning
from agno.utils.models.llama import format_message

try:
    from llama_api_client import AsyncLlamaAPIClient, LlamaAPIClient
    from llama_api_client.types.create_chat_completion_response import CreateChatCompletionResponse
    from llama_api_client.types.create_chat_completion_response_stream_chunk import (
        CreateChatCompletionResponseStreamChunk,
        EventDeltaTextDelta,
        EventDeltaToolCallDelta,
        EventDeltaToolCallDeltaFunction,
    )
    from llama_api_client.types.message_text_content_item import MessageTextContentItem
except (ImportError, ModuleNotFoundError):
    raise ImportError("`llama-api-client` not installed. Please install using `pip install llama-api-client`")


@dataclass
class Llama(Model):
    """
    A class for interacting with Llama models using the Llama API using the Llama SDK.
    """

    id: str = "Llama-4-Maverick-17B-128E-Instruct-FP8"
    name: str = "Llama"
    provider: str = "Llama"
    supports_native_structured_outputs: bool = False
    supports_json_schema_outputs: bool = True

    # Request parameters
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

    # OpenAI clients
    client: Optional[LlamaAPIClient] = None
    async_client: Optional[AsyncLlamaAPIClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("LLAMA_API_KEY")
            if not self.api_key:
                log_error("LLAMA_API_KEY not set. Please set the LLAMA_API_KEY environment variable.")

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

    def get_client(self) -> LlamaAPIClient:
        """
        Returns an Llama client.

        Returns:
            LlamaAPIClient: An instance of the Llama client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        self.client = LlamaAPIClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncLlamaAPIClient:
        """
        Returns an asynchronous Llama client.

        Returns:
            AsyncLlamaAPIClient: An instance of the asynchronous Llama client.
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
        return AsyncLlamaAPIClient(**client_params)

    @property
    def request_kwargs(self) -> Dict[str, Any]:
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
        request_params = {k: v for k, v in base_params.items() if v is not None}

        # Add tools
        if self._tools is not None and len(self._tools) > 0:
            request_params["tools"] = self._tools

        if self.response_format is not None:
            request_params["response_format"] = self.response_format

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
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
        )
        if self._tools is not None:
            model_dict["tools"] = self._tools
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def invoke(self, messages: List[Message]) -> CreateChatCompletionResponse:
        """
        Send a chat completion request to the Llama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            CreateChatCompletionResponse: The chat completion response from the API.
        """
        return self.get_client().chat.completions.create(
            model=self.id,
            messages=[format_message(m) for m in messages],  # type: ignore
            **self.request_kwargs,
        )

    async def ainvoke(self, messages: List[Message]) -> CreateChatCompletionResponse:
        """
        Sends an asynchronous chat completion request to the Llama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            CreateChatCompletionResponse: The chat completion response from the API.
        """

        return await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[format_message(m) for m in messages],  # type: ignore
            **self.request_kwargs,
        )

    def invoke_stream(self, messages: List[Message]) -> Iterator[CreateChatCompletionResponseStreamChunk]:
        """
        Send a streaming chat completion request to the Llama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[CreateChatCompletionResponseStreamChunk]: An iterator of chat completion chunks.
        """

        try:
            yield from self.get_client().chat.completions.create(
                model=self.id,
                messages=[format_message(m) for m in messages],  # type: ignore
                stream=True,
                **self.request_kwargs,
            )  # type: ignore
        except Exception as e:
            log_error(f"Error from Llama API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[CreateChatCompletionResponseStreamChunk]:
        """
        Sends an asynchronous streaming chat completion request to the Llama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AsyncIterator[CreateChatCompletionResponseStreamChunk]: An asynchronous iterator of chat completion chunks.
        """

        try:
            async_stream = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[format_message(m) for m in messages],  # type: ignore
                stream=True,
                **self.request_kwargs,
            )
            async for chunk in async_stream:  # type: ignore
                yield chunk  # type: ignore
        except Exception as e:
            log_error(f"Error from Llama API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[EventDeltaToolCallDeltaFunction]) -> List[Dict[str, Any]]:
        """
        Parse the tool calls from the Llama API.

        Args:
            tool_calls_data (List[Tuple[str, Any]]): The tool calls data.

        Returns:
            List[Dict[str, Any]]: The parsed tool calls.
        """
        tool_calls: List[Dict[str, Any]] = []

        _tool_call_id: Optional[str] = None
        _function_name_parts: List[str] = []
        _function_arguments_parts: List[str] = []

        def _create_tool_call():
            nonlocal _tool_call_id
            if _tool_call_id and (_function_name_parts or _function_arguments_parts):
                tool_calls.append(
                    {
                        "id": _tool_call_id,
                        "type": "function",
                        "function": {
                            "name": "".join(_function_name_parts),
                            "arguments": "".join(_function_arguments_parts),
                        },
                    }
                )
            _tool_call_id = None
            _function_name_parts.clear()
            _function_arguments_parts.clear()

        for _field, _value in tool_calls_data:
            if _field == "function" and isinstance(_value, EventDeltaToolCallDeltaFunction):
                if _value.name and (_tool_call_id or _function_name_parts or _function_arguments_parts):
                    _create_tool_call()
                if _value.name:
                    _function_name_parts.append(_value.name)
                if _value.arguments:
                    _function_arguments_parts.append(_value.arguments)

            elif _field == "id":
                if _value and _tool_call_id:
                    _create_tool_call()
                if _value:
                    _tool_call_id = _value  # type: ignore

        _create_tool_call()

        return tool_calls

    def parse_provider_response(self, response: CreateChatCompletionResponse) -> ModelResponse:
        """
        Parse the Llama response into a ModelResponse.

        Args:
            response: Response from invoke() method

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Get response message
        response_message = response.completion_message

        # Parse structured outputs if enabled
        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.content  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            log_warning(f"Error retrieving structured outputs: {e}")

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            if isinstance(response_message.content, MessageTextContentItem):
                model_response.content = response_message.content.text
            else:
                model_response.content = response_message.content

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                for tool_call in response_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_input = tool_call.function.arguments

                    function_def = {"name": tool_name}
                    if tool_input:
                        function_def["arguments"] = tool_input

                    model_response.tool_calls.append(
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": function_def,
                        }
                    )

            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        # Add metrics from the metrics list
        if hasattr(response, "metrics") and response.metrics is not None:
            usage_data = {}
            metric_map = {
                "num_prompt_tokens": "input_tokens",
                "num_completion_tokens": "output_tokens",
                "num_total_tokens": "total_tokens",
            }

            for metric in response.metrics:
                key = metric_map.get(metric.metric)
                if key:
                    value = int(metric.value)
                    usage_data[key] = value

                if usage_data:
                    model_response.response_usage = usage_data

        return model_response

    def parse_provider_response_delta(self, response_delta: CreateChatCompletionResponseStreamChunk) -> ModelResponse:
        """
        Parse the Llama streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from the Llama API

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if response_delta is not None:
            delta = response_delta.event

            # Capture metrics event
            if delta.event_type == "metrics" and delta.metrics is not None:
                usage_data = {}
                metric_map = {
                    "num_prompt_tokens": "input_tokens",
                    "num_completion_tokens": "output_tokens",
                    "num_total_tokens": "total_tokens",
                }

                for metric in delta.metrics:
                    key = metric_map.get(metric.metric)
                    if key:
                        usage_data[key] = int(metric.value)

                if usage_data:
                    model_response.response_usage = usage_data

            if isinstance(delta.delta, EventDeltaTextDelta):
                model_response.content = delta.delta.text

            # Add tool calls
            if isinstance(delta.delta, EventDeltaToolCallDelta):
                model_response.tool_calls = delta.delta  # type: ignore

        return model_response
