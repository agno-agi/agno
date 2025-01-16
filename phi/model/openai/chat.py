from os import getenv
from dataclasses import dataclass, field
from typing import Optional, List, Iterator, Dict, Any, Union

import httpx
from pydantic import BaseModel

from phi.model.base import Model
from phi.model.message import Message
from phi.model.response import ModelResponse
from phi.tools.function import FunctionCall
from phi.utils.log import logger
from phi.utils.timer import Timer
from phi.utils.tools import get_function_call_for_tool_call


try:
    MIN_OPENAI_VERSION = (1, 52, 0)  # v1.52.0

    # Check the installed openai version
    from openai import __version__ as installed_version

    # Convert installed version to a tuple of integers for comparison
    installed_version_tuple = tuple(map(int, installed_version.split(".")))
    if installed_version_tuple < MIN_OPENAI_VERSION:
        raise ImportError(
            f"`openai` version must be >= {'.'.join(map(str, MIN_OPENAI_VERSION))}, but found {installed_version}. "
            f"Please upgrade using `pip install --upgrade openai`."
        )

    from openai.types.chat.chat_completion_message import ChatCompletionMessage, ChatCompletionAudio
    from openai import OpenAI as OpenAIClient, AsyncOpenAI as AsyncOpenAIClient
    from openai.types.completion_usage import CompletionUsage
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.parsed_chat_completion import ParsedChatCompletion
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        ChoiceDelta,
        ChoiceDeltaToolCall,
    )

except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class Metrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens_details: Optional[dict] = None
    completion_tokens_details: Optional[dict] = None
    time_to_first_token: Optional[float] = None
    response_timer: Timer = field(default_factory=Timer)

    def log(self):
        logger.debug("**************** METRICS START ****************")
        if self.time_to_first_token is not None:
            logger.debug(f"* Time to first token:         {self.time_to_first_token:.4f}s")
        logger.debug(f"* Time to generate response:   {self.response_timer.elapsed:.4f}s")
        logger.debug(f"* Tokens per second:           {self.output_tokens / self.response_timer.elapsed:.4f} tokens/s")
        logger.debug(f"* Input tokens:                {self.input_tokens or self.prompt_tokens}")
        logger.debug(f"* Output tokens:               {self.output_tokens or self.completion_tokens}")
        logger.debug(f"* Total tokens:                {self.total_tokens}")
        if self.prompt_tokens_details is not None:
            logger.debug(f"* Prompt tokens details:       {self.prompt_tokens_details}")
        if self.completion_tokens_details is not None:
            logger.debug(f"* Completion tokens details:   {self.completion_tokens_details}")
        logger.debug("**************** METRICS END ******************")


@dataclass
class StreamData:
    response_content: str = ""
    response_audio: Optional[dict] = None
    response_tool_calls: Optional[List[ChoiceDeltaToolCall]] = None


class OpenAIChat(Model):
    """
    A class for interacting with OpenAI models.

    For more information, see: https://platform.openai.com/docs/api-reference/chat/create
    """

    id: str = "gpt-4o"
    name: str = "OpenAIChat"
    provider: str = "OpenAI"

    # Request parameters
    store: Optional[bool] = None
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
    # Whether the Model supports structured outputs.
    supports_structured_outputs: bool = True

    def get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        if self.api_key is not None:
            client_params["api_key"] = self.api_key
        if self.organization is not None:
            client_params["organization"] = self.organization
        if self.base_url is not None:
            client_params["base_url"] = self.base_url
        if self.timeout is not None:
            client_params["timeout"] = self.timeout
        if self.max_retries is not None:
            client_params["max_retries"] = self.max_retries
        if self.default_headers is not None:
            client_params["default_headers"] = self.default_headers
        if self.default_query is not None:
            client_params["default_query"] = self.default_query
        if self.client_params is not None:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> OpenAIClient:
        """
        Returns an OpenAI client.

        Returns:
            OpenAIClient: An instance of the OpenAI client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self.get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        return OpenAIClient(**client_params)

    def get_async_client(self) -> AsyncOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAIClient: An instance of the asynchronous OpenAI client.
        """
        if self.async_client:
            return self.async_client

        client_params: Dict[str, Any] = self.get_client_params()
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
        if self.store is not None:
            request_params["store"] = self.store
        if self.frequency_penalty is not None:
            request_params["frequency_penalty"] = self.frequency_penalty
        if self.logit_bias is not None:
            request_params["logit_bias"] = self.logit_bias
        if self.logprobs is not None:
            request_params["logprobs"] = self.logprobs
        if self.top_logprobs is not None:
            request_params["top_logprobs"] = self.top_logprobs
        if self.max_tokens is not None:
            request_params["max_tokens"] = self.max_tokens
        if self.max_completion_tokens is not None:
            request_params["max_completion_tokens"] = self.max_completion_tokens
        if self.modalities is not None:
            request_params["modalities"] = self.modalities
        if self.audio is not None:
            request_params["audio"] = self.audio
        if self.presence_penalty is not None:
            request_params["presence_penalty"] = self.presence_penalty
        if self.response_format is not None:
            request_params["response_format"] = (
                self.response_format if isinstance(self.response_format, dict) else str(self.response_format)
            )
        if self.seed is not None:
            request_params["seed"] = self.seed
        if self.stop is not None:
            request_params["stop"] = self.stop
        if self.temperature is not None:
            request_params["temperature"] = self.temperature
        if self.user is not None:
            request_params["user"] = self.user
        if self.top_p is not None:
            request_params["top_p"] = self.top_p
        if self.extra_headers is not None:
            request_params["extra_headers"] = self.extra_headers
        if self.extra_query is not None:
            request_params["extra_query"] = self.extra_query
        if self.tools is not None:
            request_params["tools"] = self.get_tools_for_api()
            if self.tool_choice is None:
                request_params["tool_choice"] = "auto"
            else:
                request_params["tool_choice"] = self.tool_choice
        if self.request_params is not None:
            request_params.update(self.request_params)
        return request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the model.
        """
        model_dict = super().to_dict()
        if self.store is not None:
            model_dict["store"] = self.store
        if self.frequency_penalty is not None:
            model_dict["frequency_penalty"] = self.frequency_penalty
        if self.logit_bias is not None:
            model_dict["logit_bias"] = self.logit_bias
        if self.logprobs is not None:
            model_dict["logprobs"] = self.logprobs
        if self.top_logprobs is not None:
            model_dict["top_logprobs"] = self.top_logprobs
        if self.max_tokens is not None:
            model_dict["max_tokens"] = self.max_tokens
        if self.max_completion_tokens is not None:
            model_dict["max_completion_tokens"] = self.max_completion_tokens
        if self.modalities is not None:
            model_dict["modalities"] = self.modalities
        if self.audio is not None:
            model_dict["audio"] = self.audio
        if self.presence_penalty is not None:
            model_dict["presence_penalty"] = self.presence_penalty
        if self.response_format is not None:
            model_dict["response_format"] = (
                self.response_format if isinstance(self.response_format, dict) else str(self.response_format)
            )
        if self.seed is not None:
            model_dict["seed"] = self.seed
        if self.stop is not None:
            model_dict["stop"] = self.stop
        if self.temperature is not None:
            model_dict["temperature"] = self.temperature
        if self.user is not None:
            model_dict["user"] = self.user
        if self.top_p is not None:
            model_dict["top_p"] = self.top_p
        if self.extra_headers is not None:
            model_dict["extra_headers"] = self.extra_headers
        if self.extra_query is not None:
            model_dict["extra_query"] = self.extra_query
        if self.tools is not None:
            model_dict["tools"] = self.get_tools_for_api()
            if self.tool_choice is None:
                model_dict["tool_choice"] = "auto"
            else:
                model_dict["tool_choice"] = self.tool_choice
        return model_dict

    def format_message(self, message: Message, map_system_to_developer: bool = True) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.
            map_system_to_developer (bool, optional): Whether the "system" role is mapped to "developer". Defaults to True.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        # New OpenAI format
        if map_system_to_developer and message.role == "system":
            message.role = "developer"

        if message.role == "user":
            if message.images is not None:
                message = self.add_images_to_message(message=message, images=message.images)

        if message.audio is not None:
            message = self.add_audio_to_message(message=message, audio=message.audio)

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

    def handle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        tool_role: str = "tool",
    ) -> Optional[ModelResponse]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            model_response (ModelResponse): The model response.
            tool_role (str): The role of the tool call. Defaults to "tool".

        Returns:
            Optional[ModelResponse]: The model response after handling tool calls.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0 and self.run_tools:
            if model_response.content is None:
                model_response.content = ""
            function_call_results: List[Message] = []
            function_calls_to_run: List[FunctionCall] = []
            for tool_call in assistant_message.tool_calls:
                _tool_call_id = tool_call.get("id")
                _function_call = get_function_call_for_tool_call(tool_call, self.functions)
                if _function_call is None:
                    messages.append(
                        Message(
                            role="tool",
                            tool_call_id=_tool_call_id,
                            content="Could not find function to call.",
                        )
                    )
                    continue
                if _function_call.error is not None:
                    messages.append(
                        Message(
                            role="tool",
                            tool_call_id=_tool_call_id,
                            content=_function_call.error,
                        )
                    )
                    continue
                function_calls_to_run.append(_function_call)

            if self.show_tool_calls:
                model_response.content += "\nRunning:"
                for _f in function_calls_to_run:
                    model_response.content += f"\n - {_f.get_call_str()}"
                model_response.content += "\n\n"

            for _ in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                pass

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            return model_response
        return None

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
                assistant_message.audio = response_message.audio.model_dump()
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
        logger.debug("---------- OpenAI Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.response_timer.start()
        response: Union[ChatCompletion, ParsedChatCompletion] = self.invoke(messages=messages)
        metrics.response_timer.stop()

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
        if assistant_message.audio is not None:
            # add the audio to the model response
            model_response.audio = assistant_message.audio

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
        logger.debug("---------- OpenAI Response End ----------")
        return model_response

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Generate an asynchronous response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response from the API.
        """
        logger.debug("---------- OpenAI Async Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.response_timer.start()
        response: Union[ChatCompletion, ParsedChatCompletion] = await self.ainvoke(messages=messages)
        metrics.response_timer.stop()

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
        if assistant_message.audio is not None:
            # add the audio to the model response
            model_response.audio = assistant_message.audio

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
            return await self.ahandle_post_tool_call_messages(messages=messages, model_response=model_response)

        logger.debug("---------- OpenAI Async Response End ----------")
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

    def handle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        tool_role: str = "tool",
    ) -> Iterator[ModelResponse]:
        """
        Handle tool calls for response stream.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            tool_role (str): The role of the tool call. Defaults to "tool".

        Returns:
            Iterator[ModelResponse]: An iterator of the model response.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0 and self.run_tools:
            function_calls_to_run: List[FunctionCall] = []
            function_call_results: List[Message] = []
            for tool_call in assistant_message.tool_calls:
                _tool_call_id = tool_call.get("id")
                _function_call = get_function_call_for_tool_call(tool_call, self.functions)
                if _function_call is None:
                    messages.append(
                        Message(
                            role=tool_role,
                            tool_call_id=_tool_call_id,
                            content="Could not find function to call.",
                        )
                    )
                    continue
                if _function_call.error is not None:
                    messages.append(
                        Message(
                            role=tool_role,
                            tool_call_id=_tool_call_id,
                            content=_function_call.error,
                        )
                    )
                    continue
                function_calls_to_run.append(_function_call)

            if self.show_tool_calls:
                yield ModelResponse(content="\nRunning:")
                for _f in function_calls_to_run:
                    yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                yield ModelResponse(content="\n\n")

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                yield function_call_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of model responses.
        """
        logger.debug("---------- OpenAI Response Start ----------")
        self._log_messages(messages)
        stream_data: StreamData = StreamData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.response_timer.start()
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
                    yield ModelResponse(audio=response_audio)

                if response_delta.tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_delta.tool_calls)

            if response.usage is not None:
                self.add_response_usage_to_metrics(metrics=metrics, response_usage=response.usage)
        metrics.response_timer.stop()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

        if stream_data.response_audio is not None:
            assistant_message.audio = stream_data.response_audio

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
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0 and self.run_tools:
            tool_role = "tool"
            yield from self.handle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages, tool_role=tool_role
            )
            yield from self.handle_post_tool_call_messages_stream(messages=messages)
        logger.debug("---------- OpenAI Response End ----------")

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from OpenAI.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Any: An asynchronous iterator of model responses.
        """
        logger.debug("---------- OpenAI Async Response Start ----------")
        self._log_messages(messages)
        stream_data: StreamData = StreamData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.response_timer.start()
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
                    yield ModelResponse(audio=response_audio)

                if response_delta.tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_delta.tool_calls)

            if response.usage is not None:
                self.add_response_usage_to_metrics(metrics=metrics, response_usage=response.usage)
        metrics.response_timer.stop()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

        if stream_data.response_audio is not None:
            assistant_message.audio = stream_data.response_audio

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
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0 and self.run_tools:
            tool_role = "tool"
            for tool_call_response in self.handle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages, tool_role=tool_role
            ):
                yield tool_call_response
            async for post_tool_call_response in self.ahandle_post_tool_call_messages_stream(messages=messages):
                yield post_tool_call_response
        logger.debug("---------- OpenAI Async Response End ----------")

    def build_tool_calls(self, tool_calls_data: Optional[List[ChoiceDeltaToolCall]]) -> List[Dict[str, Any]]:
        if not tool_calls_data:
            return []

        tool_calls: List[Dict[str, Any]] = []
        for _index, _tool_call in enumerate(tool_calls_data):
            _tool_call_id = _tool_call.id if _tool_call else None
            _tool_call_type = _tool_call.type if _tool_call else None
            _function_name = _tool_call.function.name if _tool_call and _tool_call.function else None
            _function_arguments = _tool_call.function.arguments if _tool_call and _tool_call.function else None

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

        return tool_calls
