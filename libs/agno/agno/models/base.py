import asyncio
import collections.abc
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from types import GeneratorType
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from agno.exceptions import AgentRunException
from agno.media import Audio, AudioOutput, Image
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse, ModelResponseEvent, ProviderResponse
from agno.tools.function import Function, FunctionCall
from agno.utils.log import logger
from agno.utils.timer import Timer
from agno.utils.tools import get_function_call_for_tool_call


@dataclass
class MessageData:
    response_role: Optional[str] = None
    response_content: Any = ""
    response_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_audio: Optional[AudioOutput] = None

    extra: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class Model(ABC):
    # ID of the model to use.
    id: str
    # Name for this Model. This is not sent to the Model API.
    name: Optional[str] = None
    # Provider for this Model. This is not sent to the Model API.
    provider: Optional[str] = None

    # -*- Do not set the following attributes directly -*-
    # -*- Set them on the Agent instead -*-

    # Used for structured_outputs, do not set this directly
    # Set the response_model attribute on the Agent instead
    response_format: Optional[Any] = None
    # Whether to use the structured outputs with this Model.
    structured_outputs: bool = False
    # True if the Model supports structured outputs natively (e.g. OpenAI)
    supports_structured_outputs: bool = False

    # Controls which (if any) function is called by the model.
    # "none" means the model will not call a function and instead generates a message.
    # "auto" means the model can pick between generating a message or calling a function.
    # Specifying a particular function via {"type: "function", "function": {"name": "my_function"}}
    #   forces the model to call that function.
    # "none" is the default when no functions are present. "auto" is the default if functions are present.
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None

    # If True, shows function calls in the response. Disabled when response_model is used.
    show_tool_calls: Optional[bool] = None
    # Maximum number of tool calls allowed.
    tool_call_limit: Optional[int] = None

    # A list of tools provided to the Model.
    # Tools are functions the model may generate JSON inputs for.
    _tools: Optional[List[Dict]] = None

    # Functions available to the Model to call
    # Functions extracted from the tools.
    # Note: These are not sent to the Model API and are only used for execution + deduplication.
    _functions: Optional[Dict[str, Function]] = None
    # Function call stack.
    _function_call_stack: Optional[List[FunctionCall]] = None

    # System prompt from the model added to the Agent.
    system_prompt: Optional[str] = None
    # Instructions from the model added to the Agent.
    instructions: Optional[List[str]] = None

    # The role of the tool message.
    tool_message_role: str = "tool"
    # The role of the assistant message.
    assistant_message_role: str = "assistant"
    # Whether to override the system message role to the the system_message_role.
    # This is used for OpenAI models to map the "system" role to "developer"
    override_system_role: bool = False
    # The role to map the system message to.
    system_message_role: str = "system"

    def __post_init__(self):
        if self.provider is None and self.name is not None:
            self.provider = f"{self.name} ({self.id})"

    def to_dict(self) -> Dict[str, Any]:
        fields = {"name", "id", "provider"}
        _dict = {field: getattr(self, field) for field in fields if getattr(self, field) is not None}
        # Add functions if they exist
        if self._functions:
            _dict["functions"] = {k: v.to_dict() for k, v in self._functions.items()}
            _dict["tool_call_limit"] = self.tool_call_limit
        return _dict

    def get_provider(self) -> str:
        return self.provider or self.name or self.__class__.__name__

    @abstractmethod
    def invoke(self, *args, **kwargs) -> Any:
        pass

    @abstractmethod
    async def ainvoke(self, *args, **kwargs) -> Any:
        pass

    @abstractmethod
    def invoke_stream(self, *args, **kwargs) -> Iterator[Any]:
        pass

    @abstractmethod
    async def ainvoke_stream(self, *args, **kwargs) -> Any:
        pass

    @abstractmethod
    def parse_model_response(self, response: Any) -> ModelResponse:
        """
        Parse the response from the model provider into a ModelResponse.

        Args:
            response: Response from the model invoke() method

        Returns:
            ModelResponse: Parsed response data
        """
        pass

    @abstractmethod
    def parse_model_response_chunk(self, response: Any) -> Optional[ModelResponse]:
        """
        Parse the streaming response chunk from the model provider into a ModelResponse object.

        Args:
            response: Streaming response chunk from the model invoke_stream() method

        Returns:
            ModelResponse: Parsed response data
        """
        pass

    def _log_messages(self, messages: List[Message]) -> None:
        """
        Log messages for debugging.
        """
        for m in messages:
            m.log()

    def set_tools(self, tools: List[Dict]) -> None:
        self._tools = tools

    def set_functions(self, functions: Dict[str, Function]) -> None:
        if len(functions) > 0:
            self._functions = functions

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse the tool calls from the model provider into a list of tool calls.
        """
        return tool_calls_data

    def get_function_calls_to_run(
        self, assistant_message: Message, messages: List[Message], error_response_role: str = "user"
    ) -> List[FunctionCall]:
        """
        Prepare function calls for the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of conversation messages.

        Returns:
            List[FunctionCall]: A list of function calls to run.
        """
        function_calls_to_run: List[FunctionCall] = []
        if assistant_message.tool_calls is not None:
            for tool_call in assistant_message.tool_calls:
                _tool_call_id = tool_call.get("id")
                _function_call = get_function_call_for_tool_call(tool_call, self._functions)
                if _function_call is None:
                    messages.append(Message(role=error_response_role, content="Could not find function to call."))
                    continue
                if _function_call.error is not None:
                    messages.append(
                        Message(role=error_response_role, tool_call_id=_tool_call_id, content=_function_call.error)
                    )
                    continue
                function_calls_to_run.append(_function_call)
        return function_calls_to_run

    def handle_agent_exception(self, a_exc: AgentRunException, additional_messages: List[Message]) -> None:
        """Handle AgentRunException and collect additional messages."""
        if a_exc.user_message is not None:
            msg = (
                Message(role="user", content=a_exc.user_message)
                if isinstance(a_exc.user_message, str)
                else a_exc.user_message
            )
            additional_messages.append(msg)

        if a_exc.agent_message is not None:
            msg = (
                Message(role="assistant", content=a_exc.agent_message)
                if isinstance(a_exc.agent_message, str)
                else a_exc.agent_message
            )
            additional_messages.append(msg)

        if a_exc.messages:
            for m in a_exc.messages:
                if isinstance(m, Message):
                    additional_messages.append(m)
                elif isinstance(m, dict):
                    try:
                        additional_messages.append(Message(**m))
                    except Exception as e:
                        logger.warning(f"Failed to convert dict to Message: {e}")

        if a_exc.stop_execution:
            for m in additional_messages:
                m.stop_after_tool_call = True

    def create_function_call_result(
        self, fc: FunctionCall, success: bool, output: Optional[Union[List[Any], str]], timer: Timer
    ) -> Message:
        """Create a function call result message."""
        return Message(
            role=self.tool_message_role,
            content=output if success else fc.error,
            tool_call_id=fc.call_id,
            tool_name=fc.function.name,
            tool_args=fc.arguments,
            tool_call_error=not success,
            stop_after_tool_call=fc.function.stop_after_tool_call,
            metrics=MessageMetrics(time=timer.elapsed),
        )

    def run_function_calls(
        self, function_calls: List[FunctionCall], function_call_results: List[Message]
    ) -> Iterator[ModelResponse]:
        if self._function_call_stack is None:
            self._function_call_stack = []

        # Additional messages from function calls that will be added to the function call results
        additional_messages: List[Message] = []

        for fc in function_calls:
            # Start function call
            function_call_timer = Timer()
            function_call_timer.start()
            # Yield a tool_call_started event
            yield ModelResponse(
                content=fc.get_call_str(),
                tool_calls=[
                    {
                        "role": self.tool_message_role,
                        "tool_call_id": fc.call_id,
                        "tool_name": fc.function.name,
                        "tool_args": fc.arguments,
                    }
                ],
                event=ModelResponseEvent.tool_call_started.value,
            )

            # Track if the function call was successful
            function_call_success = False
            # Run function calls sequentially
            try:
                function_call_success = fc.execute()
            except AgentRunException as a_exc:
                # Update additional messages from function call
                self.handle_agent_exception(a_exc, additional_messages)
                # Set function call success to False if an exception occurred
                function_call_success = False
            except Exception as e:
                logger.error(f"Error executing function {fc.function.name}: {e}")
                function_call_success = False
                raise e

            # Stop function call timer
            function_call_timer.stop()

            # Process function call output
            function_call_output: Optional[Union[List[Any], str]] = ""
            if isinstance(fc.result, (GeneratorType, collections.abc.Iterator)):
                for item in fc.result:
                    function_call_output += item
                    if fc.function.show_result:
                        yield ModelResponse(content=item)
            else:
                function_call_output = fc.result
                if fc.function.show_result:
                    yield ModelResponse(content=function_call_output)

            # Create and yield function call result
            function_call_result = self.create_function_call_result(
                fc, function_call_success, function_call_output, function_call_timer
            )
            yield ModelResponse(
                content=f"{fc.get_call_str()} completed in {function_call_timer.elapsed:.4f}s.",
                tool_calls=[
                    function_call_result.model_dump(
                        include={
                            "content",
                            "tool_call_id",
                            "tool_name",
                            "tool_args",
                            "tool_call_error",
                            "metrics",
                            "created_at",
                        }
                    )
                ],
                event=ModelResponseEvent.tool_call_completed.value,
            )

            # Add function call to function call results
            function_call_results.append(function_call_result)
            self._function_call_stack.append(fc)

            # Check function call limit
            if self.tool_call_limit and len(self._function_call_stack) >= self.tool_call_limit:
                # Deactivate tool calls by setting future tool calls to "none"
                self.tool_choice = "none"
                break  # Exit early if we reach the function call limit

        # Add any additional messages at the end
        if additional_messages:
            function_call_results.extend(additional_messages)

    async def _arun_function_call(
        self, function_call: FunctionCall
    ) -> tuple[Union[bool, AgentRunException], Timer, FunctionCall]:
        """Run a single function call and return its success status, timer, and the FunctionCall object."""
        from inspect import iscoroutinefunction

        function_call_timer = Timer()
        function_call_timer.start()
        success: Union[bool, AgentRunException] = False
        try:
            if iscoroutinefunction(function_call.function.entrypoint):
                success = await function_call.aexecute()
            else:
                success = await asyncio.to_thread(function_call.execute)
        except AgentRunException as e:
            success = e  # Pass the exception through to be handled by caller
        except Exception as e:
            logger.error(f"Error executing function {function_call.function.name}: {e}")
            success = False
            raise e

        function_call_timer.stop()
        return success, function_call_timer, function_call

    async def arun_function_calls(self, function_calls: List[FunctionCall], function_call_results: List[Message]):
        if self._function_call_stack is None:
            self._function_call_stack = []

        # Additional messages from function calls that will be added to the function call results
        additional_messages: List[Message] = []

        # Yield tool_call_started events for all function calls
        for fc in function_calls:
            yield ModelResponse(
                content=fc.get_call_str(),
                tool_calls=[
                    {
                        "role": self.tool_message_role,
                        "tool_call_id": fc.call_id,
                        "tool_name": fc.function.name,
                        "tool_args": fc.arguments,
                    }
                ],
                event=ModelResponseEvent.tool_call_started.value,
            )

        # Create and run all function calls in parallel
        results = await asyncio.gather(*(self._arun_function_call(fc) for fc in function_calls), return_exceptions=True)

        # Process results
        for result in results:
            # If result is an exception, skip processing it
            if isinstance(result, BaseException):
                logger.error(f"Error during function call: {result}")
                raise result

            # Unpack result
            function_call_success, function_call_timer, fc = result

            # Handle AgentRunException
            if isinstance(function_call_success, AgentRunException):
                a_exc = function_call_success
                # Update additional messages from function call
                self.handle_agent_exception(a_exc, additional_messages)
                # Set function call success to False if an exception occurred
                function_call_success = False

            # Process function call output
            function_call_output: Optional[Union[List[Any], str]] = ""
            if isinstance(fc.result, (GeneratorType, collections.abc.Iterator)):
                for item in fc.result:
                    function_call_output += item
                    if fc.function.show_result:
                        yield ModelResponse(content=item)
            else:
                function_call_output = fc.result
                if fc.function.show_result:
                    yield ModelResponse(content=function_call_output)

            # Create and yield function call result
            function_call_result = self.create_function_call_result(
                fc, function_call_success, function_call_output, function_call_timer
            )
            yield ModelResponse(
                content=f"{fc.get_call_str()} completed in {function_call_timer.elapsed:.4f}s.",
                tool_calls=[
                    function_call_result.model_dump(
                        include={
                            "content",
                            "tool_call_id",
                            "tool_name",
                            "tool_args",
                            "tool_call_error",
                            "metrics",
                            "created_at",
                        }
                    )
                ],
                event=ModelResponseEvent.tool_call_completed.value,
            )

            # Add function call result to function call results
            function_call_results.append(function_call_result)
            self._function_call_stack.append(fc)

            # Check function call limit
            if self.tool_call_limit and len(self._function_call_stack) >= self.tool_call_limit:
                self.tool_choice = "none"
                break

        # Add any additional messages at the end
        if additional_messages:
            function_call_results.extend(additional_messages)

    def prepare_function_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
    ) -> Tuple[List[FunctionCall], List[Message]]:
        """
        Prepare function calls from tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message containing tool calls
            messages (List[Message]): The list of messages to append tool responses to
            model_response (ModelResponse): The model response to update
        Returns:
            Tuple[List[FunctionCall], List[Message]]: Tuple of function calls to run and function call results
        """
        if model_response.content is None:
            model_response.content = ""
        if model_response.tool_calls is None:
            model_response.tool_calls = []

        function_call_results: List[Message] = []
        function_calls_to_run: List[FunctionCall] = self.get_function_calls_to_run(assistant_message, messages)

        if self.show_tool_calls:
            if len(function_calls_to_run) == 1:
                model_response.content += f" - Running: {function_calls_to_run[0].get_call_str()}\n\n"
            elif len(function_calls_to_run) > 1:
                model_response.content += "Running:"
                for _f in function_calls_to_run:
                    model_response.content += f"\n - {_f.get_call_str()}"
                model_response.content += "\n\n"

        return function_calls_to_run, function_call_results

    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], **kwargs
    ) -> None:
        """
        Format function call results.
        """
        if len(function_call_results) > 0:
            messages.extend(function_call_results)

    def handle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        **kwargs,
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
            function_calls_to_run, function_call_results = self.prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
            )

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)  # type: ignore  # model_response.tool_calls are initialized before calling this method

            self.format_function_call_results(messages=messages, function_call_results=function_call_results, **kwargs)

            return model_response
        return None

    async def ahandle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        **kwargs,
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
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            function_calls_to_run, function_call_results = self.prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
            )

            async for function_call_response in self.arun_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)  # type: ignore  # model_response.tool_calls are initialized before calling this method

            self.format_function_call_results(messages=messages, function_call_results=function_call_results, **kwargs)

            return model_response
        return None

    def prepare_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
    ) -> Tuple[List[FunctionCall], List[Message]]:
        """
        Prepare function calls from tool calls in the assistant message for streaming.

        Args:
            assistant_message (Message): The assistant message containing tool calls
            messages (List[Message]): The list of messages to append tool responses to

        Returns:
            Tuple[List[FunctionCall], List[Message]]: Tuple of function calls to run and function call results
        """
        function_calls_to_run: List[FunctionCall] = []
        function_call_results: List[Message] = []

        for tool_call in assistant_message.tool_calls:  # type: ignore  # assistant_message.tool_calls are checked before calling this method
            tool_call_id = tool_call.get("id")
            _function_call = get_function_call_for_tool_call(tool_call, self._functions)
            if _function_call is None:
                messages.append(
                    Message(
                        role=self.tool_message_role,
                        tool_call_id=tool_call_id,
                        content="Could not find function to call.",
                    )
                )
                continue
            if _function_call.error is not None:
                messages.append(
                    Message(
                        role=self.tool_message_role,
                        tool_call_id=tool_call_id,
                        content=_function_call.error,
                    )
                )
                continue
            function_calls_to_run.append(_function_call)

        return function_calls_to_run, function_call_results

    def handle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        **kwargs,
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
            yield ModelResponse(content="\n\n")

            function_calls_to_run, function_call_results = self.prepare_stream_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
            )

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f" - Running: {function_calls_to_run[0].get_call_str()}\n\n")
                else:
                    yield ModelResponse(content="\nRunning:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                yield function_call_response

            self.format_function_call_results(messages=messages, function_call_results=function_call_results, **kwargs)

    async def ahandle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        **kwargs,
    ) -> AsyncIterator[ModelResponse]:
        """
        Handle tool calls for response stream.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            tool_role (str): The role of the tool call. Defaults to "tool".

        Returns:
            Iterator[ModelResponse]: An iterator of the model response.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield ModelResponse(content="\n\n")

            function_calls_to_run, function_call_results = self.prepare_stream_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
            )

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f" - Running: {function_calls_to_run[0].get_call_str()}\n\n")
                else:
                    yield ModelResponse(content="\nRunning:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            async for function_call_response in self.arun_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                yield function_call_response

            self.format_function_call_results(messages=messages, function_call_results=function_call_results, **kwargs)

    def _handle_response_after_tool_calls(
        self, response_after_tool_calls: ModelResponse, model_response: ModelResponse
    ):
        if response_after_tool_calls.content is not None:
            if model_response.content is None:
                model_response.content = ""
            model_response.content += response_after_tool_calls.content
        if response_after_tool_calls.parsed is not None:
            # bubble up the parsed object, so that the final response has the parsed object
            # that is visible to the agent
            model_response.parsed = response_after_tool_calls.parsed
        if response_after_tool_calls.audio is not None:
            # bubble up the audio, so that the final response has the audio
            # that is visible to the agent
            model_response.audio = response_after_tool_calls.audio

    def _handle_stop_after_tool_calls(self, last_message: Message, model_response: ModelResponse):
        logger.debug("Stopping execution as stop_after_tool_call=True")
        if (
            last_message.role == "assistant"
            and last_message.content is not None
            and isinstance(last_message.content, str)
        ):
            if model_response.content is None:
                model_response.content = ""
            model_response.content += last_message.content

    def handle_post_tool_call_messages(self, messages: List[Message], model_response: ModelResponse) -> ModelResponse:
        last_message = messages[-1]
        if last_message.stop_after_tool_call:
            self._handle_stop_after_tool_calls(last_message, model_response)
        else:
            response_after_tool_calls = self.response(messages=messages)
            self._handle_response_after_tool_calls(response_after_tool_calls, model_response)
        return model_response

    async def ahandle_post_tool_call_messages(
        self, messages: List[Message], model_response: ModelResponse
    ) -> ModelResponse:
        last_message = messages[-1]
        if last_message.stop_after_tool_call:
            self._handle_stop_after_tool_calls(last_message, model_response)
        else:
            response_after_tool_calls = await self.aresponse(messages=messages)
            self._handle_response_after_tool_calls(response_after_tool_calls, model_response)
        return model_response

    def handle_post_tool_call_messages_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        last_message = messages[-1]
        if last_message.stop_after_tool_call:
            logger.debug("Stopping execution as stop_after_tool_call=True")
            if (
                last_message.role == "assistant"
                and last_message.content is not None
                and isinstance(last_message.content, str)
            ):
                yield ModelResponse(content=last_message.content)
        else:
            yield from self.response_stream(messages=messages)

    async def ahandle_post_tool_call_messages_stream(self, messages: List[Message]) -> Any:
        last_message = messages[-1]
        if last_message.stop_after_tool_call:
            logger.debug("Stopping execution as stop_after_tool_call=True")
            if (
                last_message.role == "assistant"
                and last_message.content is not None
                and isinstance(last_message.content, str)
            ):
                yield ModelResponse(content=last_message.content)
        else:
            async for model_response in self.aresponse_stream(messages=messages):  # type: ignore
                yield model_response

    def add_usage_metrics_to_assistant_message(self, assistant_message: Message, response_usage: Any) -> None:
        """
        Add usage metrics from the model provider to the assistant message.

        Args:
            assistant_message: Message to update with metrics
            response_usage: Usage data from model provider
        """
        # Standard token metrics
        if hasattr(response_usage, "input_tokens"):
            assistant_message.metrics.input_tokens = response_usage.input_tokens
        if hasattr(response_usage, "output_tokens"):
            assistant_message.metrics.output_tokens = response_usage.output_tokens
        if hasattr(response_usage, "prompt_tokens"):
            assistant_message.metrics.input_tokens = response_usage.prompt_tokens
            assistant_message.metrics.prompt_tokens = response_usage.prompt_tokens
        if hasattr(response_usage, "completion_tokens"):
            assistant_message.metrics.output_tokens = response_usage.completion_tokens
            assistant_message.metrics.completion_tokens = response_usage.completion_tokens
        if hasattr(response_usage, "total_tokens"):
            assistant_message.metrics.total_tokens = response_usage.total_tokens
        else:
            assistant_message.metrics.total_tokens = (
                assistant_message.metrics.input_tokens + assistant_message.metrics.output_tokens
            )

        # Additional timing metrics (e.g., from Groq)
        if assistant_message.metrics.additional_metrics is None:
            assistant_message.metrics.additional_metrics = {}

        additional_metrics = [
            "prompt_time",
            "completion_time",
            "queue_time",
            "total_time",
        ]

        for metric in additional_metrics:
            if hasattr(response_usage, metric) and getattr(response_usage, metric) is not None:
                assistant_message.metrics.additional_metrics[metric] = getattr(response_usage, metric)

        # Token details (e.g., from OpenAI)
        if hasattr(response_usage, "prompt_tokens_details"):
            if isinstance(response_usage.prompt_tokens_details, dict):
                assistant_message.metrics.prompt_tokens_details = response_usage.prompt_tokens_details
            elif hasattr(response_usage.prompt_tokens_details, "model_dump"):
                assistant_message.metrics.prompt_tokens_details = response_usage.prompt_tokens_details.model_dump(
                    exclude_none=True
                )

        if hasattr(response_usage, "completion_tokens_details"):
            if isinstance(response_usage.completion_tokens_details, dict):
                assistant_message.metrics.completion_tokens_details = response_usage.completion_tokens_details
            elif hasattr(response_usage.completion_tokens_details, "model_dump"):
                assistant_message.metrics.completion_tokens_details = (
                    response_usage.completion_tokens_details.model_dump(exclude_none=True)
                )

    def populate_assistant_message(
        self,
        assistant_message: Message,
        model_response: ModelResponse,
    ) -> Message:
        """
        Populate an assistant message using a ModelResponse.

        Args:
            assistant_message: The assistant message to populate
            model_response: Parsed response from the model provider

        Returns:
            Message: The populated assistant message
        """
        # Add role to assistant message
        if model_response.role is not None:
            assistant_message.role = model_response.role

        # Add content to assistant message
        if model_response.content is not None:
            assistant_message.content = model_response.content

        # Add tool calls to assistant message
        if model_response.tool_calls is not None and len(model_response.tool_calls) > 0:
            try:
                assistant_message.tool_calls = [t.model_dump() for t in model_response.tool_calls]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")

        # Add audio to assistant message
        if model_response.audio is not None:
            assistant_message.audio_output = model_response.audio

        # Add usage metrics if provided
        if model_response.response_usage is not None:
            self.add_usage_metrics_to_assistant_message(
                assistant_message=assistant_message, response_usage=model_response.response_usage
            )

        return assistant_message

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Generate a response from the model.

        Args:
            messages: List of messages in the conversation

        Returns:
            ModelResponse: The model's response
        """
        logger.debug(f"---------- {self.get_provider()} Response Start ----------")
        self._log_messages(messages)

        # Create assistant message
        assistant_message = Message(role=self.assistant_message_role)

        # Generate response
        assistant_message.metrics.start_timer()
        response = self.invoke(messages=messages)
        assistant_message.metrics.stop_timer()

        # Parse model response
        model_response = self.parse_model_response(response)

        # Add parsed data to assistant message
        if model_response.parsed is not None:
            model_response.parsed = model_response.parsed

        # Populate the assistant message
        self.populate_assistant_message(assistant_message=assistant_message, model_response=model_response)

        # Add assistant message to messages
        messages.append(assistant_message)

        # Log response and metrics
        assistant_message.log(metrics=True)

        # Update model response with assistant message content and audio
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()
        if assistant_message.audio_output is not None:
            model_response.audio = assistant_message.audio_output

        # Handle tool calls
        if (
            self.handle_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
                **model_response.extra,  # Any other values set on the provider response is passed here
            )
            is not None
        ):
            return self.handle_post_tool_call_messages(messages=messages, model_response=model_response)

        logger.debug(f"---------- {self.get_provider()} Response End ----------")
        return model_response

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        """
        Generate an asynchronous response from the model.

        Args:
            messages: List of messages in the conversation
        """
        logger.debug(f"---------- {self.get_provider()} Async Response Start ----------")
        self._log_messages(messages)

        # Create assistant message
        assistant_message = Message(role=self.assistant_message_role)

        # Generate response
        assistant_message.metrics.start_timer()
        response = await self.ainvoke(messages=messages)
        assistant_message.metrics.stop_timer()

        # Parse provider response
        model_response = self.parse_model_response(response)

        # Add parsed data to assistant message
        if model_response.parsed is not None:
            model_response.parsed = model_response.parsed

        # Populate the assistant message
        self.populate_assistant_message(assistant_message=assistant_message, model_response=model_response)

        # Add assistant message to messages
        messages.append(assistant_message)

        # Log response and metrics
        assistant_message.log(metrics=True)

        # Update model response with assistant message content and audio
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()
        if assistant_message.audio_output is not None:
            model_response.audio = assistant_message.audio_output

        # Handle tool calls
        if (
            await self.ahandle_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
                **model_response.extra,  # Any other values set on the provider response is passed here
            )
            is not None
        ):
            return await self.ahandle_post_tool_call_messages(messages=messages, model_response=model_response)

        logger.debug(f"---------- {self.get_provider()} Async Response End ----------")
        return model_response

    def update_message_data_and_assistant_message(
        self, model_response: ModelResponse, assistant_message: Message, message_data: MessageData
    ) -> ModelResponse:
        """Update the message data and assistant message with the model response."""

        # Update metrics
        assistant_message.metrics.completion_tokens += 1
        if not assistant_message.metrics.time_to_first_token:
            assistant_message.metrics.set_time_to_first_token()

        # Update message_data content
        if model_response.content is not None:
            message_data.response_content += model_response.content

        # Update message_data tool calls
        if model_response.tool_calls is not None:
            if message_data.response_tool_calls is None:
                message_data.response_tool_calls = []
            message_data.response_tool_calls.extend(model_response.tool_calls)

        if model_response.audio is not None:
            message_data.response_audio = model_response.audio

        if model_response.extra is not None:
            message_data.extra.update(model_response.extra)

        if model_response.response_usage is not None:
            self.add_usage_metrics_to_assistant_message(
                assistant_message=assistant_message, response_usage=model_response.response_usage
            )

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from the model.

        Args:
            messages: List of messages in the conversation

        Returns:
            Iterator[ModelResponse]: Iterator of model responses
        """
        logger.debug(f"---------- {self.get_provider()} Response Stream Start ----------")
        self._log_messages(messages)
        message_data: MessageData = MessageData()

        # Create assistant message
        assistant_message = Message(role=self.assistant_message_role)

        # Generate response
        assistant_message.metrics.start_timer()
        for response in self.invoke_stream(messages=messages):
            model_response = self.parse_model_response_chunk(response)
            if model_response is not None:
                yield model_response
                self.update_message_data_and_assistant_message(
                    model_response=model_response, assistant_message=assistant_message, message_data=message_data
                )
        assistant_message.metrics.stop_timer()

        # Add content and audio to assistant message
        if message_data.response_content != "":
            assistant_message.content = message_data.response_content
        if message_data.response_audio is not None:
            assistant_message.audio_output = message_data.response_audio

        # Add tool calls to assistant message
        if message_data.response_tool_calls is not None and len(message_data.response_tool_calls) > 0:
            parsed_tool_calls = self.parse_tool_calls(message_data.response_tool_calls)
            if len(parsed_tool_calls) > 0:
                assistant_message.tool_calls = parsed_tool_calls

        # Add assistant message to messages
        messages.append(assistant_message)

        # Log response and metrics
        assistant_message.log(metrics=True)

        # Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self.handle_stream_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                **message_data.extra,  # Any other values set on the provider response is passed here
            )
            yield from self.handle_post_tool_call_messages_stream(messages=messages)

        logger.debug(f"---------- {self.get_provider()} Response Stream End ----------")

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from the model.

        Args:
            messages: List of messages in the conversation

        Returns:
            Any: Async iterator of model responses
        """
        logger.debug(f"---------- {self.get_provider()} Async Response Stream Start ----------")
        self._log_messages(messages)
        message_data = MessageData()

        # Create assistant message
        assistant_message = Message(role=self.assistant_message_role)

        # Generate response
        assistant_message.metrics.start_timer()
        async for response in self.ainvoke_stream(messages=messages):
            model_response = self.parse_model_response_chunk(response)
            if model_response is not None:
                yield model_response
                self.update_message_data_and_assistant_message(
                    model_response=model_response, assistant_message=assistant_message, message_data=message_data
                )
        assistant_message.metrics.stop_timer()

        # Add content and audio to assistant message
        if message_data.response_content != "":
            assistant_message.content = message_data.response_content
        if message_data.response_audio is not None:
            assistant_message.audio_output = message_data.response_audio

        # Add tool calls to assistant message
        if message_data.response_tool_calls is not None and len(message_data.response_tool_calls) > 0:
            parsed_tool_calls = self.parse_tool_calls(message_data.response_tool_calls)
            if len(parsed_tool_calls) > 0:
                assistant_message.tool_calls = parsed_tool_calls

        # Add assistant message to messages
        messages.append(assistant_message)

        # Log response and metrics
        assistant_message.log(metrics=True)

        # Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            async for tool_call_response in self.ahandle_stream_tool_calls(
                assistant_message=assistant_message, messages=messages, **message_data.extra
            ):
                yield tool_call_response
            async for post_tool_call_response in self.ahandle_post_tool_call_messages_stream(messages=messages):
                yield post_tool_call_response

        logger.debug(f"---------- {self.get_provider()} Async Response Stream End ----------")

    def get_system_message_for_model(self) -> Optional[str]:
        return self.system_prompt

    def get_instructions_for_model(self) -> Optional[List[str]]:
        return self.instructions

    def clear(self) -> None:
        """Clears the Model's state."""

        self.response_format = None
        self._functions = None
        self._function_call_stack = None

    def __deepcopy__(self, memo):
        """Create a deep copy of the Model instance.

        Args:
            memo (dict): Dictionary of objects already copied during the current copying pass.

        Returns:
            Model: A new Model instance with deeply copied attributes.
        """
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        new_model = cls.__new__(cls)
        memo[id(self)] = new_model

        # Deep copy all attributes
        for k, v in self.__dict__.items():
            if k in {"response_format", "tools", "_functions", "_function_call_stack"}:
                continue
            setattr(new_model, k, deepcopy(v, memo))

        # Clear the new model to remove any references to the old model
        new_model.clear()
        return new_model
