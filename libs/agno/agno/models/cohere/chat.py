import json
from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

from agno.models.base import Model, StreamData
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import FunctionCall
from agno.utils.log import logger
from agno.utils.timer import Timer
from agno.utils.tools import get_function_call_for_tool_call

try:
    from cohere import AsyncClient as CohereAsyncClient
    from cohere import Client as CohereClient
    from cohere.types.api_meta import ApiMeta
    from cohere.types.api_meta_tokens import ApiMetaTokens
    from cohere.types.non_streamed_chat_response import NonStreamedChatResponse
    from cohere.types.streamed_chat_response import (
        StreamedChatResponse,
        StreamEndStreamedChatResponse,
        StreamStartStreamedChatResponse,
        TextGenerationStreamedChatResponse,
        ToolCallsChunkStreamedChatResponse,
        ToolCallsGenerationStreamedChatResponse,
    )
    from cohere.types.tool import Tool as CohereTool
    from cohere.types.tool_call import ToolCall
    from cohere.types.tool_parameter_definitions_value import (
        ToolParameterDefinitionsValue,
    )
    from cohere.types.tool_result import ToolResult
except (ModuleNotFoundError, ImportError):
    raise ImportError("`cohere` not installed. Please install using `pip install cohere`")


@dataclass
class Cohere(Model):
    id: str = "command-r-plus"
    name: str = "cohere"
    provider: str = "Cohere"

    # -*- Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    request_params: Optional[Dict[str, Any]] = None
    # Add chat history to the cohere messages instead of using the conversation_id
    add_chat_history: bool = False
    # -*- Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None
    # -*- Provide the Cohere client manually
    client: Optional[CohereClient] = None
    async_client: Optional[CohereAsyncClient] = None

    def get_client(self) -> CohereClient:
        if self.client:
            return self.client

        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("CO_API_KEY")
        if not self.api_key:
            logger.error("CO_API_KEY not set. Please set the CO_API_KEY environment variable.")

        _client_params["api_key"] = self.api_key

        self.client = CohereClient(**_client_params)
        return self.client

    def get_async_client(self) -> CohereAsyncClient:
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("CO_API_KEY")

        if not self.api_key:
            logger.error("CO_API_KEY not set. Please set the CO_API_KEY environment variable.")

        _client_params["api_key"] = self.api_key

        self.async_client = CohereAsyncClient(**_client_params)
        return self.async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        _request_params: Dict[str, Any] = {}
        if self.session_id is not None and not self.add_chat_history:
            _request_params["conversation_id"] = self.session_id
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.frequency_penalty:
            _request_params["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty:
            _request_params["presence_penalty"] = self.presence_penalty
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def _get_tools(self) -> Optional[List[CohereTool]]:
        """
        Get the tools in the format supported by the Cohere API.

        Returns:
            Optional[List[CohereTool]]: The list of tools.
        """
        if not self._functions:
            return None

        # Returns the tools in the format supported by the Cohere API
        return [
            CohereTool(
                name=f_name,
                description=function.description or "",
                parameter_definitions={
                    param_name: ToolParameterDefinitionsValue(
                        type=param_info["type"] if isinstance(param_info["type"], str) else param_info["type"][0],
                        required="null" not in param_info["type"],
                    )
                    for param_name, param_info in function.parameters.get("properties", {}).items()
                },
            )
            for f_name, function in self._functions.items()
        ]

    def _prepare_for_invoke(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        api_kwargs: Dict[str, Any] = self.request_kwargs
        chat_message: str = ""

        if self.add_chat_history:
            logger.debug("Providing chat_history to cohere")
            chat_history: List = []
            for m in messages:
                if m.role == "system" and "preamble" not in api_kwargs:
                    api_kwargs["preamble"] = m.content
                elif m.role == "user":
                    # Update the chat_message to the new user message
                    chat_message = m.get_content_string()
                    chat_history.append({"role": "USER", "message": chat_message})
                else:
                    chat_history.append({"role": "CHATBOT", "message": m.get_content_string() or ""})
            if chat_history[-1].get("role") == "USER":
                chat_history.pop()
            api_kwargs["chat_history"] = chat_history
        else:
            # Set first system message as preamble
            for m in messages:
                if m.role == "system" and "preamble" not in api_kwargs:
                    api_kwargs["preamble"] = m.get_content_string()
                    break
            # Set last user message as chat_message
            for m in reversed(messages):
                if m.role == "user":
                    chat_message = m.get_content_string()
                    break

        if self.tools:
            api_kwargs["tools"] = self._get_tools()

        if tool_results:
            api_kwargs["tool_results"] = tool_results

        return chat_message, api_kwargs

    def invoke(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> NonStreamedChatResponse:
        """
        Invoke a non-streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.
            tool_results (Optional[List[ToolResult]]): The list of tool results.

        Returns:
            NonStreamedChatResponse: The non-streamed chat response.
        """
        chat_message, api_kwargs = self._prepare_for_invoke(messages, tool_results)

        return self.get_client().chat(model=self.id, message=chat_message, **api_kwargs)

    def invoke_stream(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> Iterator[StreamedChatResponse]:
        """
        Invoke a streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.
            tool_results (Optional[List[ToolResult]]): The list of tool results.

        Returns:
            Iterator[StreamedChatResponse]: An iterator of streamed chat responses.
        """
        chat_message, api_kwargs = self._prepare_for_invoke(messages, tool_results)

        return self.get_client().chat_stream(model=self.id, message=chat_message, **api_kwargs)

    def _prepare_function_calls(self, agent_message: Message) -> Tuple[List[FunctionCall], List[Message]]:
        """
        Prepares function calls based on tool calls in the agent message.

        This method processes tool calls, matches them with available functions,
        and prepares them for execution. It also handles errors if functions
        are not found or if there are issues with the function calls.

        Args:
            agent_message (Message): The message containing tool calls to process.

        Returns:
            Tuple[List[FunctionCall], List[Message]]: A tuple containing a list of
            prepared function calls and a list of error messages.
        """
        function_calls_to_run: List[FunctionCall] = []
        error_messages: List[Message] = []

        # Check if tool_calls is None or empty
        if not agent_message.tool_calls:
            return function_calls_to_run, error_messages

        # Process each tool call in the agent message
        for tool_call in agent_message.tool_calls:
            # Attempt to get a function call for the tool call
            _function_call = get_function_call_for_tool_call(tool_call, self._functions)

            # Handle cases where function call cannot be created
            if _function_call is None:
                error_messages.append(Message(role="user", content="Could not find function to call."))
                continue

            # Handle cases where function call has an error
            if _function_call.error is not None:
                error_messages.append(Message(role="user", content=_function_call.error))
                continue

            # Add valid function calls to the list
            function_calls_to_run.append(_function_call)

        return function_calls_to_run, error_messages

    def _handle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        response_tool_calls: Optional[List[ToolCall]],
        model_response: ModelResponse,
    ) -> Optional[Any]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            response_tool_calls (List[Any]): The list of response tool calls.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[Any]: The tool results.
        """

        model_response.content = ""
        tool_role: str = "tool"
        function_calls_to_run: List[FunctionCall] = []
        function_call_results: List[Message] = []
        if assistant_message.tool_calls is None:
            return None

        if model_response.tool_calls is None:
            model_response.tool_calls = []

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

        model_response.content = assistant_message.get_content_string() + "\n\n"

        if self.show_tool_calls:
            model_response.content += "\nRunning:"
            for _f in function_calls_to_run:
                model_response.content += f"\n - {_f.get_call_str()}"
            model_response.content += "\n\n"

        function_calls_to_run, error_messages = self._prepare_function_calls(assistant_message)

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

        # Prepare tool results for the next API call
        if response_tool_calls:
            tool_results = [
                ToolResult(
                    call=tool_call,
                    outputs=[tool_call.parameters, {"result": fn_result.content}],
                )
                for tool_call, fn_result in zip(response_tool_calls, function_call_results)
            ]
        else:
            tool_results = None

        return tool_results

    def _create_assistant_message(self, response: NonStreamedChatResponse) -> Message:
        """
        Create an assistant message from the response.

        Args:
            response (NonStreamedChatResponse): The response from the Cohere API.

        Returns:
            Message: The assistant message.
        """
        response_content = response.text
        return Message(role="assistant", content=response_content)

    def response(self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None) -> ModelResponse:
        """
        Send a chat completion request to the Cohere API.

        Args:
            messages (List[Message]): A list of message objects representing the conversation.

        Returns:
            ModelResponse: The model response from the API.
        """
        logger.debug("---------- Cohere Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()

        # Timer for response
        response_timer = Timer()
        response_timer.start()
        logger.debug(f"Tool Results: {tool_results}")
        response: NonStreamedChatResponse = self.invoke(messages=messages, tool_results=tool_results)
        response_timer.stop()
        logger.debug(f"Time to generate response: {response_timer.elapsed:.4f}s")

        assistant_message = self._create_assistant_message(response)

        # Process tool calls if present
        response_tool_calls = response.tool_calls
        if response_tool_calls:
            tool_calls = [
                {
                    "type": "function",
                    "function": {
                        "name": tools.name,
                        "arguments": json.dumps(tools.parameters),
                    },
                }
                for tools in response_tool_calls
            ]
            assistant_message.tool_calls = tool_calls

        # Handle tool calls if present and tool running is enabled
        if assistant_message.tool_calls:
            tool_results = self._handle_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                response_tool_calls=response_tool_calls,
                model_response=model_response,
            )

            # Make a recursive call with tool results if available
            if tool_results:
                # Cohere doesn't allow tool calls in the same message as the user's message, so we add a new user message with empty content
                messages.append(Message(role="user", content=""))

            response_after_tool_calls = self.response(messages=messages, tool_results=tool_results)
            if response_after_tool_calls.content:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # If no tool calls, return the agent message content
        if assistant_message.content:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- Cohere Response End ----------")
        return model_response

    def _update_stream_metrics(self, stream_data: StreamData, assistant_message: Message):
        """
        Update the metrics for the streaming response.

        Args:
            stream_data (StreamData): The streaming data
            assistant_message (Message): The assistant message.
        """
        assistant_message.metrics["time"] = stream_data.response_timer.elapsed
        if stream_data.time_to_first_token is not None:
            assistant_message.metrics["time_to_first_token"] = stream_data.time_to_first_token

        if "response_times" not in self.metrics:
            self.metrics["response_times"] = []
        self.metrics["response_times"].append(stream_data.response_timer.elapsed)
        if stream_data.time_to_first_token is not None:
            if "time_to_first_token" not in self.metrics:
                self.metrics["time_to_first_token"] = []
            self.metrics["time_to_first_token"].append(stream_data.time_to_first_token)
        if stream_data.completion_tokens > 0:
            if "tokens_per_second" not in self.metrics:
                self.metrics["tokens_per_second"] = []
            self.metrics["tokens_per_second"].append(
                f"{stream_data.completion_tokens / stream_data.response_timer.elapsed:.4f}"
            )

        assistant_message.metrics["prompt_tokens"] = stream_data.response_prompt_tokens
        assistant_message.metrics["input_tokens"] = stream_data.response_prompt_tokens
        self.metrics["prompt_tokens"] = self.metrics.get("prompt_tokens", 0) + stream_data.response_prompt_tokens
        self.metrics["input_tokens"] = self.metrics.get("input_tokens", 0) + stream_data.response_prompt_tokens

        assistant_message.metrics["completion_tokens"] = stream_data.response_completion_tokens
        assistant_message.metrics["output_tokens"] = stream_data.response_completion_tokens
        self.metrics["completion_tokens"] = (
            self.metrics.get("completion_tokens", 0) + stream_data.response_completion_tokens
        )
        self.metrics["output_tokens"] = self.metrics.get("output_tokens", 0) + stream_data.response_completion_tokens

        assistant_message.metrics["total_tokens"] = stream_data.response_total_tokens
        self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + stream_data.response_total_tokens

    def response_stream(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> Iterator[ModelResponse]:
        logger.debug("---------- Cohere Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)

        stream_data: StreamData = StreamData()
        stream_data.response_timer.start()

        stream_data.response_content = ""
        tool_calls: List[Dict[str, Any]] = []
        stream_data.response_tool_calls = []
        last_delta: Optional[NonStreamedChatResponse] = None

        for response in self.invoke_stream(messages=messages, tool_results=tool_results):
            if isinstance(response, StreamStartStreamedChatResponse):
                pass

            if isinstance(response, TextGenerationStreamedChatResponse):
                if response.text is not None:
                    stream_data.response_content += response.text
                    stream_data.completion_tokens += 1
                    if stream_data.completion_tokens == 1:
                        stream_data.time_to_first_token = stream_data.response_timer.elapsed
                        logger.debug(f"Time to first token: {stream_data.time_to_first_token:.4f}s")
                    yield ModelResponse(content=response.text)

            if isinstance(response, ToolCallsChunkStreamedChatResponse):
                if response.tool_call_delta is None:
                    yield ModelResponse(content=response.text)

            # Detect if response is a tool call
            if isinstance(response, ToolCallsGenerationStreamedChatResponse):
                for tc in response.tool_calls:
                    stream_data.response_tool_calls.append(tc)
                    tool_calls.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.parameters),
                            },
                        }
                    )

            if isinstance(response, StreamEndStreamedChatResponse):
                last_delta = response.response

        yield ModelResponse(content="\n\n")

        stream_data.response_timer.stop()
        logger.debug(f"Time to generate response: {stream_data.response_timer.elapsed:.4f}s")

        # -*- Create assistant message
        assistant_message = Message(role="assistant", content=stream_data.response_content)
        # -*- Add tool calls to assistant message
        if len(stream_data.response_tool_calls) > 0:
            assistant_message.tool_calls = tool_calls

        # -*- Update usage metrics
        # Add response time to metrics
        assistant_message.metrics["time"] = stream_data.response_timer.elapsed
        if "response_times" not in self.metrics:
            self.metrics["response_times"] = []
        self.metrics["response_times"].append(stream_data.response_timer.elapsed)

        # Add token usage to metrics
        meta: Optional[ApiMeta] = last_delta.meta if last_delta else None
        tokens: Optional[ApiMetaTokens] = meta.tokens if meta else None

        if tokens:
            input_tokens = tokens.input_tokens
            output_tokens = tokens.output_tokens

            if input_tokens is not None:
                assistant_message.metrics["input_tokens"] = input_tokens
                self.metrics["input_tokens"] = self.metrics.get("input_tokens", 0) + input_tokens

            if output_tokens is not None:
                assistant_message.metrics["output_tokens"] = output_tokens
                self.metrics["output_tokens"] = self.metrics.get("output_tokens", 0) + output_tokens

            if input_tokens is not None and output_tokens is not None:
                assistant_message.metrics["total_tokens"] = input_tokens + output_tokens
                self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + input_tokens + output_tokens

        # -*- Add assistant message to messages
        self._update_stream_metrics(stream_data=stream_data, assistant_message=assistant_message)
        messages.append(assistant_message)
        assistant_message.log()
        logger.debug(f"Assistant Message: {assistant_message}")

        # -*- Parse and run function call
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
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f"- Running: {function_calls_to_run[0].get_call_str()}\n\n")
                elif len(function_calls_to_run) > 1:
                    yield ModelResponse(content="Running:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            for intermediate_model_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                yield intermediate_model_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            # Making sure the length of tool calls and function call results are the same to avoid unexpected behavior
            if stream_data.response_tool_calls is not None:
                # Constructs a list named tool_results, where each element is a dictionary that contains details of tool calls and their outputs.
                # It pairs each tool call in response_tool_calls with its corresponding result in function_call_results.
                tool_results = [
                    ToolResult(call=tool_call, outputs=[tool_call.parameters, {"result": fn_result.content}])
                    for tool_call, fn_result in zip(stream_data.response_tool_calls, function_call_results)
                ]
                messages.append(Message(role="user", content=""))

            # -*- Yield new response using results of tool calls
            yield from self.response_stream(messages=messages, tool_results=tool_results)
        logger.debug("---------- Cohere Response End ----------")

    async def ainvoke(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> NonStreamedChatResponse:
        """
        Asynchronously invoke a non-streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.
            tool_results (Optional[List[ToolResult]]): The list of tool results.

        Returns:
            NonStreamedChatResponse: The non-streamed chat response.
        """
        chat_message, api_kwargs = self._prepare_for_invoke(messages, tool_results)
        return await self.get_async_client().chat(model=self.id, message=chat_message, **api_kwargs)

    async def ainvoke_stream(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> AsyncIterator[StreamedChatResponse]:
        """
        Asynchronously invoke a streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.
            tool_results (Optional[List[ToolResult]]): The list of tool results.

        Returns:
            AsyncIterator[StreamedChatResponse]: An async iterator of streamed chat responses.
        """
        chat_message, api_kwargs = self._prepare_for_invoke(messages, tool_results)
        async for response in self.get_async_client().chat_stream(model=self.id, message=chat_message, **api_kwargs):
            yield response

    async def aresponse(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> ModelResponse:
        """
        Asynchronously send a chat completion request to the Cohere API.

        Args:
            messages (List[Message]): A list of message objects representing the conversation.

        Returns:
            ModelResponse: The model response from the API.
        """
        logger.debug("---------- Cohere Async Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()

        # Timer for response
        response_timer = Timer()
        response_timer.start()
        logger.debug(f"Tool Results: {tool_results}")
        response: NonStreamedChatResponse = await self.ainvoke(messages=messages, tool_results=tool_results)
        response_timer.stop()
        logger.debug(f"Time to generate response: {response_timer.elapsed:.4f}s")

        assistant_message = self._create_assistant_message(response)

        # Process tool calls if present
        response_tool_calls = response.tool_calls
        if response_tool_calls:
            tool_calls = [
                {
                    "type": "function",
                    "function": {
                        "name": tools.name,
                        "arguments": json.dumps(tools.parameters),
                    },
                }
                for tools in response_tool_calls
            ]
            assistant_message.tool_calls = tool_calls

        # Handle tool calls if present and tool running is enabled
        if assistant_message.tool_calls:
            tool_results = self._handle_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                response_tool_calls=response_tool_calls,
                model_response=model_response,
            )

            # Make a recursive call with tool results if available
            if tool_results:
                # Cohere doesn't allow tool calls in the same message as the user's message, so we add a new user message with empty content
                messages.append(Message(role="user", content=""))

            response_after_tool_calls = await self.aresponse(messages=messages, tool_results=tool_results)
            if response_after_tool_calls.content:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # If no tool calls, return the agent message content
        if assistant_message.content:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- Cohere Async Response End ----------")
        return model_response

    async def aresponse_stream(
        self, messages: List[Message], tool_results: Optional[List[ToolResult]] = None
    ) -> AsyncIterator[ModelResponse]:
        logger.debug("---------- Cohere Async Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)

        stream_data: StreamData = StreamData()
        stream_data.response_timer.start()

        stream_data.response_content = ""
        tool_calls: List[Dict[str, Any]] = []
        stream_data.response_tool_calls = []
        last_delta: Optional[NonStreamedChatResponse] = None

        async for response in self.ainvoke_stream(messages=messages, tool_results=tool_results):
            if isinstance(response, StreamStartStreamedChatResponse):
                pass

            if isinstance(response, TextGenerationStreamedChatResponse):
                if response.text is not None:
                    stream_data.response_content += response.text
                    stream_data.completion_tokens += 1
                    if stream_data.completion_tokens == 1:
                        stream_data.time_to_first_token = stream_data.response_timer.elapsed
                        logger.debug(f"Time to first token: {stream_data.time_to_first_token:.4f}s")
                    yield ModelResponse(content=response.text)

            if isinstance(response, ToolCallsChunkStreamedChatResponse):
                if response.tool_call_delta is None:
                    yield ModelResponse(content=response.text)

            # Detect if response is a tool call
            if isinstance(response, ToolCallsGenerationStreamedChatResponse):
                for tc in response.tool_calls:
                    stream_data.response_tool_calls.append(tc)
                    tool_calls.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.parameters),
                            },
                        }
                    )

            if isinstance(response, StreamEndStreamedChatResponse):
                last_delta = response.response

        yield ModelResponse(content="\n\n")

        stream_data.response_timer.stop()
        logger.debug(f"Time to generate response: {stream_data.response_timer.elapsed:.4f}s")

        # -*- Create assistant message
        assistant_message = Message(role="assistant", content=stream_data.response_content)
        # -*- Add tool calls to assistant message
        if len(stream_data.response_tool_calls) > 0:
            assistant_message.tool_calls = tool_calls

        # -*- Update usage metrics
        # Add response time to metrics
        assistant_message.metrics["time"] = stream_data.response_timer.elapsed
        if "response_times" not in self.metrics:
            self.metrics["response_times"] = []
        self.metrics["response_times"].append(stream_data.response_timer.elapsed)

        # Add token usage to metrics
        meta: Optional[ApiMeta] = last_delta.meta if last_delta else None
        tokens: Optional[ApiMetaTokens] = meta.tokens if meta else None

        if tokens:
            input_tokens = tokens.input_tokens
            output_tokens = tokens.output_tokens

            if input_tokens is not None:
                assistant_message.metrics["input_tokens"] = input_tokens
                self.metrics["input_tokens"] = self.metrics.get("input_tokens", 0) + input_tokens

            if output_tokens is not None:
                assistant_message.metrics["output_tokens"] = output_tokens
                self.metrics["output_tokens"] = self.metrics.get("output_tokens", 0) + output_tokens

            if input_tokens is not None and output_tokens is not None:
                assistant_message.metrics["total_tokens"] = input_tokens + output_tokens
                self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + input_tokens + output_tokens

        # -*- Add assistant message to messages
        self._update_stream_metrics(stream_data=stream_data, assistant_message=assistant_message)
        messages.append(assistant_message)
        assistant_message.log()
        logger.debug(f"Assistant Message: {assistant_message}")

        # -*- Parse and run function call
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
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f"- Running: {function_calls_to_run[0].get_call_str()}\n\n")
                elif len(function_calls_to_run) > 1:
                    yield ModelResponse(content="Running:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            for intermediate_model_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                yield intermediate_model_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            # Making sure the length of tool calls and function call results are the same to avoid unexpected behavior
            if stream_data.response_tool_calls is not None:
                # Constructs a list named tool_results, where each element is a dictionary that contains details of tool calls and their outputs.
                # It pairs each tool call in response_tool_calls with its corresponding result in function_call_results.
                tool_results = [
                    ToolResult(call=tool_call, outputs=[tool_call.parameters, {"result": fn_result.content}])
                    for tool_call, fn_result in zip(stream_data.response_tool_calls, function_call_results)
                ]
                messages.append(Message(role="user", content=""))

            # -*- Yield new response using results of tool calls
            async for response in self.aresponse_stream(messages=messages, tool_results=tool_results):
                yield response
        logger.debug("---------- Cohere Async Response End ----------")
