from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.openai import images_to_message

try:
    from groq import APIError, APIResponseValidationError, APIStatusError
    from groq import AsyncGroq as AsyncGroqClient
    from groq import Groq as GroqClient
    from groq.types.chat import ChatCompletion
    from groq.types.chat.chat_completion_chunk import ChatCompletionChunk, ChoiceDelta, ChoiceDeltaToolCall
    from groq.types.completion_usage import CompletionUsage
except ImportError:
    raise ImportError("`groq` not installed. Please install using `pip install groq`")


@dataclass
class Groq(Model):
    """
    A class for interacting with Groq models.

    For more information, see: https://console.groq.com/docs/libraries
    """

    id: str = "llama-3.3-70b-versatile"
    name: str = "Groq"
    provider: str = "Groq"

    # Request parameters
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    top_logprobs: Optional[int] = None
    top_p: Optional[float] = None
    user: Optional[str] = None
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[int] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
    client_params: Optional[Dict[str, Any]] = None

    # Groq clients
    client: Optional[GroqClient] = None
    async_client: Optional[AsyncGroqClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("GROQ_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="GROQ_API_KEY not set. Please set the GROQ_API_KEY environment variable.",
                    model_name=self.name,
                )

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

    def get_client(self) -> GroqClient:
        """
        Returns a Groq client. Caches the client to avoid recreating it on every request.

        Returns:
            GroqClient: An instance of the Groq client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                client_params["http_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            client_params["http_client"] = get_default_sync_client()

        self.client = GroqClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncGroqClient:
        """
        Returns an asynchronous Groq client. Caches the client to avoid recreating it on every request.

        Returns:
            AsyncGroqClient: An instance of the asynchronous Groq client.
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
        self.async_client = AsyncGroqClient(**client_params)
        return self.async_client

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "frequency_penalty": self.frequency_penalty,
            "logit_bias": self.logit_bias,
            "logprobs": self.logprobs,
            "max_tokens": self.max_tokens,
            "presence_penalty": self.presence_penalty,
            "response_format": response_format,
            "seed": self.seed,
            "stop": self.stop,
            "temperature": self.temperature,
            "top_logprobs": self.top_logprobs,
            "top_p": self.top_p,
            "user": self.user,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
        }
        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}
        # Add tools
        if tools is not None:
            request_params["tools"] = tools
            if tool_choice is not None:
                request_params["tool_choice"] = tool_choice
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
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "max_tokens": self.max_tokens,
                "presence_penalty": self.presence_penalty,
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_logprobs": self.top_logprobs,
                "top_p": self.top_p,
                "user": self.user,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def format_message(
        self,
        message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        compress_tool_results: bool = False,
    ) -> Dict[str, Any]:
        """
        Format a message into the format expected by Groq.

        Args:
            message (Message): The message to format.
            response_format: Optional response format specification.
            compress_tool_results: Whether to compress tool results.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        # Use compressed content for tool messages if compression is active
        if message.role == "tool":
            content = message.get_content(use_compressed_content=compress_tool_results)
        else:
            content = message.content

        message_dict: Dict[str, Any] = {
            "role": message.role,
            "content": content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        if (
            message.role == "system"
            and isinstance(message.content, str)
            and response_format is not None
            and isinstance(response_format, dict)
            and response_format.get("type") == "json_object"
        ):
            # This is required by Groq to ensure the model outputs in the correct format
            message.content += "\n\nYour output should be in JSON format."

        if message.images is not None and len(message.images) > 0:
            # Ignore non-string message content
            # because we assume that the images/audio are already added to the message
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                message_dict["content"].extend(images_to_message(images=message.images))

        if message.files is not None and len(message.files) > 0:
            log_warning("File input is currently unsupported.")

        if message.audio is not None and len(message.audio) > 0:
            log_warning("Audio input is currently unsupported.")

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        return message_dict

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
        Send a chat completion request to the Groq API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()
            provider_response = self.get_client().chat.completions.create(
                model=self.id,
                messages=[self.format_message(m, response_format, compress_tool_results) for m in messages],  # type: ignore
                **self.get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice),
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except (APIResponseValidationError, APIStatusError) as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(
                message=e.response.text, status_code=e.response.status_code, model_name=self.name, model_id=self.id
            ) from e
        except APIError as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Groq API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

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
        Sends an asynchronous chat completion request to the Groq API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()
            response = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self.format_message(m, response_format, compress_tool_results) for m in messages],  # type: ignore
                **self.get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice),
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(response, response_format=response_format)

            return model_response

        except (APIResponseValidationError, APIStatusError) as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(
                message=e.response.text, status_code=e.response.status_code, model_name=self.name, model_id=self.id
            ) from e
        except APIError as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Groq API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

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
        Send a streaming chat completion request to the Groq API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            for chunk in self.get_client().chat.completions.create(
                model=self.id,
                messages=[self.format_message(m, response_format, compress_tool_results) for m in messages],  # type: ignore
                stream=True,
                **self.get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice),
            ):
                yield self._parse_provider_response_delta(chunk)  # type: ignore

            assistant_message.metrics.stop_timer()

        except (APIResponseValidationError, APIStatusError) as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(
                message=e.response.text, status_code=e.response.status_code, model_name=self.name, model_id=self.id
            ) from e
        except APIError as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Groq API: {str(e)}")
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
        Sends an asynchronous streaming chat completion request to the Groq API.
        """

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            async_stream = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self.format_message(m, response_format, compress_tool_results) for m in messages],  # type: ignore
                stream=True,
                **self.get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice),
            )
            async for chunk in async_stream:  # type: ignore
                yield self._parse_provider_response_delta(chunk)  # type: ignore

            assistant_message.metrics.stop_timer()

        except (APIResponseValidationError, APIStatusError) as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(
                message=e.response.text, status_code=e.response.status_code, model_name=self.name, model_id=self.id
            ) from e
        except APIError as e:
            log_error(f"Error calling Groq API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Groq API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[ChoiceDeltaToolCall]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[ChoiceDeltaToolCall]): The tool call data to build from.

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

    def _parse_provider_response(self, response: ChatCompletion, **kwargs) -> ModelResponse:
        """
        Parse the Groq response into a ModelResponse.

        Args:
            response: Raw response from Groq

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Get response message
        response_message = response.choices[0].message

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        # Add usage metrics if present
        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(self, response: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the Groq streaming response into ModelResponse objects.

        Args:
            response: Raw response chunk from Groq

        Returns:
            ModelResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()

        if len(response.choices) > 0:
            choice_delta: ChoiceDelta = response.choices[0].delta

            if choice_delta:
                # Add content
                if choice_delta.content is not None:
                    model_response.content = choice_delta.content

                # Add tool calls
                if choice_delta.tool_calls is not None:
                    model_response.tool_calls = choice_delta.tool_calls  # type: ignore

        # Add usage metrics if present
        if response.x_groq is not None and response.x_groq.usage is not None:
            model_response.response_usage = self._get_metrics(response.x_groq.usage)

        return model_response

    def _get_metrics(self, response_usage: CompletionUsage) -> MessageMetrics:
        """
        Parse the given Groq usage into an Agno MessageMetrics object.

        Args:
            response_usage: Usage data from Groq

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.prompt_tokens or 0
        metrics.output_tokens = response_usage.completion_tokens or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        # Additional time metrics offered by Groq
        if completion_time := response_usage.completion_time:
            metrics.provider_metrics = metrics.provider_metrics or {}
            metrics.provider_metrics["completion_time"] = completion_time
        if prompt_time := response_usage.prompt_time:
            metrics.provider_metrics = metrics.provider_metrics or {}
            metrics.provider_metrics["prompt_time"] = prompt_time
        if queue_time := response_usage.queue_time:
            metrics.provider_metrics = metrics.provider_metrics or {}
            metrics.provider_metrics["queue_time"] = queue_time
        if total_time := response_usage.total_time:
            metrics.provider_metrics = metrics.provider_metrics or {}
            metrics.provider_metrics["total_time"] = total_time

        return metrics
