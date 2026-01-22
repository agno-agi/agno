import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

import httpx
from pydantic import BaseModel, ValidationError

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.claude import format_messages, format_tools_for_model

try:
    from anthropic import Anthropic as AnthropicClient
    from anthropic import (
        APIConnectionError,
        APIStatusError,
    )
    from anthropic import (
        AsyncAnthropic as AsyncAnthropicClient,
    )
    from anthropic.types import (
        ContentBlockDeltaEvent,
        ContentBlockStartEvent,
        ContentBlockStopEvent,
        MessageDeltaUsage,
        MessageStopEvent,
        Usage,
    )
    from anthropic.types import (
        Message as AnthropicMessage,
    )

except ImportError as e:
    raise ImportError("`anthropic` not installed. Please install it with `pip install anthropic`") from e


@dataclass
class OllamaAnthropic(Model):
    """
    A class for interacting with Ollama using the Anthropic Messages API compatibility.

    This allows you to use Ollama models with the Anthropic SDK, enabling compatibility
    with tools and applications that expect the Anthropic API format.

    Requires Ollama v0.14.0 or later.

    For more information, see: https://docs.ollama.com/api/anthropic-compatibility

    Example usage:
        ```python
        from agno.models.ollama import OllamaAnthropic
        from agno.agent import Agent

        agent = Agent(
            model=OllamaAnthropic(id="qwen3-coder"),
            instructions="You are a helpful assistant.",
        )
        ```
    """

    id: str = "llama3.1"
    name: str = "OllamaAnthropic"
    provider: str = "Ollama (Anthropic API)"

    # Request parameters
    max_tokens: Optional[int] = 8192
    temperature: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    base_url: str = field(default_factory=lambda: getenv("OLLAMA_HOST", "http://localhost:11434"))
    api_key: Optional[str] = field(default_factory=lambda: getenv("OLLAMA_API_KEY", "ollama"))
    timeout: Optional[float] = None
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
    client_params: Optional[Dict[str, Any]] = None

    client: Optional[AnthropicClient] = None
    async_client: Optional[AsyncAnthropicClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        # Ollama's Anthropic API requires an API key but ignores its value
        client_params["api_key"] = self.api_key or "ollama"
        client_params["base_url"] = self.base_url

        if self.timeout is not None:
            client_params["timeout"] = self.timeout

        # Add additional client parameters
        if self.client_params is not None:
            client_params.update(self.client_params)

        log_debug(f"Using Ollama Anthropic API at: {self.base_url}")
        return client_params

    def get_client(self) -> AnthropicClient:
        """
        Returns an instance of the Anthropic client configured for Ollama.
        """
        if self.client and not self.client.is_closed():
            return self.client

        _client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                _client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                _client_params["http_client"] = get_default_sync_client()
        else:
            _client_params["http_client"] = get_default_sync_client()

        self.client = AnthropicClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAnthropicClient:
        """
        Returns an instance of the async Anthropic client configured for Ollama.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        _client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                _client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                _client_params["http_client"] = get_default_async_client()
        else:
            _client_params["http_client"] = get_default_async_client()

        self.async_client = AsyncAnthropicClient(**_client_params)
        return self.async_client

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stop_sequences": self.stop_sequences,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "base_url": self.base_url,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.
        """
        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k

        if self.request_params:
            _request_params.update(self.request_params)

        return _request_params

    def _prepare_request_kwargs(
        self,
        system_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Dict[str, Any]:
        """
        Prepare the request keyword arguments for the API call.

        Args:
            system_message (str): The concatenated system messages.
            tools: Optional list of tools
            response_format: Optional response format (Pydantic model or dict)

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools).copy()
        if system_message:
            request_kwargs["system"] = [{"text": system_message, "type": "text"}]

        # Format tools for Anthropic API
        if tools:
            request_kwargs["tools"] = format_tools_for_model(tools)

        if request_kwargs:
            log_debug(f"Calling {self.provider} with request parameters: {request_kwargs}", log_level=2)
        return request_kwargs

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
        Send a request to Ollama using the Anthropic Messages API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
            request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

            assistant_message.metrics.start_timer()
            provider_response = self.get_client().messages.create(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            )
            assistant_message.metrics.stop_timer()

            # Parse the response into an Agno ModelResponse object
            model_response = self._parse_provider_response(provider_response, response_format=response_format)
            return model_response

        except APIConnectionError as e:
            log_error(f"Connection error while calling Ollama Anthropic API: {str(e)}")
            raise
        except APIStatusError as e:
            log_error(f"Ollama Anthropic API error (status {e.status_code}): {str(e)}")
            raise
        except Exception as e:
            log_error(f"Unexpected error calling Ollama Anthropic API: {str(e)}")
            raise

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> Any:
        """
        Stream a response from Ollama using the Anthropic Messages API.
        """
        chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
        request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()
            with self.get_client().messages.stream(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            ) as stream:
                for chunk in stream:  # type: ignore
                    yield self._parse_provider_response_delta(chunk, response_format=response_format)

            assistant_message.metrics.stop_timer()

        except APIConnectionError as e:
            log_error(f"Connection error while calling Ollama Anthropic API: {str(e)}")
            raise
        except APIStatusError as e:
            log_error(f"Ollama Anthropic API error (status {e.status_code}): {str(e)}")
            raise
        except Exception as e:
            log_error(f"Unexpected error calling Ollama Anthropic API: {str(e)}")
            raise

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
        Send an asynchronous request to Ollama using the Anthropic Messages API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
            request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

            assistant_message.metrics.start_timer()
            provider_response = await self.get_async_client().messages.create(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            )
            assistant_message.metrics.stop_timer()

            # Parse the response into an Agno ModelResponse object
            model_response = self._parse_provider_response(provider_response, response_format=response_format)
            return model_response

        except APIConnectionError as e:
            log_error(f"Connection error while calling Ollama Anthropic API: {str(e)}")
            raise
        except APIStatusError as e:
            log_error(f"Ollama Anthropic API error (status {e.status_code}): {str(e)}")
            raise
        except Exception as e:
            log_error(f"Unexpected error calling Ollama Anthropic API: {str(e)}")
            raise

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
        Stream an asynchronous response from Ollama using the Anthropic Messages API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
            request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

            assistant_message.metrics.start_timer()
            async with self.get_async_client().messages.stream(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            ) as stream:
                async for chunk in stream:  # type: ignore
                    yield self._parse_provider_response_delta(chunk, response_format=response_format)

            assistant_message.metrics.stop_timer()

        except APIConnectionError as e:
            log_error(f"Connection error while calling Ollama Anthropic API: {str(e)}")
            raise
        except APIStatusError as e:
            log_error(f"Ollama Anthropic API error (status {e.status_code}): {str(e)}")
            raise
        except Exception as e:
            log_error(f"Unexpected error calling Ollama Anthropic API: {str(e)}")
            raise

    def _parse_provider_response(
        self,
        response: AnthropicMessage,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        **kwargs,
    ) -> ModelResponse:
        """
        Parse the Anthropic-format response into a ModelResponse.

        Args:
            response: Raw response from Ollama (Anthropic format)
            response_format: Optional response format for structured output parsing

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Add role (always 'assistant')
        model_response.role = response.role or "assistant"

        if response.content:
            for block in response.content:
                if block.type == "text":
                    text_content = block.text

                    if model_response.content is None:
                        model_response.content = text_content
                    else:
                        model_response.content += text_content

                    # Handle structured outputs (JSON outputs)
                    if (
                        response_format is not None
                        and isinstance(response_format, type)
                        and issubclass(response_format, BaseModel)
                    ):
                        if text_content:
                            try:
                                # Parse JSON from text content
                                parsed_data = json.loads(text_content)
                                # Validate against Pydantic model
                                model_response.parsed = response_format.model_validate(parsed_data)
                                log_debug(f"Successfully parsed structured output: {model_response.parsed}")
                            except json.JSONDecodeError as e:
                                log_warning(f"Failed to parse JSON from structured output: {e}")
                            except ValidationError as e:
                                log_warning(f"Failed to validate structured output against schema: {e}")
                            except Exception as e:
                                log_warning(f"Unexpected error parsing structured output: {e}")

        # Extract tool calls from the response
        if response.stop_reason == "tool_use":
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    function_def = {"name": tool_name}
                    if tool_input:
                        function_def["arguments"] = json.dumps(tool_input)

                    model_response.extra = model_response.extra or {}

                    model_response.tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": function_def,
                        }
                    )

        # Add usage metrics
        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(
        self,
        response: Union[
            ContentBlockStartEvent,
            ContentBlockDeltaEvent,
            ContentBlockStopEvent,
            MessageStopEvent,
        ],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """
        Parse the streaming response into ModelResponse objects.

        Args:
            response: Raw response chunk from Ollama (Anthropic format)
            response_format: Optional response format for structured output parsing

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if isinstance(response, ContentBlockDeltaEvent):
            # Handle text content
            if response.delta.type == "text_delta":
                model_response.content = response.delta.text

        elif isinstance(response, ContentBlockStopEvent):
            if response.content_block.type == "tool_use":
                tool_use = response.content_block
                tool_name = tool_use.name
                tool_input = tool_use.input

                function_def = {"name": tool_name}
                if tool_input:
                    function_def["arguments"] = json.dumps(tool_input)

                model_response.extra = model_response.extra or {}

                model_response.tool_calls = [
                    {
                        "id": tool_use.id,
                        "type": "function",
                        "function": function_def,
                    }
                ]

        elif isinstance(response, MessageStopEvent):
            # Set empty content to avoid duplication (content was already streamed)
            model_response.content = ""

            # Handle structured outputs (JSON outputs) from accumulated text
            accumulated_text = ""
            for block in response.message.content:
                if block.type == "text":
                    accumulated_text += block.text

            if (
                response_format is not None
                and isinstance(response_format, type)
                and issubclass(response_format, BaseModel)
            ):
                if accumulated_text:
                    try:
                        parsed_data = json.loads(accumulated_text)
                        model_response.parsed = response_format.model_validate(parsed_data)
                        log_debug(f"Successfully parsed structured output from stream: {model_response.parsed}")
                    except json.JSONDecodeError as e:
                        log_warning(f"Failed to parse JSON from structured output in stream: {e}")
                    except ValidationError as e:
                        log_warning(f"Failed to validate structured output against schema in stream: {e}")
                    except Exception as e:
                        log_warning(f"Unexpected error parsing structured output in stream: {e}")

        if hasattr(response, "message") and hasattr(response.message, "usage") and response.message.usage is not None:
            model_response.response_usage = self._get_metrics(response.message.usage)

        return model_response

    def _get_metrics(self, response_usage: Union[Usage, MessageDeltaUsage]) -> Metrics:
        """
        Parse the given Anthropic-specific usage into an Agno Metrics object.

        Args:
            response_usage: Usage data from the API

        Returns:
            Metrics: Parsed metrics data
        """
        metrics = Metrics()

        metrics.input_tokens = response_usage.input_tokens or 0
        metrics.output_tokens = response_usage.output_tokens or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics
