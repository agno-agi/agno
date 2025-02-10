from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from pydantic import BaseModel

from agno.media import AudioOutput
from agno.models.base import Metrics, Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger

try:
    from openai import AsyncOpenAI as AsyncOpenAIClient
    from openai import OpenAI as OpenAIClient
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        ChoiceDelta,
        ChoiceDeltaToolCall,
    )
    from openai.types.chat.chat_completion_message import ChatCompletionAudio, ChatCompletionMessage
    from openai.types.chat.parsed_chat_completion import ParsedChatCompletion
    from openai.types.completion_usage import CompletionUsage
except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class StreamData:
    response_content: str = ""
    response_audio: Optional[ChatCompletionAudio] = None
    response_tool_calls: Optional[List[ChoiceDeltaToolCall]] = None


@dataclass
class OpenAIChat(Model):
    """
    A class for interacting with OpenAI models.

    For more information, see: https://platform.openai.com/docs/api-reference/chat/create
    """

    id: str = "gpt-4o"
    name: str = "OpenAIChat"
    provider: str = "OpenAI"
    supports_structured_outputs: bool = True

    # Request parameters
    store: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    modalities: Optional[List[str]] = None
    audio: Optional[Dict[str, Any]] = None
    presence_penalty: Optional[float] = None
    response_format: Optional[Any] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    user: Optional[str] = None
    top_p: Optional[float] = None
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # OpenAI clients
    client: Optional[OpenAIClient] = None
    async_client: Optional[AsyncOpenAIClient] = None

    # Internal parameters. Not used for API requests
    # Whether to use the structured outputs with this Model.
    structured_outputs: bool = False

    # Whether to override the system role.
    override_system_role: bool = True
    # The role to map the system message to.
    system_message_role: str = "developer"

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        client_params.update(
            {
                "api_key": self.api_key,
                "organization": self.organization,
                "base_url": self.base_url,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "default_headers": self.default_headers,
                "default_query": self.default_query,
            }
        )
        if self.client_params is not None:
            client_params.update(self.client_params)

        # Remove None
        client_params = {k: v for k, v in client_params.items() if v is not None}
        return client_params

    def get_client(self) -> OpenAIClient:
        """
        Returns an OpenAI client.

        Returns:
            OpenAIClient: An instance of the OpenAI client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        self.client = OpenAIClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAIClient: An instance of the asynchronous OpenAI client.
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
        return AsyncOpenAIClient(**client_params)

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        request_params: Dict[str, Any] = {}

        request_params.update(
            {
                "store": self.store,
                "reasoning_effort": self.reasoning_effort,
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "top_logprobs": self.top_logprobs,
                "max_tokens": self.max_tokens,
                "max_completion_tokens": self.max_completion_tokens,
                "modalities": self.modalities,
                "audio": self.audio,
                "presence_penalty": self.presence_penalty,
                "response_format": self.response_format,
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "user": self.user,
                "top_p": self.top_p,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
            }
        )
        if self.tools is not None:
            request_params["tools"] = self.tools
            if self.tool_choice is None:
                request_params["tool_choice"] = "auto"
            else:
                request_params["tool_choice"] = self.tool_choice

        if self.request_params is not None:
            request_params.update(self.request_params)

        # Remove None
        request_params = {k: v for k, v in request_params.items() if v is not None}
        return request_params

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
                "top_logprobs": self.top_logprobs,
                "max_tokens": self.max_tokens,
                "max_completion_tokens": self.max_completion_tokens,
                "modalities": self.modalities,
                "audio": self.audio,
                "presence_penalty": self.presence_penalty,
                "response_format": self.response_format
                if isinstance(self.response_format, dict)
                else str(self.response_format),
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "user": self.user,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
            }
        )
        if self.tools is not None:
            _dict["tools"] = self.tools
            if self.tool_choice is None:
                _dict["tool_choice"] = "auto"
            else:
                _dict["tool_choice"] = self.tool_choice
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

    def format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        if message.role == "user":
            if message.images is not None:
                message = self.add_images_to_message(message=message, images=message.images)

            if message.audio is not None:
                message = self.add_audio_to_message(message=message, audio=message.audio)

            if message.videos is not None:
                logger.warning("Video input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message.tool_calls = None

        return message.to_dict()

    def invoke(self, messages: List[Message]) -> Union[ChatCompletion, ParsedChatCompletion]:
        """
        Send a chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        if self.response_format is not None and self.structured_outputs:
            try:
                if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                    return self.get_client().beta.chat.completions.parse(
                        model=self.id,
                        messages=[self.format_message(m) for m in messages],  # type: ignore
                        **self.request_kwargs,
                    )
                else:
                    raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")
            except Exception as e:
                logger.error(f"Error from OpenAI API: {e}")

        return self.get_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            **self.request_kwargs,
        )

    async def ainvoke(self, messages: List[Message]) -> Union[ChatCompletion, ParsedChatCompletion]:
        """
        Sends an asynchronous chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        if self.response_format is not None and self.structured_outputs:
            try:
                if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                    return await self.get_async_client().beta.chat.completions.parse(
                        model=self.id,
                        messages=[self.format_message(m) for m in messages],  # type: ignore
                        **self.request_kwargs,
                    )
                else:
                    raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")
            except Exception as e:
                logger.error(f"Error from OpenAI API: {e}")

        return await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            **self.request_kwargs,
        )

    def invoke_stream(self, messages: List[Message]) -> Iterator[ChatCompletionChunk]:
        """
        Send a streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatCompletionChunk]: An iterator of chat completion chunks.
        """
        yield from self.get_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            stream=True,
            stream_options={"include_usage": True},
            **self.request_kwargs,
        )  # type: ignore

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Sends an asynchronous streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """
        async_stream = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            stream=True,
            stream_options={"include_usage": True},
            **self.request_kwargs,
        )
        async for chunk in async_stream:  # type: ignore
            yield chunk

    def update_usage_metrics(
        self, assistant_message: Message, metrics: Metrics, response_usage: Optional[CompletionUsage]
    ) -> None:
        """
        Update the usage metrics for the assistant message and the model.

        Args:
            assistant_message (Message): The assistant message.
            metrics (Metrics): The metrics.
            response_usage (Optional[CompletionUsage]): The response usage.
        """
        # Update time taken to generate response
        assistant_message.metrics["time"] = metrics.response_timer.elapsed
        self.metrics.setdefault("response_times", []).append(metrics.response_timer.elapsed)
        if response_usage:
            prompt_tokens = response_usage.prompt_tokens
            completion_tokens = response_usage.completion_tokens
            total_tokens = response_usage.total_tokens

            if prompt_tokens is not None:
                metrics.input_tokens = prompt_tokens
                metrics.prompt_tokens = prompt_tokens
                assistant_message.metrics["input_tokens"] = prompt_tokens
                assistant_message.metrics["prompt_tokens"] = prompt_tokens
                self.metrics["input_tokens"] = self.metrics.get("input_tokens", 0) + prompt_tokens
                self.metrics["prompt_tokens"] = self.metrics.get("prompt_tokens", 0) + prompt_tokens
            if completion_tokens is not None:
                metrics.output_tokens = completion_tokens
                metrics.completion_tokens = completion_tokens
                assistant_message.metrics["output_tokens"] = completion_tokens
                assistant_message.metrics["completion_tokens"] = completion_tokens
                self.metrics["output_tokens"] = self.metrics.get("output_tokens", 0) + completion_tokens
                self.metrics["completion_tokens"] = self.metrics.get("completion_tokens", 0) + completion_tokens
            if total_tokens is not None:
                metrics.total_tokens = total_tokens
                assistant_message.metrics["total_tokens"] = total_tokens
                self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + total_tokens
            if response_usage.prompt_tokens_details is not None:
                if isinstance(response_usage.prompt_tokens_details, dict):
                    metrics.prompt_tokens_details = response_usage.prompt_tokens_details
                elif isinstance(response_usage.prompt_tokens_details, BaseModel):
                    metrics.prompt_tokens_details = response_usage.prompt_tokens_details.model_dump(exclude_none=True)
                assistant_message.metrics["prompt_tokens_details"] = metrics.prompt_tokens_details
                if metrics.prompt_tokens_details is not None:
                    for k, v in metrics.prompt_tokens_details.items():
                        self.metrics.get("prompt_tokens_details", {}).get(k, 0) + v
            if response_usage.completion_tokens_details is not None:
                if isinstance(response_usage.completion_tokens_details, dict):
                    metrics.completion_tokens_details = response_usage.completion_tokens_details
                elif isinstance(response_usage.completion_tokens_details, BaseModel):
                    metrics.completion_tokens_details = response_usage.completion_tokens_details.model_dump(
                        exclude_none=True
                    )
                assistant_message.metrics["completion_tokens_details"] = metrics.completion_tokens_details
                if metrics.completion_tokens_details is not None:
                    for k, v in metrics.completion_tokens_details.items():
                        self.metrics.get("completion_tokens_details", {}).get(k, 0) + v

    def create_assistant_message(
        self,
        response_message: ChatCompletionMessage,
        metrics: Metrics,
        response_usage: Optional[CompletionUsage],
    ) -> Message:
        """
        Create an assistant message from the response.

        Args:
            response_message (ChatCompletionMessage): The response message.
            metrics (Metrics): The metrics.
            response_usage (Optional[CompletionUsage]): The response usage.

        Returns:
            Message: The assistant message.
        """
        assistant_message = Message(
            role=response_message.role or "assistant",
            content=response_message.content,
        )
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                assistant_message.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")
        if hasattr(response_message, "audio") and response_message.audio is not None:
            try:
                assistant_message.audio_output = AudioOutput(
                    id=response_message.audio.id,
                    content=response_message.audio.data,
                    expires_at=response_message.audio.expires_at,
                    transcript=response_message.audio.transcript,
                )
            except Exception as e:
                logger.warning(f"Error processing audio: {e}")

        # Update metrics
        self.update_usage_metrics(assistant_message, metrics, response_usage)
        return assistant_message

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Generate a response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response.
        """
        logger.debug(f"---------- {self.get_provider()} Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: Union[ChatCompletion, ParsedChatCompletion] = self.invoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Parse response
        response_message: ChatCompletionMessage = response.choices[0].message
        response_usage: Optional[CompletionUsage] = response.usage
        response_audio: Optional[ChatCompletionAudio] = response_message.audio

        # -*- Parse transcript if available
        if response_audio:
            if response_audio.transcript and not response_message.content:
                response_message.content = response_audio.transcript

        # -*- Parse structured outputs
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
            logger.warning(f"Error retrieving structured outputs: {e}")

        # -*- Create assistant message
        assistant_message = self.create_assistant_message(
            response_message=response_message, metrics=metrics, response_usage=response_usage
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Update model response with assistant message content and audio
        if assistant_message.content is not None:
            # add the content to the model response
            model_response.content = assistant_message.get_content_string()
        if assistant_message.audio_output is not None:
            # add the audio to the model response
            model_response.audio = assistant_message.audio_output

        # -*- Handle tool calls
        tool_role = "tool"
        if (
            self.handle_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
                tool_role=tool_role,
            )
            is not None
        ):
            return self.handle_post_tool_call_messages(messages=messages, model_response=model_response)
        logger.debug(f"---------- {self.get_provider()} Response End ----------")
        return model_response

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Generate an asynchronous response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response from the API.
        """
        logger.debug(f"---------- {self.get_provider()} Async Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: Union[ChatCompletion, ParsedChatCompletion] = await self.ainvoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Parse response
        response_message: ChatCompletionMessage = response.choices[0].message
        response_usage: Optional[CompletionUsage] = response.usage
        response_audio: Optional[ChatCompletionAudio] = response_message.audio

        # -*- Parse transcript if available
        if response_audio:
            if response_audio.transcript and not response_message.content:
                response_message.content = response_audio.transcript

        # -*- Parse structured outputs
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
            logger.warning(f"Error retrieving structured outputs: {e}")

        # -*- Create assistant message
        assistant_message = self.create_assistant_message(
            response_message=response_message, metrics=metrics, response_usage=response_usage
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Update model response with assistant message content and audio
        if assistant_message.content is not None:
            # add the content to the model response
            model_response.content = assistant_message.get_content_string()
        if assistant_message.audio_output is not None:
            # add the audio to the model response
            model_response.audio = assistant_message.audio_output

        # -*- Handle tool calls
        tool_role = "tool"
        if (
            await self.ahandle_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
                tool_role=tool_role,
            )
            is not None
        ):
            return await self.ahandle_post_tool_call_messages(messages=messages, model_response=model_response)

        logger.debug(f"---------- {self.get_provider()} Async Response End ----------")
        return model_response

    def update_stream_metrics(self, assistant_message: Message, metrics: Metrics):
        """
        Update the usage metrics for the assistant message and the model.

        Args:
            assistant_message (Message): The assistant message.
            metrics (Metrics): The metrics.
        """
        # Update time taken to generate response
        assistant_message.metrics["time"] = metrics.response_timer.elapsed
        self.metrics.setdefault("response_times", []).append(metrics.response_timer.elapsed)

        if metrics.time_to_first_token is not None:
            assistant_message.metrics["time_to_first_token"] = metrics.time_to_first_token
            self.metrics.setdefault("time_to_first_token", []).append(metrics.time_to_first_token)

        if metrics.input_tokens is not None:
            assistant_message.metrics["input_tokens"] = metrics.input_tokens
            self.metrics["input_tokens"] = self.metrics.get("input_tokens", 0) + metrics.input_tokens
        if metrics.output_tokens is not None:
            assistant_message.metrics["output_tokens"] = metrics.output_tokens
            self.metrics["output_tokens"] = self.metrics.get("output_tokens", 0) + metrics.output_tokens
        if metrics.prompt_tokens is not None:
            assistant_message.metrics["prompt_tokens"] = metrics.prompt_tokens
            self.metrics["prompt_tokens"] = self.metrics.get("prompt_tokens", 0) + metrics.prompt_tokens
        if metrics.completion_tokens is not None:
            assistant_message.metrics["completion_tokens"] = metrics.completion_tokens
            self.metrics["completion_tokens"] = self.metrics.get("completion_tokens", 0) + metrics.completion_tokens
        if metrics.total_tokens is not None:
            assistant_message.metrics["total_tokens"] = metrics.total_tokens
            self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + metrics.total_tokens
        if metrics.prompt_tokens_details is not None:
            assistant_message.metrics["prompt_tokens_details"] = metrics.prompt_tokens_details
            for k, v in metrics.prompt_tokens_details.items():
                self.metrics.get("prompt_tokens_details", {}).get(k, 0) + v
        if metrics.completion_tokens_details is not None:
            assistant_message.metrics["completion_tokens_details"] = metrics.completion_tokens_details
            for k, v in metrics.completion_tokens_details.items():
                self.metrics.get("completion_tokens_details", {}).get(k, 0) + v

    def add_response_usage_to_metrics(self, metrics: Metrics, response_usage: CompletionUsage):
        metrics.input_tokens = response_usage.prompt_tokens
        metrics.prompt_tokens = response_usage.prompt_tokens
        metrics.output_tokens = response_usage.completion_tokens
        metrics.completion_tokens = response_usage.completion_tokens
        metrics.total_tokens = response_usage.total_tokens
        if response_usage.prompt_tokens_details is not None:
            if isinstance(response_usage.prompt_tokens_details, dict):
                metrics.prompt_tokens_details = response_usage.prompt_tokens_details
            elif isinstance(response_usage.prompt_tokens_details, BaseModel):
                metrics.prompt_tokens_details = response_usage.prompt_tokens_details.model_dump(exclude_none=True)
        if response_usage.completion_tokens_details is not None:
            if isinstance(response_usage.completion_tokens_details, dict):
                metrics.completion_tokens_details = response_usage.completion_tokens_details
            elif isinstance(response_usage.completion_tokens_details, BaseModel):
                metrics.completion_tokens_details = response_usage.completion_tokens_details.model_dump(
                    exclude_none=True
                )

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of model responses.
        """
        logger.debug(f"---------- {self.get_provider()} Response Start ----------")
        self._log_messages(messages)
        stream_data: StreamData = StreamData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        for response in self.invoke_stream(messages=messages):
            if len(response.choices) > 0:
                metrics.completion_tokens += 1
                if metrics.completion_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

                response_delta: ChoiceDelta = response.choices[0].delta

                if response_delta.content is not None:
                    stream_data.response_content += response_delta.content
                    yield ModelResponse(content=response_delta.content)

                if hasattr(response_delta, "audio"):
                    response_audio = response_delta.audio
                    stream_data.response_audio = response_audio
                    if stream_data.response_audio:
                        yield ModelResponse(
                            audio=AudioOutput(
                                id=stream_data.response_audio.id,
                                content=stream_data.response_audio.data,
                                expires_at=stream_data.response_audio.expires_at,
                                transcript=stream_data.response_audio.transcript,
                            )
                        )

                if response_delta.tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_delta.tool_calls)

            if response.usage is not None:
                self.add_response_usage_to_metrics(metrics=metrics, response_usage=response.usage)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

        if stream_data.response_audio is not None:
            assistant_message.audio_output = AudioOutput(
                id=stream_data.response_audio.id,
                content=stream_data.response_audio.data,
                expires_at=stream_data.response_audio.expires_at,
                transcript=stream_data.response_audio.transcript,
            )

        if stream_data.response_tool_calls is not None:
            _tool_calls = self.build_tool_calls(stream_data.response_tool_calls)
            if len(_tool_calls) > 0:
                assistant_message.tool_calls = _tool_calls

        # -*- Update usage metrics
        self.update_stream_metrics(assistant_message=assistant_message, metrics=metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            tool_role = "tool"
            yield from self.handle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages, tool_role=tool_role
            )
            yield from self.handle_post_tool_call_messages_stream(messages=messages)
        logger.debug(f"---------- {self.get_provider()} Response End ----------")

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Any: An asynchronous iterator of model responses.
        """
        logger.debug(f"---------- {self.get_provider()} Async Response Start ----------")
        self._log_messages(messages)
        stream_data: StreamData = StreamData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        async for response in self.ainvoke_stream(messages=messages):
            if response.choices and len(response.choices) > 0:
                metrics.completion_tokens += 1
                if metrics.completion_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

                response_delta: ChoiceDelta = response.choices[0].delta

                if response_delta.content is not None:
                    stream_data.response_content += response_delta.content
                    yield ModelResponse(content=response_delta.content)

                if hasattr(response_delta, "audio"):
                    response_audio = response_delta.audio
                    stream_data.response_audio = response_audio
                    if stream_data.response_audio:
                        yield ModelResponse(
                            audio=AudioOutput(
                                id=stream_data.response_audio.id,
                                content=stream_data.response_audio.data,
                                expires_at=stream_data.response_audio.expires_at,
                                transcript=stream_data.response_audio.transcript,
                            )
                        )

                if response_delta.tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_delta.tool_calls)

            if response.usage is not None:
                self.add_response_usage_to_metrics(metrics=metrics, response_usage=response.usage)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

        if stream_data.response_audio is not None:
            assistant_message.audio_output = AudioOutput(
                id=stream_data.response_audio.id,
                content=stream_data.response_audio.data,
                expires_at=stream_data.response_audio.expires_at,
                transcript=stream_data.response_audio.transcript,
            )

        if stream_data.response_tool_calls is not None:
            _tool_calls = self.build_tool_calls(stream_data.response_tool_calls)
            if len(_tool_calls) > 0:
                assistant_message.tool_calls = _tool_calls

        self.update_stream_metrics(assistant_message=assistant_message, metrics=metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            tool_role = "tool"
            async for tool_call_response in self.ahandle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages, tool_role=tool_role
            ):
                yield tool_call_response
            async for post_tool_call_response in self.ahandle_post_tool_call_messages_stream(messages=messages):
                yield post_tool_call_response
        logger.debug(f"---------- {self.get_provider()} Async Response End ----------")

    def build_tool_calls(self, tool_calls_data: List[ChoiceDeltaToolCall]) -> List[Dict[str, Any]]:
        """
        Build tool calls from tool call data.

        Args:
            tool_calls_data (List[ChoiceDeltaToolCall]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """

        return self._build_tool_calls(tool_calls_data)
