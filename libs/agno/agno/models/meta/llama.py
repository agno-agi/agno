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
from agno.utils.log import log_error, log_info, log_warning

try:
    from llama_api_client import AsyncLlamaAPIClient, LlamaAPIClient
    from llama_api_client.types.create_chat_completion_response import CreateChatCompletionResponse
    from llama_api_client.types.create_chat_completion_response_stream_chunk import (
        CreateChatCompletionResponseStreamChunk,
    )
    from llama_api_client.types.message_param import (
        CompletionMessageParam,
        MessageParam,
        SystemMessageParam,
        ToolResponseMessageParam,
        UserMessageParam,
    )
except (ImportError, ModuleNotFoundError):
    raise ImportError("`llama-api-client` not installed. Please install using `pip install llama-api-client`")


@dataclass
class Llama(Model):
    """
    A class for interacting with Llama models using the Llama API.
    """

    id: str = "Llama-4-Maverick-17B-128E-Instruct-FP8"
    name: str = "Llama"
    provider: str = "Llama"
    supports_native_structured_outputs: bool = False

    # Request parameters
    max_tokens: Optional[int] = None
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

    # Internal parameters. Not used for API requests
    # Whether to use the structured outputs with this Model.
    structured_outputs: bool = False

    # The role to map the message role to.
    role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }

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
            "max_tokens": self.max_tokens,
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
                "max_tokens": self.max_tokens,
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
            if self.tool_choice is not None:
                model_dict["tool_choice"] = self.tool_choice
            else:
                model_dict["tool_choice"] = "auto"
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by Llama API.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role],
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        if message.images is not None and len(message.images) > 0:
            log_warning("Image input is currently unsupported.")

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        if message.audio is not None and len(message.audio) > 0:
            log_warning("Audio input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        # Manually add the content field even if it is None
        if message.content is None:
            message_dict["content"] = None

        return message_dict

    def invoke(self, messages: List[Message]) -> CreateChatCompletionResponse:
        """
        Send a chat completion request to the Llama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            CreateChatCompletionResponse: The chat completion response from the API.
        """

        try:
            if self.response_format is not None and self.structured_outputs:
                if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                    return self.get_client().beta.chat.completions.parse(
                        model=self.id,
                        messages=[self._format_message(m) for m in messages],  # type: ignore
                        **self.request_kwargs,
                    )
                else:
                    raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")

            return self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.request_kwargs,
            )
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]) -> CreateChatCompletionResponse:
        """
        Sends an asynchronous chat completion request to the Llama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            CreateChatCompletionResponse: The chat completion response from the API.
        """

        try:
            if self.response_format is not None and self.structured_outputs:
                if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                    return await self.get_async_client().beta.chat.completions.parse(
                        model=self.id,
                        messages=[self._format_message(m) for m in messages],  # type: ignore
                        **self.request_kwargs,
                    )
                else:
                    raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")
            return await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.request_kwargs,
            )
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[CreateChatCompletionResponseStreamChunk]:
        """
        Send a streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[CreateChatCompletionResponseStreamChunk]: An iterator of chat completion chunks.
        """

        try:
            yield from self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
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
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                **self.request_kwargs,
            )
            async for chunk in async_stream:
                yield chunk
        except Exception as e:
            log_error(f"Error from Llama API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # # Override base method
    # @staticmethod
    # def parse_tool_calls(tool_calls_data: List[ChoiceDeltaToolCall]) -> List[Dict[str, Any]]:
    #     """
    #     Build tool calls from streamed tool call data.

    #     Args:
    #         tool_calls_data (List[ChoiceDeltaToolCall]): The tool call data to build from.

    #     Returns:
    #         List[Dict[str, Any]]: The built tool calls.
    #     """
    #     tool_calls: List[Dict[str, Any]] = []
    #     for _tool_call in tool_calls_data:
    #         _index = _tool_call.index or 0
    #         _tool_call_id = _tool_call.id
    #         _tool_call_type = _tool_call.type
    #         _function_name = _tool_call.function.name if _tool_call.function else None
    #         _function_arguments = _tool_call.function.arguments if _tool_call.function else None

    #         if len(tool_calls) <= _index:
    #             tool_calls.extend([{}] * (_index - len(tool_calls) + 1))
    #         tool_call_entry = tool_calls[_index]
    #         if not tool_call_entry:
    #             tool_call_entry["id"] = _tool_call_id
    #             tool_call_entry["type"] = _tool_call_type
    #             tool_call_entry["function"] = {
    #                 "name": _function_name or "",
    #                 "arguments": _function_arguments or "",
    #             }
    #         else:
    #             if _function_name:
    #                 tool_call_entry["function"]["name"] += _function_name
    #             if _function_arguments:
    #                 tool_call_entry["function"]["arguments"] += _function_arguments
    #             if _tool_call_id:
    #                 tool_call_entry["id"] = _tool_call_id
    #             if _tool_call_type:
    #                 tool_call_entry["type"] = _tool_call_type
    #     return tool_calls

    def parse_provider_response(self, response: CreateChatCompletionResponse) -> ModelResponse:
        """
        Parse the Llama response into a ModelResponse.

        Args:
            response: Response from invoke() method

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        log_info(f"Llama response: {response}")

        # Get response message
        response_message = response.completion_message

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content.text

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        return model_response

    def parse_provider_response_delta(self, response_delta: CreateChatCompletionResponseStreamChunk) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from OpenAI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        log_info(f"Llama response delta: {response_delta}")

        if response_delta is not None:
            delta = response_delta.event

            # Add content
            if delta.delta.text is not None:
                model_response.content = delta.delta.text

            # # Add tool calls
            # if delta.tool_calls is not None:
            #     model_response.tool_calls = delta.tool_calls  # type: ignore

        # Add usage metrics if present
        # if response_delta.metrics is not None:
        #     model_response.response_usage = response_delta.metrics

        return model_response
