from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx

from agno.models.base import Metrics as BaseMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger

try:
    from groq import AsyncGroq as AsyncGroqClient
    from groq import Groq as GroqClient
    from groq.types.chat import ChatCompletion, ChatCompletionMessage
    from groq.types.chat.chat_completion_chunk import ChatCompletionChunk, ChoiceDelta, ChoiceDeltaToolCall
    from groq.types.completion_usage import CompletionUsage
except (ModuleNotFoundError, ImportError):
    raise ImportError("`groq` not installed. Please install using `pip install groq`")


@dataclass
class Metrics(BaseMetrics):
    completion_time: Optional[float] = None
    prompt_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None

    def log(self):
        metric_lines = []
        if self.time_to_first_token is not None:
            metric_lines.append(f"* Time to first token:         {self.time_to_first_token:.4f}s")
        metric_lines.extend(
            [
                f"* Time to generate response:   {self.response_timer.elapsed:.4f}s",
                f"* Tokens per second:           {self.output_tokens / self.response_timer.elapsed:.4f} tokens/s",
                f"* Input tokens:                {self.input_tokens or self.prompt_tokens}",
                f"* Output tokens:               {self.output_tokens or self.completion_tokens}",
                f"* Total tokens:                {self.total_tokens}",
            ]
        )
        if self.completion_time is not None:
            metric_lines.append(f"* Completion time:             {self.completion_time:.4f}s")
        if self.prompt_time is not None:
            metric_lines.append(f"* Prompt time:                 {self.prompt_time:.4f}s")
        if self.queue_time is not None:
            metric_lines.append(f"* Queue time:                  {self.queue_time:.4f}s")
        if self.total_time is not None:
            metric_lines.append(f"* Total time:                  {self.total_time:.4f}s")

        self._log(metric_lines=metric_lines)


@dataclass
class StreamData:
    response_content: str = ""
    response_tool_calls: Optional[List[ChoiceDeltaToolCall]] = None


@dataclass
class Groq(Model):
    """
    A class for interacting with Groq models.

    For more information, see: https://console.groq.com/docs/libraries
    """

    id: str = "llama3-groq-70b-8192-tool-use-preview"
    name: str = "Groq"
    provider: str = "Groq"

    # Request parameters
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    response_format: Optional[Dict[str, Any]] = None
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
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # Groq clients
    client: Optional[GroqClient] = None
    async_client: Optional[AsyncGroqClient] = None

    def get_client_params(self) -> Dict[str, Any]:
        self.api_key = self.api_key or getenv("GROQ_API_KEY")
        if not self.api_key:
            logger.error("GROQ_API_KEY not set. Please set the GROQ_API_KEY environment variable.")

        client_params: Dict[str, Any] = {}
        if self.api_key:
            client_params["api_key"] = self.api_key
        if self.base_url:
            client_params["base_url"] = self.base_url
        if self.timeout:
            client_params["timeout"] = self.timeout
        if self.max_retries:
            client_params["max_retries"] = self.max_retries
        if self.default_headers:
            client_params["default_headers"] = self.default_headers
        if self.default_query:
            client_params["default_query"] = self.default_query
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> GroqClient:
        """
        Returns a Groq client.

        Returns:
            GroqClient: An instance of the Groq client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self.get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client

        self.client = GroqClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncGroqClient:
        """
        Returns an asynchronous Groq client.

        Returns:
            AsyncGroqClient: An instance of the asynchronous Groq client.
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
        return AsyncGroqClient(**client_params)

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        request_params: Dict[str, Any] = {}
        if self.frequency_penalty:
            request_params["frequency_penalty"] = self.frequency_penalty
        if self.logit_bias:
            request_params["logit_bias"] = self.logit_bias
        if self.logprobs:
            request_params["logprobs"] = self.logprobs
        if self.max_tokens:
            request_params["max_tokens"] = self.max_tokens
        if self.presence_penalty:
            request_params["presence_penalty"] = self.presence_penalty
        if self.response_format:
            request_params["response_format"] = self.response_format
        if self.seed:
            request_params["seed"] = self.seed
        if self.stop:
            request_params["stop"] = self.stop
        if self.temperature:
            request_params["temperature"] = self.temperature
        if self.top_logprobs:
            request_params["top_logprobs"] = self.top_logprobs
        if self.top_p:
            request_params["top_p"] = self.top_p
        if self.user:
            request_params["user"] = self.user
        if self.extra_headers:
            request_params["extra_headers"] = self.extra_headers
        if self.extra_query:
            request_params["extra_query"] = self.extra_query
        if self.tools:
            request_params["tools"] = self.tools
            if self.tool_choice is None:
                request_params["tool_choice"] = "auto"
            else:
                request_params["tool_choice"] = self.tool_choice
        if self.request_params:
            request_params.update(self.request_params)
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
                "user": self.user,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
                "tools": self.tools,
                "tool_choice": self.tool_choice
                if (self.tools is not None and self.tool_choice is not None)
                else "auto",
            }
        )
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
            # TODO: Add audio support
            # if message.audio is not None:
            #     message = self.add_audio_to_message(message=message, audio=message.audio)

        return message.to_dict()

    def invoke(self, messages: List[Message]) -> ChatCompletion:
        """
        Send a chat completion request to the Groq API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        return self.get_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            **self.request_kwargs,
        )

    async def ainvoke(self, messages: List[Message]) -> ChatCompletion:
        """
        Sends an asynchronous chat completion request to the Groq API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        return await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            **self.request_kwargs,
        )

    def invoke_stream(self, messages: List[Message]) -> Iterator[ChatCompletionChunk]:
        """
        Send a streaming chat completion request to the Groq API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatCompletionChunk]: An iterator of chat completion chunks.
        """
        yield from self.get_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.request_kwargs,
        )

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Sends an asynchronous streaming chat completion request to the Groq API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """
        async_stream = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[self.format_message(m) for m in messages],  # type: ignore
            stream=True,
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
            if response_usage.completion_time is not None:
                metrics.completion_time = response_usage.completion_time
                assistant_message.metrics["completion_time"] = response_usage.completion_time
                self.metrics["completion_time"] = (
                    self.metrics.get("completion_time", 0) + response_usage.completion_time
                )
            if response_usage.prompt_time is not None:
                metrics.prompt_time = response_usage.prompt_time
                assistant_message.metrics["prompt_time"] = response_usage.prompt_time
                self.metrics["prompt_time"] = self.metrics.get("prompt_time", 0) + response_usage.prompt_time
            if response_usage.queue_time is not None:
                metrics.queue_time = response_usage.queue_time
                assistant_message.metrics["queue_time"] = response_usage.queue_time
                self.metrics["queue_time"] = self.metrics.get("queue_time", 0) + response_usage.queue_time
            if response_usage.total_time is not None:
                metrics.total_time = response_usage.total_time
                assistant_message.metrics["total_time"] = response_usage.total_time
                self.metrics["total_time"] = self.metrics.get("total_time", 0) + response_usage.total_time

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

        # Update metrics
        self.update_usage_metrics(assistant_message, metrics, response_usage)
        return assistant_message

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Generate a response from Groq.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response.
        """
        logger.debug("---------- Groq Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: ChatCompletion = self.invoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Parse response
        response_message: ChatCompletionMessage = response.choices[0].message
        response_usage: Optional[CompletionUsage] = response.usage

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
        logger.debug("---------- Groq Response End ----------")
        return model_response

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Generate an asynchronous response from Groq.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response from the API.
        """
        logger.debug("---------- Groq Async Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: ChatCompletion = await self.ainvoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Parse response
        response_message: ChatCompletionMessage = response.choices[0].message
        response_usage: Optional[CompletionUsage] = response.usage

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

        logger.debug("---------- Groq Async Response End ----------")
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
        if metrics.completion_time is not None:
            assistant_message.metrics["completion_time"] = metrics.completion_time
            self.metrics["completion_time"] = self.metrics.get("completion_time", 0) + metrics.completion_time
        if metrics.prompt_time is not None:
            assistant_message.metrics["prompt_time"] = metrics.prompt_time
            self.metrics["prompt_time"] = self.metrics.get("prompt_time", 0) + metrics.prompt_time
        if metrics.queue_time is not None:
            assistant_message.metrics["queue_time"] = metrics.queue_time
            self.metrics["queue_time"] = self.metrics.get("queue_time", 0) + metrics.queue_time
        if metrics.total_time is not None:
            assistant_message.metrics["total_time"] = metrics.total_time
            self.metrics["total_time"] = self.metrics.get("total_time", 0) + metrics.total_time

    def add_response_usage_to_metrics(self, metrics: Metrics, response_usage: CompletionUsage):
        metrics.input_tokens = response_usage.prompt_tokens
        metrics.prompt_tokens = response_usage.prompt_tokens
        metrics.output_tokens = response_usage.completion_tokens
        metrics.completion_tokens = response_usage.completion_tokens
        metrics.total_tokens = response_usage.total_tokens
        metrics.completion_time = response_usage.completion_time
        metrics.prompt_time = response_usage.prompt_time
        metrics.queue_time = response_usage.queue_time
        metrics.total_time = response_usage.total_time

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from Groq.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of model responses.
        """
        logger.debug("---------- Groq Response Start ----------")
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
                response_content: Optional[str] = response_delta.content
                response_tool_calls: Optional[List[ChoiceDeltaToolCall]] = response_delta.tool_calls

                if response_content is not None:
                    stream_data.response_content += response_content
                    yield ModelResponse(content=response_content)

                if response_tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_tool_calls)

            if response.usage is not None:
                self.add_response_usage_to_metrics(metrics=metrics, response_usage=response.usage)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

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
        logger.debug("---------- Groq Response End ----------")

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from Groq.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Any: An asynchronous iterator of model responses.
        """
        logger.debug("---------- Groq Async Response Start ----------")
        self._log_messages(messages)
        stream_data: StreamData = StreamData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        async for response in self.ainvoke_stream(messages=messages):
            if len(response.choices) > 0:
                metrics.completion_tokens += 1
                if metrics.completion_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

                response_delta: ChoiceDelta = response.choices[0].delta
                response_content = response_delta.content
                response_tool_calls = response_delta.tool_calls

                if response_content is not None:
                    stream_data.response_content += response_content
                    yield ModelResponse(content=response_content)

                if response_tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_tool_calls)

            if response.usage is not None:
                self.add_response_usage_to_metrics(metrics=metrics, response_usage=response.usage)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

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
        logger.debug("---------- Groq Async Response End ----------")

    def build_tool_calls(self, tool_calls_data: List[ChoiceDeltaToolCall]) -> List[Dict[str, Any]]:
        """
        Build tool calls from tool call data.

        Args:
            tool_calls_data (List[ChoiceDeltaToolCall]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        return self._build_tool_calls(tool_calls_data)
