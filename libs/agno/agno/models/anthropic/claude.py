import json
from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from agno.media import Image
from agno.models.base import Metrics, Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.utils.log import logger

try:
    from anthropic import Anthropic as AnthropicClient
    from anthropic import AsyncAnthropic as AsyncAnthropicClient
    from anthropic.lib.streaming._types import (
        ContentBlockStopEvent,
        MessageStopEvent,
        RawContentBlockDeltaEvent,
    )
    from anthropic.types import Message as AnthropicMessage
    from anthropic.types import TextBlock, TextDelta, ToolUseBlock, Usage
except (ModuleNotFoundError, ImportError):
    raise ImportError("`anthropic` not installed. Please install using `pip install anthropic`")


@dataclass
class MessageData:
    response_content: str = ""
    response_block: List[Union[TextBlock, ToolUseBlock]] = field(default_factory=list)
    response_block_content: Optional[Union[TextBlock, ToolUseBlock]] = None
    response_usage: Optional[Usage] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_ids: List[str] = field(default_factory=list)


def _format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    """
    Add an image to a message by converting it to base64 encoded format.
    """
    import base64
    import imghdr

    type_mapping = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}

    try:
        # Case 1: Image is a URL
        if image.url is not None:
            content_bytes = image.image_url_content

        # Case 2: Image is a local file path
        elif image.filepath is not None:
            from pathlib import Path

            path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
            if path.exists() and path.is_file():
                with open(image.filepath, "rb") as f:
                    content_bytes = f.read()
            else:
                logger.error(f"Image file not found: {image}")
                return None

        # Case 3: Image is a bytes object
        elif image.content is not None:
            content_bytes = image.content

        else:
            logger.error(f"Unsupported image type: {type(image)}")
            return None

        img_type = imghdr.what(None, h=content_bytes)  # type: ignore
        if not img_type:
            logger.error("Unable to determine image type")
            return None

        media_type = type_mapping.get(img_type)
        if not media_type:
            logger.error(f"Unsupported image type: {img_type}")
            return None

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(content_bytes).decode("utf-8"),  # type: ignore
            },
        }

    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return None


def _format_messages(messages: List[Message]) -> Tuple[List[Dict[str, str]], str]:
    """
    Process the list of messages and separate them into API messages and system messages.

    Args:
        messages (List[Message]): The list of messages to process.

    Returns:
        Tuple[List[Dict[str, str]], str]: A tuple containing the list of API messages and the concatenated system messages.
    """
    chat_messages: List[Dict[str, str]] = []
    system_messages: List[str] = []

    for idx, message in enumerate(messages):
        content = message.content or ""
        if message.role == "system" or (message.role != "user" and idx in [0, 1]):
            if content is not None:
                system_messages.append(content)  # type: ignore
            continue
        elif message.role == "user":
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if message.images is not None:
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)

        # Handle tool calls from history
        elif message.role == "assistant" and isinstance(message.content, str) and message.tool_calls:
            if message.content:
                content = [TextBlock(text=message.content, type="text")]
            else:
                content = []
            for tool_call in message.tool_calls:
                content.append(
                    ToolUseBlock(
                        id=tool_call["id"],
                        input=json.loads(tool_call["function"]["arguments"])
                        if "arguments" in tool_call["function"]
                        else {},
                        name=tool_call["function"]["name"],
                        type="tool_use",
                    )
                )

        chat_messages.append({"role": message.role, "content": content})  # type: ignore
    return chat_messages, " ".join(system_messages)


@dataclass
class Claude(Model):
    """
    A class representing Anthropic Claude model.

    For more information, see: https://docs.anthropic.com/en/api/messages
    """

    id: str = "claude-3-5-sonnet-20241022"
    name: str = "Claude"
    provider: str = "Anthropic"

    # Request parameters
    max_tokens: Optional[int] = 1024
    temperature: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Anthropic clients
    client: Optional[AnthropicClient] = None
    async_client: Optional[AsyncAnthropicClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.error("ANTHROPIC_API_KEY not set. Please set the ANTHROPIC_API_KEY environment variable.")

        client_params.update(
            {
                "api_key": self.api_key,
            }
        )
        if self.client_params is not None:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> AnthropicClient:
        """
        Returns an instance of the Anthropic client.
        """
        if self.client:
            return self.client

        _client_params = self._get_client_params()
        self.client = AnthropicClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAnthropicClient:
        """
        Returns an instance of the async Anthropic client.
        """
        if self.async_client:
            return self.async_client

        _client_params = self._get_client_params()
        self.async_client = AsyncAnthropicClient(**_client_params)
        return self.async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
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

    def prepare_request_kwargs(self, system_message: str) -> Dict[str, Any]:
        """
        Prepare the request keyword arguments for the API call.

        Args:
            system_message (str): The concatenated system messages.

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        request_kwargs = self.request_kwargs.copy()
        request_kwargs["system"] = system_message

        if self.tools:
            request_kwargs["tools"] = self.format_tools_for_model()
        return request_kwargs

    def format_tools_for_model(self) -> Optional[List[Dict[str, Any]]]:
        """
        Transforms function definitions into a format accepted by the Anthropic API.

        Returns:
            Optional[List[Dict[str, Any]]]: A list of tools formatted for the API, or None if no functions are defined.
        """
        if not self._functions:
            return None

        tools: List[Dict[str, Any]] = []
        for func_name, func_def in self._functions.items():
            parameters: Dict[str, Any] = func_def.parameters or {}
            properties: Dict[str, Any] = parameters.get("properties", {})
            required_params: List[str] = []

            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "")
                param_type_list: List[str] = [param_type] if isinstance(param_type, str) else param_type or []

                if "null" not in param_type_list:
                    required_params.append(param_name)

            input_properties: Dict[str, Dict[str, Union[str, List[str]]]] = {
                param_name: {
                    "type": param_info.get("type", ""),
                    "description": param_info.get("description", ""),
                }
                for param_name, param_info in properties.items()
            }

            tool = {
                "name": func_name,
                "description": func_def.description or "",
                "input_schema": {
                    "type": parameters.get("type", "object"),
                    "properties": input_properties,
                    "required": required_params,
                },
            }
            tools.append(tool)
        return tools

    def invoke(self, messages: List[Message]) -> AnthropicMessage:
        """
        Send a request to the Anthropic API to generate a response.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AnthropicMessage: The response from the model.
        """
        chat_messages, system_message = _format_messages(messages)
        request_kwargs = self.prepare_request_kwargs(system_message)

        return self.get_client().messages.create(
            model=self.id,
            messages=chat_messages,  # type: ignore
            **request_kwargs,
        )

    def invoke_stream(self, messages: List[Message]) -> Any:
        """
        Stream a response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.
        """
        chat_messages, system_message = _format_messages(messages)
        request_kwargs = self.prepare_request_kwargs(system_message)

        return self.get_client().messages.stream(
            model=self.id,
            messages=chat_messages,  # type: ignore
            **request_kwargs,
        )

    def update_usage_metrics(
        self,
        assistant_message: Message,
        usage: Optional[Usage] = None,
        metrics: Metrics = Metrics(),
    ) -> None:
        """
        Update the usage metrics for the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            usage (Optional[Usage]): The usage metrics returned by the model.
            metrics (Metrics): The metrics to update.
        """
        if usage:
            metrics.input_tokens = usage.input_tokens or 0
            metrics.output_tokens = usage.output_tokens or 0
            metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        self._update_model_metrics(metrics_for_run=metrics)
        self._update_assistant_message_metrics(assistant_message=assistant_message, metrics_for_run=metrics)

    def create_assistant_message(self, response: AnthropicMessage, metrics: Metrics) -> Tuple[Message, str, List[str]]:
        """
        Create an assistant message from the response.

        Args:
            response (AnthropicMessage): The response from the model.
            metrics (Metrics): The metrics for the response.

        Returns:
            Tuple[Message, str, List[str]]: A tuple containing the assistant message, the response content, and the tool ids.
        """
        message_data = MessageData()

        if response.content:
            message_data.response_block = response.content
            message_data.response_block_content = response.content[0]
            message_data.response_usage = response.usage

        # -*- Extract response content
        if message_data.response_block_content is not None:
            if isinstance(message_data.response_block_content, TextBlock):
                message_data.response_content = message_data.response_block_content.text
            elif isinstance(message_data.response_block_content, ToolUseBlock):
                tool_block_input = message_data.response_block_content.input
                if tool_block_input and isinstance(tool_block_input, dict):
                    message_data.response_content = tool_block_input.get("query", "")

        # -*- Extract tool calls from the response
        if response.stop_reason == "tool_use":
            for block in message_data.response_block:
                if isinstance(block, ToolUseBlock):
                    tool_use: ToolUseBlock = block
                    tool_name = tool_use.name
                    tool_input = tool_use.input
                    message_data.tool_ids.append(tool_use.id)

                    function_def = {"name": tool_name}
                    if tool_input:
                        function_def["arguments"] = json.dumps(tool_input)
                    message_data.tool_calls.append(
                        {
                            "id": tool_use.id,
                            "type": "function",
                            "function": function_def,
                        }
                    )

        # -*- Create assistant message
        assistant_message = Message(
            role=response.role or "assistant",
            content=message_data.response_content,
        )

        # -*- Update assistant message if tool calls are present
        if len(message_data.tool_calls) > 0:
            assistant_message.tool_calls = message_data.tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(assistant_message, message_data.response_usage, metrics)

        return assistant_message, message_data.response_content, message_data.tool_ids

    def format_function_call_results(
        self, function_call_results: List[Message], tool_ids: List[str], messages: List[Message]
    ) -> None:
        """
        Handle the results of function calls.

        Args:
            function_call_results (List[Message]): The results of the function calls.
            tool_ids (List[str]): The tool ids.
            messages (List[Message]): The list of conversation messages.
        """
        if len(function_call_results) > 0:
            fc_responses: List = []
            for _fc_message_index, _fc_message in enumerate(function_call_results):
                fc_responses.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_ids[_fc_message_index],
                        "content": _fc_message.content,
                    }
                )
            messages.append(Message(role="user", content=fc_responses))

    def handle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        tool_ids: List[str],
    ) -> Optional[ModelResponse]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): A list of messages.
            model_response [ModelResponse]: The model response.
            tool_ids (List[str]): The tool ids.

        Returns:
            Optional[ModelResponse]: The model response.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            function_calls_to_run, function_call_results = self._prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
            )

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run,
                function_call_results=function_call_results,
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)  # type: ignore  # model_response.tool_calls are initialized before calling this method

            self.format_function_call_results(function_call_results, tool_ids, messages)

            return model_response
        return None

    async def ahandle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        tool_ids: List[str],
    ) -> Optional[ModelResponse]:
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            function_calls_to_run, function_call_results = self._prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
            )

            async for function_call_response in self.arun_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role="tool"
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)  # type: ignore  # model_response.tool_calls are initialized before calling this method

            self.format_function_call_results(function_call_results, tool_ids, messages)

            return model_response
        return None

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Send a chat completion request to the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ModelResponse: The response from the model.
        """
        logger.debug("---------- Claude Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics_for_run = Metrics()

        metrics_for_run.start_response_timer()
        response: AnthropicMessage = self.invoke(messages=messages)
        metrics_for_run.stop_response_timer()

        # -*- Create assistant message
        assistant_message, response_content, tool_ids = self.create_assistant_message(
            response=response, metrics=metrics_for_run
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics_for_run.log()

        # -*- Handle tool calls
        if self.handle_tool_calls(assistant_message, messages, model_response, tool_ids) is not None:
            response_after_tool_calls = self.response(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Update model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- Claude Response End ----------")
        return model_response

    def handle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        tool_ids: List[str],
    ) -> Iterator[ModelResponse]:
        """
        Parse and run function calls from the assistant message.

        Args:
            assistant_message (Message): The assistant message containing tool calls.
            messages (List[Message]): The list of conversation messages.
            tool_ids (List[str]): The list of tool IDs.

        Yields:
            Iterator[ModelResponse]: Yields model responses during function execution.
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

            self.format_function_call_results(function_call_results, tool_ids, messages)

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        logger.debug("---------- Claude Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response = self.invoke_stream(messages=messages)
        with response as stream:
            for delta in stream:
                if isinstance(delta, RawContentBlockDeltaEvent):
                    if isinstance(delta.delta, TextDelta):
                        yield ModelResponse(content=delta.delta.text)
                        message_data.response_content += delta.delta.text
                        metrics.output_tokens += 1
                        if metrics.output_tokens == 1:
                            metrics.time_to_first_token = metrics.response_timer.elapsed

                if isinstance(delta, ContentBlockStopEvent):
                    if isinstance(delta.content_block, ToolUseBlock):
                        tool_use = delta.content_block
                        tool_name = tool_use.name
                        tool_input = tool_use.input
                        message_data.tool_ids.append(tool_use.id)

                        function_def = {"name": tool_name}
                        if tool_input:
                            function_def["arguments"] = json.dumps(tool_input)
                        message_data.tool_calls.append(
                            {
                                "id": tool_use.id,
                                "type": "function",
                                "function": function_def,
                            }
                        )
                    message_data.response_block.append(delta.content_block)

                if isinstance(delta, MessageStopEvent):
                    message_data.response_usage = delta.message.usage

        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(
            role="assistant",
            content=message_data.response_content,
        )

        # -*- Update assistant message if tool calls are present
        if len(message_data.tool_calls) > 0:
            assistant_message.tool_calls = message_data.tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(assistant_message, message_data.response_usage, metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self.handle_stream_tool_calls(assistant_message, messages, message_data.tool_ids)
            yield from self.response_stream(messages=messages)
        logger.debug("---------- Claude Response End ----------")

    def get_tool_call_prompt(self) -> Optional[str]:
        if self._functions is not None and len(self._functions) > 0:
            tool_call_prompt = "Do not reflect on the quality of the returned search results in your response"
            return tool_call_prompt
        return None

    def get_system_message_for_model(self) -> Optional[str]:
        return self.get_tool_call_prompt()

    async def ainvoke(self, messages: List[Message]) -> AnthropicMessage:
        """
        Send an asynchronous request to the Anthropic API to generate a response.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AnthropicMessage: The response from the model.
        """
        chat_messages, system_message = _format_messages(messages)
        request_kwargs = self.prepare_request_kwargs(system_message)

        return await self.get_async_client().messages.create(
            model=self.id,
            messages=chat_messages,  # type: ignore
            **request_kwargs,
        )

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Stream an asynchronous response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.
        """
        chat_messages, system_message = _format_messages(messages)
        request_kwargs = self.prepare_request_kwargs(system_message)

        return self.get_async_client().messages.stream(
            model=self.id,
            messages=chat_messages,  # type: ignore
            **request_kwargs,
        )

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Send an asynchronous chat completion request to the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ModelResponse: The response from the model.
        """
        logger.debug("---------- Claude Async Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics_for_run = Metrics()

        metrics_for_run.start_response_timer()
        response: AnthropicMessage = await self.ainvoke(messages=messages)
        metrics_for_run.stop_response_timer()

        # -*- Create assistant message
        assistant_message, response_content, tool_ids = self.create_assistant_message(
            response=response, metrics=metrics_for_run
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics_for_run.log()

        # -*- Handle tool calls
        if await self.ahandle_tool_calls(assistant_message, messages, model_response, tool_ids) is not None:
            response_after_tool_calls = await self.aresponse(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Update model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- Claude Async Response End ----------")
        return model_response

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of model responses.
        """
        logger.debug("---------- Claude Async Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        response = await self.ainvoke_stream(messages=messages)
        async with response as stream:
            async for delta in stream:
                if isinstance(delta, RawContentBlockDeltaEvent):
                    if isinstance(delta.delta, TextDelta):
                        yield ModelResponse(content=delta.delta.text)
                        message_data.response_content += delta.delta.text
                        metrics.output_tokens += 1
                        if metrics.output_tokens == 1:
                            metrics.time_to_first_token = metrics.response_timer.elapsed

                if isinstance(delta, ContentBlockStopEvent):
                    if isinstance(delta.content_block, ToolUseBlock):
                        tool_use = delta.content_block
                        tool_name = tool_use.name
                        tool_input = tool_use.input
                        message_data.tool_ids.append(tool_use.id)

                        function_def = {"name": tool_name}
                        if tool_input:
                            function_def["arguments"] = json.dumps(tool_input)
                        message_data.tool_calls.append(
                            {
                                "id": tool_use.id,
                                "type": "function",
                                "function": function_def,
                            }
                        )
                    message_data.response_block.append(delta.content_block)

                if isinstance(delta, MessageStopEvent):
                    message_data.response_usage = delta.message.usage

        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(
            role="assistant",
            content=message_data.response_content,
        )

        # -*- Update assistant message if tool calls are present
        if len(message_data.tool_calls) > 0:
            assistant_message.tool_calls = message_data.tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(assistant_message, message_data.response_usage, metrics)

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            async for tool_call_response in self.ahandle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages, tool_ids=message_data.tool_ids
            ):
                yield tool_call_response
            async for post_tool_call_response in self.aresponse_stream(messages=messages):
                yield post_tool_call_response
        logger.debug("---------- Claude Async Response End ----------")

    async def ahandle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        tool_ids: List[str],
    ) -> Any:
        """
        Parse and run function calls from the assistant message asynchronously.

        Args:
            assistant_message (Message): The assistant message containing tool calls.
            messages (List[Message]): The list of conversation messages.
            tool_ids (List[str]): The list of tool IDs.

        Yields:
            Any: Yields model responses during function execution.
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

            self.format_function_call_results(function_call_results, tool_ids, messages)
