from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from pydantic import BaseModel

from agno.models.base import Metrics, Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.tools.function import FunctionCall
from agno.utils.log import logger
from agno.utils.tools import get_function_call_for_tool_call

try:
    from huggingface_hub import (
        AsyncInferenceClient,
        ChatCompletionOutput,
        ChatCompletionOutputMessage,
        ChatCompletionOutputUsage,
        ChatCompletionStreamOutput,
        ChatCompletionStreamOutputDelta,
        ChatCompletionStreamOutputDeltaToolCall,
        InferenceClient,
    )
except (ModuleNotFoundError, ImportError):
    raise ImportError("`huggingface_hub` not installed. Please install using `pip install huggingface_hub`")


@dataclass
class StreamData:
    response_content: str = ""
    response_tool_calls: Optional[List[ChatCompletionStreamOutputDeltaToolCall]] = None


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
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # HuggingFace Hub Inference clients
    client: Optional[InferenceClient] = None
    async_client: Optional[AsyncInferenceClient] = None

    def get_client_params(self) -> Dict[str, Any]:
        self.api_key = self.api_key or getenv("HF_TOKEN")
        if not self.api_key:
            logger.error("HF_TOKEN not set. Please set the HF_TOKEN environment variable.")

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
        if self.http_client is not None:
            _client_params["http_client"] = self.http_client
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

        if self.http_client:
            _client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            _client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )
        return AsyncInferenceClient(**_client_params)

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
        if self.response_format is not None:
            _request_params["response_format"] = self.response_format
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
        if self.tools is not None:
            _request_params["tools"] = self.tools
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
                "tools": self.tools,
                "tool_choice": self.tool_choice
                if (self.tools is not None and self.tool_choice is not None)
                else "auto",
            }
        )
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

    def invoke(self, messages: List[Message]) -> Union[ChatCompletionOutput]:
        """
        Send a chat completion request to the HuggingFace Hub.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletionOutput: The chat completion response from the Inference Client.
        """
        return self.get_client().chat.completions.create(
            model=self.id,
            messages=[m.to_dict() for m in messages],
            **self.request_kwargs,
        )

    async def ainvoke(self, messages: List[Message]) -> Union[ChatCompletionOutput]:
        """
        Sends an asynchronous chat completion request to the HuggingFace Hub Inference.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletionOutput: The chat completion response from the Inference Client.
        """
        return await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[m.to_dict() for m in messages],
            **self.request_kwargs,
        )

    def invoke_stream(self, messages: List[Message]) -> Iterator[ChatCompletionStreamOutput]:
        """
        Send a streaming chat completion request to the HuggingFace API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatCompletionStreamOutput]: An iterator of chat completion delta.
        """
        yield from self.get_client().chat.completions.create(
            model=self.id,
            messages=[m.to_dict() for m in messages],  # type: ignore
            stream=True,
            stream_options={"include_usage": True},
            **self.request_kwargs,
        )  # type: ignore

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Sends an asynchronous streaming chat completion request to the HuggingFace API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """
        async_stream = await self.get_async_client().chat.completions.create(
            model=self.id,
            messages=[m.to_dict() for m in messages],
            stream=True,
            stream_options={"include_usage": True},
            **self.request_kwargs,
        )
        async for chunk in async_stream:  # type: ignore
            yield chunk

    def _handle_tool_calls(
        self, assistant_message: Message, messages: List[Message], model_response: ModelResponse
    ) -> Optional[ModelResponse]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[ModelResponse]: The model response after handling tool calls.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            model_response.content = ""
            tool_role: str = "tool"
            function_calls_to_run: List[FunctionCall] = []
            function_call_results: List[Message] = []
            for tool_call in assistant_message.tool_calls:
                _tool_call_id = tool_call.get("id")
                _function_call = get_function_call_for_tool_call(tool_call, self._functions)
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

    def _update_usage_metrics(
        self, assistant_message: Message, metrics: Metrics, response_usage: Optional[ChatCompletionOutputUsage]
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

    def _create_assistant_message(
        self,
        response_message: ChatCompletionOutputMessage,
        metrics: Metrics,
        response_usage: Optional[ChatCompletionOutputUsage],
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
            assistant_message.tool_calls = [t.model_dump() for t in response_message.tool_calls]

        return assistant_message

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Generate a response from HuggingFace Hub.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response.
        """
        logger.debug("---------- HuggingFace Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: Union[ChatCompletionOutput] = self.invoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Parse response
        response_message: ChatCompletionOutputMessage = response.choices[0].message
        response_usage: Optional[ChatCompletionOutputUsage] = response.usage

        # -*- Create assistant message
        assistant_message = self._create_assistant_message(
            response_message=response_message, metrics=metrics, response_usage=response_usage
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if self._handle_tool_calls(assistant_message, messages, model_response):
            response_after_tool_calls = self.response(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Update model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- HuggingFace Response End ----------")
        return model_response

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Generate an asynchronous response from HuggingFace.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            ModelResponse: The model response from the API.
        """
        logger.debug("---------- HuggingFace Async Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response: Union[ChatCompletionOutput] = await self.ainvoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Parse response
        response_message: ChatCompletionOutputMessage = response.choices[0].message
        response_usage: Optional[ChatCompletionOutputUsage] = response.usage

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
        assistant_message = self._create_assistant_message(
            response_message=response_message, metrics=metrics, response_usage=response_usage
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if self._handle_tool_calls(assistant_message, messages, model_response):
            response_after_tool_calls = await self.aresponse(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Update model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- HuggingFace Async Response End ----------")
        return model_response

    def _update_stream_metrics(self, assistant_message: Message, metrics: Metrics):
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

    def _handle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
    ) -> Iterator[ModelResponse]:
        """
        Handle tool calls for response stream.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of the model response.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            tool_role: str = "tool"
            function_calls_to_run: List[FunctionCall] = []
            function_call_results: List[Message] = []
            for tool_call in assistant_message.tool_calls:
                _tool_call_id = tool_call.get("id")
                _function_call = get_function_call_for_tool_call(tool_call, self._functions)
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

            for intermediate_model_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                yield intermediate_model_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from HuggingFace Hub.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of model responses.
        """
        logger.debug("---------- HuggingFace Response Start ----------")
        self._log_messages(messages)
        stream_data: StreamData = StreamData()

        # -*- Generate response
        for response in self.invoke_stream(messages=messages):
            if len(response.choices) > 0:
                # metrics.completion_tokens += 1

                response_delta: ChatCompletionStreamOutputDelta = response.choices[0].delta
                response_content: Optional[str] = response_delta.content
                response_tool_calls: Optional[List[ChatCompletionStreamOutputDeltaToolCall]] = response_delta.tool_calls

                if response_content is not None:
                    stream_data.response_content += response_content
                    yield ModelResponse(content=response_content)

                if response_tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_tool_calls)

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

        if stream_data.response_tool_calls is not None:
            _tool_calls = self._build_tool_calls(stream_data.response_tool_calls)
            if len(_tool_calls) > 0:
                assistant_message.tool_calls = _tool_calls

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self._handle_stream_tool_calls(assistant_message, messages)
            yield from self.response_stream(messages=messages)
        logger.debug("---------- HuggingFace Response End ----------")

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from HuggingFace Hub.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Any: An asynchronous iterator of model responses.
        """
        logger.debug("---------- HuggingFace Hub Async Response Start ----------")
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

                response_delta: ChatCompletionStreamOutputDelta = response.choices[0].delta
                response_content = response_delta.content
                response_tool_calls = response_delta.tool_calls

                if response_content is not None:
                    stream_data.response_content += response_content
                    yield ModelResponse(content=response_content)

                if response_tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_tool_calls)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role="assistant")
        if stream_data.response_content != "":
            assistant_message.content = stream_data.response_content

        if stream_data.response_tool_calls is not None:
            _tool_calls = self._build_tool_calls(stream_data.response_tool_calls)
            if len(_tool_calls) > 0:
                assistant_message.tool_calls = _tool_calls

        self._update_stream_metrics(assistant_message=assistant_message, metrics=metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            for model_response in self._handle_stream_tool_calls(assistant_message, messages):
                yield model_response
            async for model_response in self.aresponse_stream(messages=messages):
                yield model_response
        logger.debug("---------- HuggingFace Hub Async Response End ----------")
