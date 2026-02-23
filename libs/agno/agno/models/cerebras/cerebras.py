import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning

try:
    from cerebras.cloud.sdk import AsyncCerebras as AsyncCerebrasClient
    from cerebras.cloud.sdk import Cerebras as CerebrasClient
    from cerebras.cloud.sdk.types.chat.chat_completion import (
        ChatChunkResponse,
        ChatChunkResponseChoice,
        ChatChunkResponseChoiceDelta,
        ChatChunkResponseUsage,
        ChatCompletionResponse,
        ChatCompletionResponseChoice,
        ChatCompletionResponseChoiceMessage,
        ChatCompletionResponseUsage,
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
    parallel_tool_calls: Optional[bool] = None
    max_completion_tokens: Optional[int] = None
    repetition_penalty: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    strict_output: bool = True  # When True, guarantees schema adherence for structured outputs. When False, attempts to follow schema as a guide but may occasionally deviate
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

    def _ensure_additional_properties_false(self, schema: Dict[str, Any]) -> None:
        """
        Recursively ensure all object types have additionalProperties: false.
        Cerebras API requires this for JSON schema validation.
        """
        if not isinstance(schema, dict):
            return

        # Set additionalProperties: false for object types
        if schema.get("type") == "object":
            schema["additionalProperties"] = False

        # Recursively process nested schemas
        if "properties" in schema and isinstance(schema["properties"], dict):
            for prop_schema in schema["properties"].values():
                self._ensure_additional_properties_false(prop_schema)

        if "items" in schema:
            self._ensure_additional_properties_false(schema["items"])

        if "$defs" in schema and isinstance(schema["$defs"], dict):
            for def_schema in schema["$defs"].values():
                self._ensure_additional_properties_false(def_schema)

        for key in ["allOf", "anyOf", "oneOf"]:
            if key in schema and isinstance(schema[key], list):
                for item in schema[key]:
                    self._ensure_additional_properties_false(item)

    def get_client(self) -> CerebrasClient:
        """
        Returns a Cerebras client.

        Returns:
            CerebrasClient: An instance of the Cerebras client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        else:
            # Use global sync client when no custom http_client is provided
            client_params["http_client"] = get_default_sync_client()
        self.client = CerebrasClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncCerebrasClient:
        """
        Returns an asynchronous Cerebras client.

        Returns:
            AsyncCerebras: An instance of the asynchronous Cerebras client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client and isinstance(self.http_client, httpx.AsyncClient):
            client_params["http_client"] = self.http_client
        else:
            # Use global async client when no custom http_client is provided
            client_params["http_client"] = get_default_async_client()
        self.async_client = AsyncCerebrasClient(**client_params)
        return self.async_client

    def get_request_params(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        **kwargs: Any,
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
                        "description": tool["function"]["description"],
                        "parameters": tool["function"]["parameters"],
                    },
                }
                for tool in tools
            ]
            # Cerebras requires parallel_tool_calls=False for llama-4-scout-17b-16e-instruct
            if self.id == "llama-4-scout-17b-16e-instruct":
                request_params["parallel_tool_calls"] = False
            elif self.parallel_tool_calls is not None:
                request_params["parallel_tool_calls"] = self.parallel_tool_calls

        # Handle response format for structured outputs
        if response_format is not None:
            if (
                isinstance(response_format, dict)
                and response_format.get("type") == "json_schema"
                and isinstance(response_format.get("json_schema"), dict)
            ):
                # Ensure json_schema has strict parameter set
                schema = response_format["json_schema"]
                if isinstance(schema.get("schema"), dict):
                    if "strict" not in schema:
                        schema["strict"] = self.strict_output
                    # Cerebras requires additionalProperties: false for all object types
                    self._ensure_additional_properties_false(schema["schema"])

                request_params["response_format"] = response_format

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

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
        Send a chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            CompletionResponse: The chat completion response from the API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()
        provider_response = self.get_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m, compress_tool_results) for m in messages],  # type: ignore
            **self.get_request_params(response_format=response_format, tools=tools),
        )
        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response, response_format=response_format)  # type: ignore

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
        Sends an asynchronous chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()
        provider_response = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m, compress_tool_results) for m in messages],  # type: ignore
            **self.get_request_params(response_format=response_format, tools=tools),
        )
        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response, response_format=response_format)  # type: ignore

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
        Send a streaming chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatChunkResponse]: An iterator of chat completion chunks.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()

        for chunk in self.get_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m, compress_tool_results) for m in messages],  # type: ignore
            stream=True,
            **self.get_request_params(response_format=response_format, tools=tools),
        ):
            yield self._parse_provider_response_delta(chunk)  # type: ignore

        assistant_message.metrics.stop_timer()

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
        Sends an asynchronous streaming chat completion request to the Cerebras API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AsyncIterator[ChatChunkResponse]: An asynchronous iterator of chat completion chunks.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        if assistant_message.metrics is None:
            assistant_message.metrics = MessageMetrics()
        assistant_message.metrics.start_timer()

        async_stream = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self._format_message(m, compress_tool_results) for m in messages],  # type: ignore
            stream=True,
            **self.get_request_params(response_format=response_format, tools=tools),
        )

        async for chunk in async_stream:  # type: ignore
            yield self._parse_provider_response_delta(chunk)  # type: ignore

        assistant_message.metrics.stop_timer()

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """
        Format a message into the format expected by the Cerebras API.

        Args:
            message (Message): The message to format.
            compress_tool_results: Whether to compress tool results.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        # Use compressed content for tool messages if compression is active
        if message.role == "tool":
            content = message.get_content(use_compressed_content=compress_tool_results)
        else:
            content = message.content if message.content is not None else ""

        # Basic message content
        message_dict: Dict[str, Any] = {
            "role": message.role,
            "content": content,
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
                "content": content,
            }

        # Ensure no None values in the message
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        return message_dict

    def _parse_provider_response(self, response: ChatCompletionResponse, **kwargs) -> ModelResponse:
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
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(
        self, response: Union[ChatChunkResponse, ChatCompletionResponse]
    ) -> ModelResponse:
        """
        Parse the streaming response from the Cerebras API into a ModelResponse.

        Args:
            response (ChatChunkResponse): The streaming response chunk.

        Returns:
            ModelResponse: The parsed response.
        """
        model_response = ModelResponse()

        # Get the first choice (assuming single response)
        if response.choices is not None:
            choice: Union[ChatChunkResponseChoice, ChatCompletionResponseChoice] = response.choices[0]
            choice_delta: ChatChunkResponseChoiceDelta = choice.delta  # type: ignore

            if choice_delta:
                # Add content
                if choice_delta.content:
                    model_response.content = choice_delta.content

                # Add tool calls - preserve index for proper aggregation in parse_tool_calls
                if choice_delta.tool_calls:
                    model_response.tool_calls = [
                        {
                            "index": tool_call.index if hasattr(tool_call, "index") else idx,
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": {
                                "name": tool_call.function.name if tool_call.function else None,
                                "arguments": tool_call.function.arguments if tool_call.function else None,
                            },
                        }
                        for idx, tool_call in enumerate(choice_delta.tool_calls)
                    ]

        # Add usage metrics
        if response.usage:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build complete tool calls from streamed tool call delta data.

        Cerebras streams tool calls incrementally with partial data in each chunk.
        This method aggregates those chunks by index to produce complete tool calls.

        Args:
            tool_calls_data: List of tool call deltas from streaming chunks.

        Returns:
            List[Dict[str, Any]]: List of fully-formed tool call dicts.
        """
        tool_calls: List[Dict[str, Any]] = []

        for tool_call_delta in tool_calls_data:
            # Get the index for this tool call (default to 0 if not present)
            index = tool_call_delta.get("index", 0)

            # Extend the list if needed
            while len(tool_calls) <= index:
                tool_calls.append(
                    {
                        "id": None,
                        "type": None,
                        "function": {
                            "name": "",
                            "arguments": "",
                        },
                    }
                )

            tool_call_entry = tool_calls[index]

            # Update id if present
            if tool_call_delta.get("id"):
                tool_call_entry["id"] = tool_call_delta["id"]

            # Update type if present
            if tool_call_delta.get("type"):
                tool_call_entry["type"] = tool_call_delta["type"]

            # Update function name and arguments (concatenate for streaming)
            if tool_call_delta.get("function"):
                func_delta = tool_call_delta["function"]
                if func_delta.get("name"):
                    tool_call_entry["function"]["name"] += func_delta["name"]
                if func_delta.get("arguments"):
                    tool_call_entry["function"]["arguments"] += func_delta["arguments"]

        # Filter out any incomplete tool calls (missing id or function name)
        complete_tool_calls = [tc for tc in tool_calls if tc.get("id") and tc.get("function", {}).get("name")]

        return complete_tool_calls

    def _get_metrics(
        self, response_usage: Union[ChatCompletionResponseUsage, ChatChunkResponseUsage]
    ) -> MessageMetrics:
        """
        Parse the given Cerebras usage into an Agno MessageMetrics object.

        Args:
            response_usage: Usage data from Cerebras

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.prompt_tokens or 0
        metrics.output_tokens = response_usage.completion_tokens or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        # Capture Cerebras timing metrics if available
        provider_metrics: Dict[str, Any] = {}
        if hasattr(response_usage, "time_system") and response_usage.time_system is not None:
            provider_metrics["time_system"] = response_usage.time_system
        if hasattr(response_usage, "time_prompt") and response_usage.time_prompt is not None:
            provider_metrics["time_prompt"] = response_usage.time_prompt
        if provider_metrics:
            metrics.provider_metrics = provider_metrics

        return metrics
