from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

from agno.media import Image
from agno.models.base import Metrics, Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.utils.log import logger

try:
    from mistralai import Mistral as MistralClient
    from mistralai import UsageInfo
    from mistralai.models import AssistantMessage, ImageURLChunk, SystemMessage, TextChunk, ToolMessage, UserMessage
    from mistralai.models.chatcompletionresponse import ChatCompletionResponse
    from mistralai.models.deltamessage import DeltaMessage
    from mistralai.types.basemodel import Unset

    MistralMessage = Union[UserMessage, AssistantMessage, SystemMessage, ToolMessage]

except (ModuleNotFoundError, ImportError):
    raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")


@dataclass
class MessageData:
    response_content: str = ""
    response_usage: Optional[UsageInfo] = None
    response_tool_calls: Optional[List[Any]] = None


def _format_image_for_message(image: Image) -> Optional[ImageURLChunk]:
    # Case 1: Image is a URL
    if image.url is not None:
        return ImageURLChunk(image_url=image.url)
    # Case 2: Image is a local file path
    elif image.filepath is not None:
        import base64
        from pathlib import Path

        path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
        if not path.exists() or not path.is_file():
            logger.error(f"Image file not found: {image}")
            raise FileNotFoundError(f"Image file not found: {image}")

        with open(image.filepath, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            return ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}")

    # Case 3: Image is a bytes object
    elif image.content is not None:
        import base64

        base64_image = base64.b64encode(image.content).decode("utf-8")
        return ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}")
    return None


def _format_messages(messages: List[Message]) -> List[MistralMessage]:
    mistral_messages: List[MistralMessage] = []
    for message in messages:
        mistral_message: MistralMessage
        if message.role == "user":
            if message.images is not None:
                content: List[Any] = [TextChunk(type="text", text=message.content)]
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)
                mistral_message = UserMessage(role="user", content=content)
            else:
                mistral_message = UserMessage(role="user", content=message.content)
        elif message.role == "assistant":
            if message.tool_calls is not None:
                mistral_message = AssistantMessage(
                    role="assistant", content=message.content, tool_calls=message.tool_calls
                )
            else:
                mistral_message = AssistantMessage(role=message.role, content=message.content)
        elif message.role == "system":
            mistral_message = SystemMessage(role="system", content=message.content)
        elif message.role == "tool":
            mistral_message = ToolMessage(name="tool", content=message.content, tool_call_id=message.tool_call_id)
        else:
            raise ValueError(f"Unknown role: {message.role}")
        mistral_messages.append(mistral_message)
    return mistral_messages


@dataclass
class MistralChat(Model):
    """
    MistralChat is a model that uses the Mistral API to generate responses to messages.

    Args:
        id (str): The ID of the model.
        name (str): The name of the model.
        provider (str): The provider of the model.
        temperature (Optional[float]): The temperature of the model.
        max_tokens (Optional[int]): The maximum number of tokens to generate.
        top_p (Optional[float]): The top p of the model.
        random_seed (Optional[int]): The random seed of the model.
        safe_mode (bool): The safe mode of the model.
        safe_prompt (bool): The safe prompt of the model.
        response_format (Optional[Union[Dict[str, Any], ChatCompletionResponse]]): The response format of the model.
        request_params (Optional[Dict[str, Any]]): The request parameters of the model.
        api_key (Optional[str]): The API key of the model.
        endpoint (Optional[str]): The endpoint of the model.
        max_retries (Optional[int]): The maximum number of retries of the model.
        timeout (Optional[int]): The timeout of the model.
        client_params (Optional[Dict[str, Any]]): The client parameters of the model.
        mistral_client (Optional[Mistral]): The Mistral client of the model.
    """

    id: str = "mistral-large-latest"
    name: str = "MistralChat"
    provider: str = "Mistral"

    # -*- Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    random_seed: Optional[int] = None
    safe_mode: bool = False
    safe_prompt: bool = False
    response_format: Optional[Union[Dict[str, Any], ChatCompletionResponse]] = None
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    max_retries: Optional[int] = None
    timeout: Optional[int] = None
    client_params: Optional[Dict[str, Any]] = None
    # -*- Provide the Mistral Client manually
    mistral_client: Optional[MistralClient] = None

    def get_client(self) -> MistralClient:
        """
        Get the Mistral client.

        Returns:
            MistralClient: The Mistral client instance.
        """
        if self.mistral_client:
            return self.mistral_client

        _client_params = self._get_client_params()
        self.mistral_client = MistralClient(**_client_params)
        return self.mistral_client

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get the client parameters for initializing Mistral clients.

        Returns:
            Dict[str, Any]: The client parameters.
        """
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("MISTRAL_API_KEY")
        if not self.api_key:
            logger.error("MISTRAL_API_KEY not set. Please set the MISTRAL_API_KEY environment variable.")

        client_params.update(
            {
                "api_key": self.api_key,
                "endpoint": self.endpoint,
                "max_retries": self.max_retries,
                "timeout": self.timeout,
            }
        )

        if self.client_params is not None:
            client_params.update(self.client_params)

        # Remove None values
        return {k: v for k, v in client_params.items() if v is not None}

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Get the API kwargs for the Mistral model.

        Returns:
            Dict[str, Any]: The API kwargs.
        """
        _request_params: Dict[str, Any] = {}
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.random_seed:
            _request_params["random_seed"] = self.random_seed
        if self.safe_mode:
            _request_params["safe_mode"] = self.safe_mode
        if self.safe_prompt:
            _request_params["safe_prompt"] = self.safe_prompt
        if self.tools:
            _request_params["tools"] = self.tools
            if self.tool_choice is None:
                _request_params["tool_choice"] = "auto"
            else:
                _request_params["tool_choice"] = self.tool_choice
        if self.request_params:
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
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "random_seed": self.random_seed,
                "safe_mode": self.safe_mode,
                "safe_prompt": self.safe_prompt,
                "response_format": self.response_format,
            }
        )
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

    def invoke(self, messages: List[Message]) -> ChatCompletionResponse:
        """
        Send a chat completion request to the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            ChatCompletionResponse: The response from the model.
        """
        mistral_messages = _format_messages(messages)
        response = self.get_client().chat.complete(
            model=self.id,
            messages=mistral_messages,
            **self.request_kwargs,
        )
        if response is None:
            raise ValueError("Chat completion returned None")
        return response

    def invoke_stream(self, messages: List[Message]) -> Iterator[Any]:
        """
        Stream the response from the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            Iterator[Any]: The streamed response.
        """
        mistral_messages = _format_messages(messages)
        stream = self.get_client().chat.stream(
            model=self.id,
            messages=mistral_messages,
            **self.request_kwargs,
        )
        if stream is None:
            raise ValueError("Chat stream returned None")
        return stream

    async def ainvoke(self, messages: List[Message]) -> ChatCompletionResponse:
        """
        Send an asynchronous chat completion request to the Mistral API.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            ChatCompletionResponse: The response from the model.
        """
        mistral_messages = _format_messages(messages)
        response = await self.get_client().chat.complete_async(
            model=self.id,
            messages=mistral_messages,
            **self.request_kwargs,
        )
        if response is None:
            raise ValueError("Chat completion returned None")
        return response

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Stream an asynchronous response from the Mistral API.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            Any: The streamed response.
        """
        mistral_messages = _format_messages(messages)
        stream = await self.get_client().chat.stream_async(
            model=self.id,
            messages=mistral_messages,
            **self.request_kwargs,
        )
        if stream is None:
            raise ValueError("Chat stream returned None")
        return stream

    def _handle_tool_calls(
        self, assistant_message: Message, messages: List[Message], model_response: ModelResponse
    ) -> Optional[ModelResponse]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The messages to send to the model.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[ModelResponse]: The model response after handling tool calls.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            if model_response.tool_calls is None:
                model_response.tool_calls = []
            model_response.content = ""
            tool_role: str = "tool"

            function_calls_to_run, function_call_results = self._prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
            )

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            return model_response
        return None

    def _create_assistant_message(self, response: ChatCompletionResponse, metrics: Metrics) -> Message:
        """
        Create an assistant message from the response.

        Args:
            response (ChatCompletionResponse): The response from the model.

        Returns:
            Message: The assistant message.
        """
        if response.choices is None or len(response.choices) == 0:
            raise ValueError("The response does not contain any choices.")

        response_message: AssistantMessage = response.choices[0].message

        # Create assistant message
        assistant_message = Message(
            role=response_message.role or "assistant",
            content=response_message.content,
        )

        if isinstance(response_message.tool_calls, list) and len(response_message.tool_calls) > 0:
            for tool_call in response_message.tool_calls:
                if not assistant_message.tool_calls:
                    assistant_message.tool_calls = []
                assistant_message.tool_calls.append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )

        # -*- Update usage metrics
        self._update_usage_metrics(assistant_message, response.usage, metrics)

        return assistant_message

    def _update_usage_metrics(
        self,
        assistant_message: Message,
        usage: Optional[UsageInfo],
        metrics: Metrics,
    ) -> None:
        """
        Update the usage metrics for the response.

        Args:
            assistant_message (Message): The assistant message.
            response (ChatCompletionResponse): The response from the model.
            response_timer (Timer): The timer for the response.
        """
        if usage:
            metrics.input_tokens = usage.prompt_tokens or 0
            metrics.output_tokens = usage.completion_tokens or 0
            metrics.total_tokens = metrics.total_tokens or 0

        self._update_model_metrics(metrics_for_run=metrics)
        self._update_assistant_message_metrics(assistant_message=assistant_message, metrics_for_run=metrics)

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Send a chat completion request to the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            ModelResponse: The response from the model.
        """
        logger.debug("---------- Mistral Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        metrics.start_response_timer()
        response: ChatCompletionResponse = self.invoke(messages=messages)
        metrics.stop_response_timer()
        logger.debug(f"Time to generate response: {metrics.response_timer.elapsed:.4f}s")

        # -*- Ensure response.choices is not None
        if response.choices is None or len(response.choices) == 0:
            raise ValueError("Chat completion response has no choices")

        # -*- Create assistant message
        assistant_message = self._create_assistant_message(response=response, metrics=metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)
        assistant_message.log()

        # -*- Handle tool calls
        if self._handle_tool_calls(assistant_message, messages, model_response):
            response_after_tool_calls = self.response(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Add content to model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- Mistral Response End ----------")
        return model_response

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Stream the response from the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            Iterator[ModelResponse]: The streamed response.
        """
        logger.debug("---------- Mistral Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)
        metrics = Metrics()
        message_data = MessageData()

        metrics.start_response_timer()

        assistant_message_role = None
        for response in self.invoke_stream(messages=messages):
            # -*- Parse response
            response_delta: DeltaMessage = response.data.choices[0].delta
            if assistant_message_role is None and response_delta.role is not None:
                assistant_message_role = response_delta.role

            response_content: Optional[str] = None
            if (
                response_delta.content is not None
                and not isinstance(response_delta.content, Unset)
                and isinstance(response_delta.content, str)
            ):
                response_content = response_delta.content
            response_tool_calls = response_delta.tool_calls

            # -*- Return content if present, otherwise get tool call
            if response_content is not None:
                message_data.response_content += response_content
                if response.data.usage is not None:
                    metrics.input_tokens += response.data.usage.prompt_tokens
                    metrics.output_tokens += response.data.usage.completion_tokens
                    metrics.total_tokens += response.data.usage.total_tokens
                    if metrics.time_to_first_token is None:
                        metrics.time_to_first_token = metrics.response_timer.elapsed
                        logger.debug(f"Time to first token: {metrics.time_to_first_token:.4f}s")
                yield ModelResponse(content=response_content)

            # -*- Parse tool calls
            if response_tool_calls is not None:
                if message_data.response_tool_calls is None:
                    message_data.response_tool_calls = []
                message_data.response_tool_calls.extend(response_tool_calls)

        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role=(assistant_message_role or "assistant"))
        if message_data.response_content != "":
            assistant_message.content = message_data.response_content

        # -*- Add tool calls to assistant message

        if message_data.response_tool_calls is not None:
            for tool_call in message_data.response_tool_calls:
                if not assistant_message.tool_calls:
                    assistant_message.tool_calls = []
                assistant_message.tool_calls.append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )

        # -*- Update usage metrics
        self._update_usage_metrics(assistant_message, message_data.response_usage, metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log assistant message
        assistant_message.log()
        metrics.log()

        # -*- Parse and run tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self.handle_stream_tool_calls(assistant_message, messages)
            yield from self.response_stream(messages=messages)
        logger.debug("---------- Mistral Response End ----------")

    def handle_stream_tool_calls(self, assistant_message: Message, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The messages to send to the model.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield ModelResponse(content="\n\n")
            function_calls_to_run = self._get_function_calls_to_run(assistant_message, messages)
            function_call_results: List[Message] = []

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f" - Running: {function_calls_to_run[0].get_call_str()}\n\n")
                elif len(function_calls_to_run) > 1:
                    yield ModelResponse(content="Running:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            for intermediate_model_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                yield intermediate_model_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

    async def ahandle_stream_tool_calls(self, assistant_message: Message, messages: List[Message]) -> Any:
        """
        Handle tool calls in the assistant message asynchronously.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The messages to send to the model.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield ModelResponse(content="\n\n")
            function_calls_to_run = self._get_function_calls_to_run(assistant_message, messages)
            function_call_results: List[Message] = []

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f" - Running: {function_calls_to_run[0].get_call_str()}\n\n")
                elif len(function_calls_to_run) > 1:
                    yield ModelResponse(content="Running:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            async for intermediate_model_response in self.arun_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                yield intermediate_model_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Send an asynchronous chat completion request to the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            ModelResponse: The response from the model.
        """
        logger.debug("---------- Mistral Async Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        metrics.start_response_timer()
        response: ChatCompletionResponse = await self.ainvoke(messages=messages)
        metrics.stop_response_timer()
        logger.debug(f"Time to generate response: {metrics.response_timer.elapsed:.4f}s")

        # -*- Ensure response.choices is not None
        if response.choices is None or len(response.choices) == 0:
            raise ValueError("Chat completion response has no choices")

        # -*- Create assistant message
        assistant_message = self._create_assistant_message(response=response, metrics=metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)
        assistant_message.log()

        # -*- Handle tool calls
        if await self._ahandle_tool_calls(assistant_message, messages, model_response):
            response_after_tool_calls = await self.aresponse(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Add content to model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- Mistral Async Response End ----------")
        return model_response

    async def _ahandle_tool_calls(
        self, assistant_message: Message, messages: List[Message], model_response: ModelResponse
    ) -> Optional[ModelResponse]:
        """
        Handle tool calls in the assistant message asynchronously.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The messages to send to the model.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[ModelResponse]: The model response after handling tool calls.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            if model_response.tool_calls is None:
                model_response.tool_calls = []
            model_response.content = ""
            tool_role: str = "tool"
            function_calls_to_run, function_call_results = self._prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
            )

            async for function_call_response in self.arun_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            return model_response
        return None

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from the Mistral API.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            Any: An asynchronous iterator of model responses.
        """
        logger.debug("---------- Mistral Async Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)
        metrics = Metrics()
        message_data = MessageData()

        metrics.start_response_timer()

        assistant_message_role = None
        stream = await self.ainvoke_stream(messages=messages)
        async for response in stream:
            # -*- Parse response
            response_delta: DeltaMessage = response.data.choices[0].delta
            if assistant_message_role is None and response_delta.role is not None:
                assistant_message_role = response_delta.role

            response_content: Optional[str] = None
            if (
                response_delta.content is not None
                and not isinstance(response_delta.content, Unset)
                and isinstance(response_delta.content, str)
            ):
                response_content = response_delta.content
            response_tool_calls = response_delta.tool_calls

            # -*- Return content if present, otherwise get tool call
            if response_content is not None:
                message_data.response_content += response_content
                if response.data.usage is not None:
                    metrics.input_tokens += response.data.usage.prompt_tokens
                    metrics.output_tokens += response.data.usage.completion_tokens
                    metrics.total_tokens += response.data.usage.total_tokens

                if metrics.time_to_first_token is None:
                    metrics.time_to_first_token = metrics.response_timer.elapsed
                    logger.debug(f"Time to first token: {metrics.time_to_first_token:.4f}s")
                yield ModelResponse(content=response_content)

            # -*- Parse tool calls
            if response_tool_calls is not None:
                if message_data.response_tool_calls is None:
                    message_data.response_tool_calls = []
                message_data.response_tool_calls.extend(response_tool_calls)

        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role=(assistant_message_role or "assistant"))
        if message_data.response_content != "":
            assistant_message.content = message_data.response_content

        # -*- Add tool calls to assistant message
        if message_data.response_tool_calls is not None:
            for tool_call in message_data.response_tool_calls:
                if not assistant_message.tool_calls:
                    assistant_message.tool_calls = []
                assistant_message.tool_calls.append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )

        # -*- Update usage metrics
        self._update_usage_metrics(assistant_message, message_data.response_usage, metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Parse and run tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            async for tool_call_response in self.ahandle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages
            ):
                yield tool_call_response

            async for response in self.aresponse_stream(messages=messages):
                yield response

        logger.debug("---------- Mistral Async Response End ----------")
