from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.llama import format_message

try:
    from llama_api_client import AsyncLlamaAPIClient, LlamaAPIClient
    from llama_api_client.types.create_chat_completion_response import CreateChatCompletionResponse, Metric
    from llama_api_client.types.create_chat_completion_response_stream_chunk import (
        CreateChatCompletionResponseStreamChunk,
        EventDeltaTextDelta,
        EventDeltaToolCallDelta,
        EventDeltaToolCallDeltaFunction,
        EventMetric,
    )
    from llama_api_client.types.message_text_content_item import MessageTextContentItem
except ImportError:
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
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
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
        Returns a Llama client.

        Returns:
            LlamaAPIClient: An instance of the Llama client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                client_params["http_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            client_params["http_client"] = get_default_sync_client()
        self.client = LlamaAPIClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncLlamaAPIClient:
        """
        Returns an asynchronous Llama client.

        Returns:
            AsyncLlamaAPIClient: An instance of the asynchronous Llama client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                # Use global async client when user http_client is invalid
                client_params["http_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            client_params["http_client"] = get_default_async_client()

        # Create and cache the client
        self.async_client = AsyncLlamaAPIClient(**client_params)
        return self.async_client

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.
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
        if tools is not None and len(tools) > 0:
            request_params["tools"] = tools

        if response_format is not None:
            request_params["response_format"] = response_format

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
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
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Send a chat completion request to the Llama API.
        """
        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()

        provider_response = self.get_client().chat.completions.create(
            model=self.id,
            messages=[
                format_message(m, tool_calls=bool(tools), compress_tool_results=compress_tool_results)  # type: ignore
                for m in messages
            ],
            **self.get_request_params(tools=tools, response_format=response_format),
        )

        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response, response_format=response_format)
        return model_response

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Sends an asynchronous chat completion request to the Llama API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()

        provider_response = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[
                format_message(m, tool_calls=bool(tools), compress_tool_results=compress_tool_results)  # type: ignore
                for m in messages
            ],
            **self.get_request_params(tools=tools, response_format=response_format),
        )

        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response, response_format=response_format)
        return model_response

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> Iterator[ModelResponse]:
        """
        Send a streaming chat completion request to the Llama API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        try:
            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            for chunk in self.get_client().chat.completions.create(
                model=self.id,
                messages=[
                    format_message(m, tool_calls=bool(tools), compress_tool_results=compress_tool_results)  # type: ignore
                    for m in messages
                ],
                stream=True,
                **self.get_request_params(tools=tools, response_format=response_format),
            ):
                yield self._parse_provider_response_delta(chunk)  # type: ignore

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error from Llama API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """
        Sends an asynchronous streaming chat completion request to the Llama API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()

        try:
            async for chunk in await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[
                    format_message(m, tool_calls=bool(tools), compress_tool_results=compress_tool_results)  # type: ignore
                    for m in messages
                ],
                stream=True,
                **self.get_request_params(tools=tools, response_format=response_format),
            ):
                yield self._parse_provider_response_delta(chunk)  # type: ignore

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error from Llama API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def parse_tool_calls(self, tool_calls_data: List[EventDeltaToolCallDeltaFunction]) -> List[Dict[str, Any]]:
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

    def _parse_provider_response(self, response: CreateChatCompletionResponse, **kwargs) -> ModelResponse:
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
            model_response.response_usage = self._get_metrics(response.metrics)

        return model_response

    def _parse_provider_response_delta(
        self, response: CreateChatCompletionResponseStreamChunk, **kwargs
    ) -> ModelResponse:
        """
        Parse the Llama streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from the Llama API

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if response is not None:
            delta = response.event

            # Capture metrics event
            if delta.event_type == "metrics" and delta.metrics is not None:
                model_response.response_usage = self._get_metrics(delta.metrics)

            if isinstance(delta.delta, EventDeltaTextDelta):
                model_response.content = delta.delta.text

            # Add tool calls
            if isinstance(delta.delta, EventDeltaToolCallDelta):
                model_response.tool_calls = delta.delta  # type: ignore

        return model_response

    def _get_metrics(self, response_usage: Union[List[Metric], List[EventMetric]]) -> MessageMetrics:
        """
        Parse the given Llama usage into an Agno MessageMetrics object.

        Args:
            response_usage: Usage data from Llama

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        for metric in response_usage:
            metrics_field = metric.metric
            if metrics_field == "num_prompt_tokens":
                metrics.input_tokens = int(metric.value)
            elif metrics_field == "num_completion_tokens":
                metrics.output_tokens = int(metric.value)

        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics
