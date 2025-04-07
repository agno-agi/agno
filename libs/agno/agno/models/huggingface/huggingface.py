import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning

try:
    from huggingface_hub import (
        AsyncInferenceClient,
        ChatCompletionOutput,
        ChatCompletionOutputMessage,
        ChatCompletionStreamOutput,
        ChatCompletionStreamOutputDelta,
        ChatCompletionStreamOutputDeltaToolCall,
        InferenceClient,
    )
    from huggingface_hub.errors import InferenceTimeoutError
except (ModuleNotFoundError, ImportError):
    raise ImportError("`huggingface_hub` not installed. Please install using `pip install huggingface_hub`")


@dataclass
class HuggingFace(Model):
    """
    A class for interacting with HuggingFace Hub Inference models.

    Attributes:
        id (str): The id of the HuggingFace model to use. Default is "meta-llama/Meta-Llama-3-8B-Instruct".
        name (str): The name of this chat model instance. Default is "HuggingFace".
        provider (str): The provider of the model. Default is "HuggingFace".
        store (Optional[bool]): Whether or not to store the output of this chat completion request for use in the model distillation or evals products.
        frequency_penalty (Optional[float]): Penalizes new tokens based on their frequency in the text so far.
        logit_bias (Optional[Any]): Modifies the likelihood of specified tokens appearing in the completion.
        logprobs (Optional[bool]): Include the log probabilities on the logprobs most likely tokens.
        max_tokens (Optional[int]): The maximum number of tokens to generate in the chat completion.
        presence_penalty (Optional[float]): Penalizes new tokens based on whether they appear in the text so far.
        response_format (Optional[Any]): An object specifying the format that the model must output.
        seed (Optional[int]): A seed for deterministic sampling.
        stop (Optional[Union[str, List[str]]]): Up to 4 sequences where the API will stop generating further tokens.
        temperature (Optional[float]): Controls randomness in the model's output.
        top_logprobs (Optional[int]): How many log probability results to return per token.
        top_p (Optional[float]): Controls diversity via nucleus sampling.
        request_params (Optional[Dict[str, Any]]): Additional parameters to include in the request.
        api_key (Optional[str]): The Access Token for authenticating with HuggingFace.
        base_url (Optional[Union[str, httpx.URL]]): The base URL for API requests.
        timeout (Optional[float]): The timeout for API requests.
        max_retries (Optional[int]): The maximum number of retries for failed requests.
        default_headers (Optional[Any]): Default headers to include in all requests.
        default_query (Optional[Any]): Default query parameters to include in all requests.
        http_client (Optional[httpx.Client]): An optional pre-configured HTTP client.
        client_params (Optional[Dict[str, Any]]): Additional parameters for client configuration.
        client (Optional[InferenceClient]): The HuggingFace Hub Inference client instance.
        async_client (Optional[AsyncInferenceClient]): The asynchronous HuggingFace Hub client instance.
    """

    id: str = "meta-llama/Meta-Llama-3-8B-Instruct"
    name: str = "HuggingFace"
    provider: str = "HuggingFace"

    # Request parameters
    store: Optional[bool] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    response_format: Optional[Any] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    top_logprobs: Optional[int] = None
    top_p: Optional[float] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    client_params: Optional[Dict[str, Any]] = None

    # HuggingFace Hub Inference clients
    client: Optional[InferenceClient] = None
    async_client: Optional[AsyncInferenceClient] = None

    def get_client_params(self) -> Dict[str, Any]:
        self.api_key = self.api_key or getenv("HF_TOKEN")
        if not self.api_key:
            log_error("HF_TOKEN not set. Please set the HF_TOKEN environment variable.")

        _client_params: Dict[str, Any] = {}
        if self.api_key is not None:
            _client_params["api_key"] = self.api_key
        if self.base_url is not None:
            _client_params["base_url"] = self.base_url
        if self.timeout is not None:
            _client_params["timeout"] = self.timeout
        if self.max_retries is not None:
            _client_params["max_retries"] = self.max_retries
        if self.default_headers is not None:
            _client_params["default_headers"] = self.default_headers
        if self.default_query is not None:
            _client_params["default_query"] = self.default_query
        if self.client_params is not None:
            _client_params.update(self.client_params)
        return _client_params

    def get_client(self) -> InferenceClient:
        """
        Returns an HuggingFace Inference client.

        Returns:
            InferenceClient: An instance of the Inference client.
        """
        if self.client:
            return self.client

        _client_params: Dict[str, Any] = self.get_client_params()
        self.client = InferenceClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncInferenceClient:
        """
        Returns an asynchronous HuggingFace Hub client.

        Returns:
            AsyncInferenceClient: An instance of the asynchronous HuggingFace Inference client.
        """
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = self.get_client_params()
        self.async_client = AsyncInferenceClient(**_client_params)
        return self.async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for inference model client requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for inference model client requests.
        """
        _request_params: Dict[str, Any] = {}
        if self.store is not None:
            _request_params["store"] = self.store
        if self.frequency_penalty is not None:
            _request_params["frequency_penalty"] = self.frequency_penalty
        if self.logit_bias is not None:
            _request_params["logit_bias"] = self.logit_bias
        if self.logprobs is not None:
            _request_params["logprobs"] = self.logprobs
        if self.max_tokens is not None:
            _request_params["max_tokens"] = self.max_tokens
        if self.presence_penalty is not None:
            _request_params["presence_penalty"] = self.presence_penalty
        if self.seed is not None:
            _request_params["seed"] = self.seed
        if self.stop is not None:
            _request_params["stop"] = self.stop
        if self.temperature is not None:
            _request_params["temperature"] = self.temperature
        if self.top_logprobs is not None:
            _request_params["top_logprobs"] = self.top_logprobs
        if self.top_p is not None:
            _request_params["top_p"] = self.top_p
        if self._tools is not None:
            _request_params["tools"] = self._tools
            if self.tool_choice is None:
                _request_params["tool_choice"] = "auto"
            else:
                _request_params["tool_choice"] = self.tool_choice
        if self.request_params is not None:
            _request_params.update(self.request_params)
        return _request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        _dict = super().to_dict()
        _dict.update(
            {
                "store": self.store,
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "max_tokens": self.max_tokens,
                "presence_penalty": self.presence_penalty,
                "response_format": self.response_format,
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_logprobs": self.top_logprobs,
                "top_p": self.top_p,
                "tools": self._tools,
                "tool_choice": self.tool_choice
                if (self._tools is not None and self.tool_choice is not None)
                else "auto",
            }
        )
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by HuggingFace.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        message_dict = {
            "role": message.role,
            "content": message.content if message.content is not None else "",
            "name": message.name or message.tool_name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        if message.tool_calls is None or len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        return message_dict

    def invoke(self, messages: List[Message]) -> Union[ChatCompletionOutput]:
        """
        Send a chat completion request to the HuggingFace Hub.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletionOutput: The chat completion response from the Inference Client.
        """
        try:
            return self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],
                **self.request_kwargs,
            )
        except InferenceTimeoutError as e:
            log_error(f"Error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]) -> Union[ChatCompletionOutput]:
        """
        Sends an asynchronous chat completion request to the HuggingFace Hub Inference.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletionOutput: The chat completion response from the Inference Client.
        """
        try:
            async with self.get_async_client() as client:
                return await client.chat.completions.create(
                    model=self.id,
                    messages=[self._format_message(m) for m in messages],
                    **self.request_kwargs,
                )
        except InferenceTimeoutError as e:
            log_error(f"Error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[ChatCompletionStreamOutput]:
        """
        Send a streaming chat completion request to the HuggingFace API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatCompletionStreamOutput]: An iterator of chat completion delta.
        """
        try:
            yield from self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],
                stream=True,
                stream_options={"include_usage": True},
                **self.request_kwargs,
            )  # type: ignore
        except InferenceTimeoutError as e:
            log_error(f"Error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[Any]:
        """
        Sends an asynchronous streaming chat completion request to the HuggingFace API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AsyncIterator[Any]: An asynchronous iterator of chat completion chunks.
        """
        try:
            async with self.get_async_client() as client:
                stream = await client.chat.completions.create(
                    model=self.id,
                    messages=[self._format_message(m) for m in messages],
                    stream=True,
                    stream_options={"include_usage": True},
                    **self.request_kwargs,
                )
                async for chunk in stream:
                    yield chunk
        except InferenceTimeoutError as e:
            log_error(f"Error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error invoking HuggingFace model: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[ChatCompletionStreamOutputDeltaToolCall]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[ChatCompletionStreamOutputDeltaToolCall]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        tool_calls: List[Dict[str, Any]] = []
        for _tool_call in tool_calls_data:
            _index = _tool_call.index
            _tool_call_id = _tool_call.id
            _tool_call_type = _tool_call.type
            _function_name = _tool_call.function.name if _tool_call.function else None
            _function_arguments = _tool_call.function.arguments if _tool_call.function else None

            if len(tool_calls) <= _index:
                tool_calls.extend([{}] * (_index - len(tool_calls) + 1))
            tool_call_entry = tool_calls[_index]
            if not tool_call_entry:
                tool_call_entry["id"] = _tool_call_id
                tool_call_entry["type"] = _tool_call_type
                tool_call_entry["function"] = {
                    "name": _function_name or "",
                    "arguments": _function_arguments or "",
                }
            else:
                if _function_name:
                    tool_call_entry["function"]["name"] += _function_name
                if _function_arguments:
                    tool_call_entry["function"]["arguments"] += _function_arguments
                if _tool_call_id:
                    tool_call_entry["id"] = _tool_call_id
                if _tool_call_type:
                    tool_call_entry["type"] = _tool_call_type
        return tool_calls

    def parse_provider_response(self, response: ChatCompletionOutput) -> ModelResponse:
        """
        Parse the provider response into a ModelResponse.
        """
        model_response = ModelResponse()

        response_message: ChatCompletionOutputMessage = response.choices[0].message

        model_response.role = response_message.role
        if response_message.content is not None:
            model_response.content = response_message.content

        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            model_response.tool_calls = [asdict(t) for t in response_message.tool_calls]
            for tool_call in model_response.tool_calls:
                if isinstance(tool_call["function"]["arguments"], dict):
                    tool_call["function"]["arguments"] = json.dumps(tool_call["function"]["arguments"])

        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.parsed  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            log_warning(f"Error retrieving structured outputs: {e}")

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatCompletionStreamOutput) -> ModelResponse:
        """
        Parse the provider response delta into a ModelResponse.
        """
        model_response = ModelResponse()
        if response_delta.choices and len(response_delta.choices) > 0:
            response_delta_message: ChatCompletionStreamOutputDelta = response_delta.choices[0].delta

            model_response.role = response_delta_message.role

            if response_delta_message.content is not None:
                model_response.content = response_delta_message.content
            if response_delta_message.tool_calls is not None and len(response_delta_message.tool_calls) > 0:
                model_response.tool_calls = [response_delta_message.tool_calls]  # type: ignore
        if response_delta.usage is not None:
            model_response.response_usage = response_delta.usage

        return model_response
