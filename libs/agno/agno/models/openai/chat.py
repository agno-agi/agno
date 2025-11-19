from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Literal, Optional, Type, Union
from uuid import uuid4

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Audio
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message
from agno.utils.reasoning import extract_thinking_content

try:
    from openai import APIConnectionError, APIStatusError, RateLimitError
    from openai import AsyncOpenAI as AsyncOpenAIClient
    from openai import OpenAI as OpenAIClient
    from openai.types import CompletionUsage
    from openai.types.chat import ChatCompletion, ChatCompletionAudio, ChatCompletionChunk
    from openai.types.chat.chat_completion_chunk import ChoiceDelta, ChoiceDeltaToolCall
except (ImportError, ModuleNotFoundError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class OpenAIChat(Model):
    """
    A class for interacting with OpenAI models using the Chat completions API.

    For more information, see: https://platform.openai.com/docs/api-reference/chat/create
    """

    id: str = "gpt-4o"
    name: str = "OpenAIChat"
    provider: str = "OpenAI"
    supports_native_structured_outputs: bool = True

    # Request parameters
    store: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    verbosity: Optional[Literal["low", "medium", "high"]] = None
    metadata: Optional[Dict[str, Any]] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    modalities: Optional[List[str]] = None  # "text" and/or "audio"
    audio: Optional[Dict[str, Any]] = (
        None  # E.g. {"voice": "alloy", "format": "wav"}. `format` must be one of `wav`, `mp3`, `flac`, `opus`, or `pcm16`. `voice` must be one of `ash`, `ballad`, `coral`, `sage`, `verse`, `alloy`, `echo`, and `shimmer`.
    )
    presence_penalty: Optional[float] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    user: Optional[str] = None
    top_p: Optional[float] = None
    service_tier: Optional[str] = None  # "auto" | "default" | "flex" | "priority", defaults to "auto" when not set
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    extra_body: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None
    role_map: Optional[Dict[str, str]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
    client_params: Optional[Dict[str, Any]] = None

    # The role to map the message role to.
    default_role_map = {
        "system": "developer",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("OPENAI_API_KEY")
            if not self.api_key:
                log_error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
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

    def get_client(self) -> OpenAIClient:
        """
        Returns an OpenAI client.

        Returns:
            OpenAIClient: An instance of the OpenAI client.
        """
        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client.")
        return OpenAIClient(**client_params)

    def get_async_client(self) -> AsyncOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAIClient: An instance of the asynchronous OpenAI client.
        """
        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.AsyncClient. Using default httpx.AsyncClient.")
                # Create a new async HTTP client with custom limits
                client_params["http_client"] = httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
                )
        else:
            # Create a new async HTTP client with custom limits
            client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )
        return AsyncOpenAIClient(**client_params)

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "store": self.store,
            "reasoning_effort": self.reasoning_effort,
            "verbosity": self.verbosity,
            "frequency_penalty": self.frequency_penalty,
            "logit_bias": self.logit_bias,
            "logprobs": self.logprobs,
            "top_logprobs": self.top_logprobs,
            "max_tokens": self.max_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "modalities": self.modalities,
            "audio": self.audio,
            "presence_penalty": self.presence_penalty,
            "seed": self.seed,
            "stop": self.stop,
            "temperature": self.temperature,
            "user": self.user,
            "top_p": self.top_p,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
            "extra_body": self.extra_body,
            "metadata": self.metadata,
            "service_tier": self.service_tier,
        }

        # Handle response format - always use JSON schema approach
        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                # Convert Pydantic to JSON schema for regular endpoint
                from agno.utils.models.schema_utils import get_response_schema_for_provider

                schema = get_response_schema_for_provider(response_format, "openai")
                base_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                }
            else:
                # Handle other response format types (like {"type": "json_object"})
                base_params["response_format"] = response_format

        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}

        # Add tools
        if tools is not None and len(tools) > 0:
            # Remove unsupported fields for OpenAILike models
            if self.provider in ["AIMLAPI", "Fireworks", "Nvidia"]:
                for tool in tools:
                    if tool.get("type") == "function":
                        if tool["function"].get("requires_confirmation") is not None:
                            del tool["function"]["requires_confirmation"]
                        if tool["function"].get("external_execution") is not None:
                            del tool["function"]["external_execution"]

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
                "store": self.store,
                "reasoning_effort": self.reasoning_effort,
                "verbosity": self.verbosity,
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "top_logprobs": self.top_logprobs,
                "max_tokens": self.max_tokens,
                "max_completion_tokens": self.max_completion_tokens,
                "modalities": self.modalities,
                "audio": self.audio,
                "presence_penalty": self.presence_penalty,
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "user": self.user,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
                "extra_body": self.extra_body,
                "service_tier": self.service_tier,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role] if self.role_map else self.default_role_map[message.role],
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if (message.images is not None and len(message.images) > 0) or (
            message.audio is not None and len(message.audio) > 0
        ):
            # Ignore non-string message content
            # because we assume that the images/audio are already added to the message
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                if message.images is not None:
                    message_dict["content"].extend(images_to_message(images=message.images))

                if message.audio is not None:
                    message_dict["content"].extend(audio_to_message(audio=message.audio))

        if message.audio_output is not None:
            message_dict["content"] = ""
            message_dict["audio"] = {"id": message.audio_output.id}

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        if message.files is not None:
            # Ensure content is a list of parts
            content = message_dict.get("content")
            if isinstance(content, str):  # wrap existing text
                text = content
                message_dict["content"] = [{"type": "text", "text": text}]
            elif content is None:
                message_dict["content"] = []
            # Insert each file part before text parts
            for file in message.files:
                file_part = _format_file_for_message(file)
                if file_part:
                    message_dict["content"].insert(0, file_part)

        # Manually add the content field even if it is None
        if message.content is None:
            message_dict["content"] = ""
        return message_dict

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Send a chat completion request to the OpenAI API and parse the response.

        Args:
            messages (List[Message]): A list of messages to send to the model.
            assistant_message (Message): The assistant message to populate.
            response_format (Optional[Union[Dict, Type[BaseModel]]]): The response format to use.
            tools (Optional[List[Dict[str, Any]]]): The tools to use.
            tool_choice (Optional[Union[str, Dict[str, Any]]]): The tool choice to use.

        Returns:
            ModelResponse: The chat completion response from the API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            provider_response = self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.get_request_params(
                    response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
                ),
            )
            assistant_message.metrics.stop_timer()

            # Parse the response into an Agno ModelResponse object
            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Sends an asynchronous chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.
            assistant_message (Message): The assistant message to populate.
            response_format (Optional[Union[Dict, Type[BaseModel]]]): The response format to use.
            tools (Optional[List[Dict[str, Any]]]): The tools to use.
            tool_choice (Optional[Union[str, Dict[str, Any]]]): The tool choice to use.

        Returns:
            ModelResponse: The chat completion response from the API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()
            response = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.get_request_params(
                    response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
                ),
            )
            assistant_message.metrics.stop_timer()

            # Parse the response into an Agno ModelResponse object
            provider_response: ModelResponse = self._parse_provider_response(response, response_format=response_format)

            return provider_response

        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Iterator[ModelResponse]:
        """
        Send a streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ModelResponse]: An iterator of model responses.
        """

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            for chunk in self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                stream_options={"include_usage": True},
                **self.get_request_params(
                    response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
                ),
            ):
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> AsyncIterator[ModelResponse]:
        """
        Sends an asynchronous streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of model responses.
        """

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            async_stream = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                stream_options={"include_usage": True},
                **self.get_request_params(
                    response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
                ),
            )

            async for chunk in async_stream:
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

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
            _index = _tool_call.index or 0
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

    def _parse_provider_response(
        self,
        response: ChatCompletion,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.
        """
        model_response = ModelResponse()

        if hasattr(response, "error") and response.error:  # type: ignore
            raise ModelProviderError(
                message=response.error.get("message", "Unknown model error"),  # type: ignore
                model_name=self.name,
                model_id=self.id,
            )

        # Get response message
        response_message = response.choices[0].message

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content

            # Extract thinking content before any structured parsing
            if model_response.content:
                reasoning_content, output_content = extract_thinking_content(model_response.content)
                if reasoning_content:
                    model_response.reasoning_content = reasoning_content
                    model_response.content = output_content
        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        # Add audio transcript to content if available
        response_audio: Optional[ChatCompletionAudio] = response_message.audio
        if response_audio and response_audio.transcript and not model_response.content:
            model_response.content = response_audio.transcript

        # Add audio if present
        if hasattr(response_message, "audio") and response_message.audio is not None:
            # If the audio output modality is requested, we can extract an audio response
            try:
                if isinstance(response_message.audio, dict):
                    model_response.audio = Audio(
                        id=response_message.audio.get("id"),
                        content=response_message.audio.get("data"),
                        expires_at=response_message.audio.get("expires_at"),
                        transcript=response_message.audio.get("transcript"),
                    )
                else:
                    model_response.audio = Audio(
                        id=response_message.audio.id,
                        content=response_message.audio.data,
                        expires_at=response_message.audio.expires_at,
                        transcript=response_message.audio.transcript,
                    )
            except Exception as e:
                log_warning(f"Error processing audio: {e}")

        if hasattr(response_message, "reasoning_content") and response_message.reasoning_content is not None:  # type: ignore
            model_response.reasoning_content = response_message.reasoning_content  # type: ignore

        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from OpenAI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if response_delta.choices and len(response_delta.choices) > 0:
            choice_delta: ChoiceDelta = response_delta.choices[0].delta

            if choice_delta:
                # Add content
                if choice_delta.content is not None:
                    model_response.content = choice_delta.content

                # Add tool calls
                if choice_delta.tool_calls is not None:
                    model_response.tool_calls = choice_delta.tool_calls  # type: ignore

                if hasattr(choice_delta, "reasoning_content") and choice_delta.reasoning_content is not None:
                    model_response.reasoning_content = choice_delta.reasoning_content

                # Add audio if present
                if hasattr(choice_delta, "audio") and choice_delta.audio is not None:
                    try:
                        audio_data = None
                        audio_id = None
                        audio_expires_at = None
                        audio_transcript = None

                        if isinstance(choice_delta.audio, dict):
                            audio_data = choice_delta.audio.get("data")
                            audio_id = choice_delta.audio.get("id")
                            audio_expires_at = choice_delta.audio.get("expires_at")
                            audio_transcript = choice_delta.audio.get("transcript")
                        else:
                            audio_data = choice_delta.audio.data
                            audio_id = choice_delta.audio.id
                            audio_expires_at = choice_delta.audio.expires_at
                            audio_transcript = choice_delta.audio.transcript

                        # Only create Audio object if there's actual content
                        if audio_data is not None:
                            model_response.audio = Audio(
                                id=audio_id,
                                content=audio_data,
                                expires_at=audio_expires_at,
                                transcript=audio_transcript,
                                sample_rate=24000,
                                mime_type="pcm16",
                            )
                        # If no content but there's transcript/metadata, create minimal Audio object
                        elif audio_transcript is not None or audio_id is not None:
                            model_response.audio = Audio(
                                id=audio_id or str(uuid4()),
                                content=b"",
                                expires_at=audio_expires_at,
                                transcript=audio_transcript,
                                sample_rate=24000,
                                mime_type="pcm16",
                            )
                    except Exception as e:
                        log_warning(f"Error processing audio: {e}")

        # Add usage metrics if present
        if response_delta.usage is not None:
            model_response.response_usage = self._get_metrics(response_delta.usage)

        return model_response

    def _get_metrics(self, response_usage: CompletionUsage) -> Metrics:
        """
        Parse the given OpenAI-specific usage into an Agno Metrics object.

        Args:
            response_usage: Usage data from OpenAI

        Returns:
            Metrics: Parsed metrics data
        """

        metrics = Metrics()

        metrics.input_tokens = response_usage.prompt_tokens or 0
        metrics.output_tokens = response_usage.completion_tokens or 0
        metrics.total_tokens = response_usage.total_tokens or 0

        # Add the prompt_tokens_details field
        if prompt_token_details := response_usage.prompt_tokens_details:
            metrics.audio_input_tokens = prompt_token_details.audio_tokens or 0
            metrics.cache_read_tokens = prompt_token_details.cached_tokens or 0

        # Add the completion_tokens_details field
        if completion_tokens_details := response_usage.completion_tokens_details:
            metrics.audio_output_tokens = completion_tokens_details.audio_tokens or 0
            metrics.reasoning_tokens = completion_tokens_details.reasoning_tokens or 0

        return metrics
