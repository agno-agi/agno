import asyncio
import collections.abc
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from types import GeneratorType
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from agno.exceptions import AgentRunException
from agno.media import Audio, Image
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools import Toolkit
from agno.tools.function import Function, FunctionCall
from agno.utils.log import logger
from agno.utils.timer import Timer
from agno.utils.tools import get_function_call_for_tool_call


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

    def start_response_timer(self):
        self.response_timer.start()

    def stop_response_timer(self):
        self.response_timer.stop()

    def _log(self, metric_lines: list[str]):
        logger.debug("**************** METRICS START ****************")
        for line in metric_lines:
            logger.debug(line)
        logger.debug("**************** METRICS END ******************")

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
        if self.prompt_tokens_details is not None:
            metric_lines.append(f"* Prompt tokens details:       {self.prompt_tokens_details}")
        if self.completion_tokens_details is not None:
            metric_lines.append(f"* Completion tokens details:   {self.completion_tokens_details}")
        self._log(metric_lines=metric_lines)


@dataclass
class StreamData:
    response_content: str = ""
    response_tool_calls: Optional[List[Any]] = None
    completion_tokens: int = 0
    response_prompt_tokens: int = 0
    response_completion_tokens: int = 0
    response_total_tokens: int = 0
    time_to_first_token: Optional[float] = None
    response_timer: Timer = field(default_factory=Timer)


@dataclass
class Model(ABC):
    # ID of the model to use.
    id: str
    # Name for this Model. This is not sent to the Model API.
    name: Optional[str] = None
    # Provider for this Model. This is not sent to the Model API.
    provider: Optional[str] = None
    # Metrics collected for this Model. This is not sent to the Model API.
    metrics: Dict[str, Any] = field(default_factory=dict)
    # Used for structured_outputs
    response_format: Optional[Any] = None

    # A list of tools provided to the Model.
    # Tools are functions the model may generate JSON inputs for.
    # If you provide a dict, it is not called by the model.
    # Always add tools using the add_tool() method.
    tools: Optional[List[Dict]] = None

    # Controls which (if any) function is called by the model.
    # "none" means the model will not call a function and instead generates a message.
    # "auto" means the model can pick between generating a message or calling a function.
    # Specifying a particular function via {"type: "function", "function": {"name": "my_function"}}
    #   forces the model to call that function.
    # "none" is the default when no functions are present. "auto" is the default if functions are present.
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None

    # If True, shows function calls in the response.  Is not compatible with response_model
    show_tool_calls: Optional[bool] = None

    # Maximum number of tool calls allowed.
    tool_call_limit: Optional[int] = None

    # -*- Functions available to the Model to call -*-
    # Functions extracted from the tools.
    # Note: These are not sent to the Model API and are only used for execution + deduplication.
    _functions: Optional[Dict[str, Function]] = None
    # Function call stack.
    _function_call_stack: Optional[List[FunctionCall]] = None

    # System prompt from the model added to the Agent.
    system_prompt: Optional[str] = None
    # Instructions from the model added to the Agent.
    instructions: Optional[List[str]] = None

    # Session ID of the calling Agent or Workflow.
    session_id: Optional[str] = None
    # Whether to use the structured outputs with this Model.
    structured_outputs: Optional[bool] = None
    # Whether the Model supports native structured outputs.
    supports_structured_outputs: bool = False
    # Whether to override the system role.
    override_system_role: bool = False
    # The role to map the system message to.
    system_message_role: str = "system"

    def __post_init__(self):
        if self.provider is None and self.name is not None:
            self.provider = f"{self.name} ({self.id})"

    def to_dict(self) -> Dict[str, Any]:
        fields = {"name", "id", "provider", "metrics"}
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
    def response(self, messages: List[Message]) -> ModelResponse:
        pass

    @abstractmethod
    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        pass

    @abstractmethod
    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        pass

    @abstractmethod
    async def aresponse_stream(self, messages: List[Message]) -> Any:
        pass

    def _log_messages(self, messages: List[Message]) -> None:
        """
        Log messages for debugging.
        """
        for m in messages:
            m.log()

    @staticmethod
    def _update_assistant_message_metrics(assistant_message: Message, metrics_for_run: Metrics = Metrics()) -> None:
        assistant_message.metrics["time"] = metrics_for_run.response_timer.elapsed
        if metrics_for_run.input_tokens is not None:
            assistant_message.metrics["input_tokens"] = metrics_for_run.input_tokens
        if metrics_for_run.output_tokens is not None:
            assistant_message.metrics["output_tokens"] = metrics_for_run.output_tokens
        if metrics_for_run.total_tokens is not None:
            assistant_message.metrics["total_tokens"] = metrics_for_run.total_tokens
        if metrics_for_run.time_to_first_token is not None:
            assistant_message.metrics["time_to_first_token"] = metrics_for_run.time_to_first_token

    def _update_model_metrics(
        self,
        metrics_for_run: Metrics = Metrics(),
    ) -> None:
        self.metrics.setdefault("response_times", []).append(metrics_for_run.response_timer.elapsed)
        if metrics_for_run.input_tokens is not None:
            self.metrics["input_tokens"] = self.metrics.get("input_tokens", 0) + metrics_for_run.input_tokens
        if metrics_for_run.output_tokens is not None:
            self.metrics["output_tokens"] = self.metrics.get("output_tokens", 0) + metrics_for_run.output_tokens
        if metrics_for_run.total_tokens is not None:
            self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + metrics_for_run.total_tokens
        if metrics_for_run.time_to_first_token is not None:
            self.metrics.setdefault("time_to_first_token", []).append(metrics_for_run.time_to_first_token)

    def _get_function_calls_to_run(
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

    def add_tool(
        self, tool: Union[Toolkit, Callable, Dict, Function], strict: bool = False, agent: Optional[Any] = None
    ) -> None:
        if self.tools is None:
            self.tools = []

        # If the tool is a Dict, add it directly to the Model
        if isinstance(tool, Dict):
            if tool not in self.tools:
                self.tools.append(tool)
                logger.debug(f"Added tool {tool} to model.")

        # If the tool is a Callable or Toolkit, process and add to the Model
        elif callable(tool) or isinstance(tool, Toolkit) or isinstance(tool, Function):
            if self._functions is None:
                self._functions = {}

            if isinstance(tool, Toolkit):
                # For each function in the toolkit, process entrypoint and add to self.tools
                for name, func in tool.functions.items():
                    # If the function does not exist in self.functions, add to self.tools
                    if name not in self._functions:
                        func._agent = agent
                        func.process_entrypoint(strict=strict)
                        if strict and self.supports_structured_outputs:
                            func.strict = True
                        self._functions[name] = func
                        self.tools.append({"type": "function", "function": func.to_dict()})
                        logger.debug(f"Function {name} from {tool.name} added to model.")

            elif isinstance(tool, Function):
                if tool.name not in self._functions:
                    tool._agent = agent
                    tool.process_entrypoint(strict=strict)
                    if strict and self.supports_structured_outputs:
                        tool.strict = True
                    self._functions[tool.name] = tool
                    self.tools.append({"type": "function", "function": tool.to_dict()})
                    logger.debug(f"Function {tool.name} added to model.")

            elif callable(tool):
                try:
                    function_name = tool.__name__
                    if function_name not in self._functions:
                        func = Function.from_callable(tool, strict=strict)
                        func._agent = agent
                        if strict and self.supports_structured_outputs:
                            func.strict = True
                        self._functions[func.name] = func
                        self.tools.append({"type": "function", "function": func.to_dict()})
                        logger.debug(f"Function {func.name} added to model.")
                except Exception as e:
                    logger.warning(f"Could not add function {tool}: {e}")

    def _handle_agent_exception(self, a_exc: AgentRunException, additional_messages: List[Message]) -> None:
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

    def _create_function_call_result(
        self, fc: FunctionCall, success: bool, output: Optional[Union[List[Any], str]], timer: Timer, tool_role: str
    ) -> Message:
        """Create a function call result message."""
        return Message(
            role=tool_role,
            content=output if success else fc.error,
            tool_call_id=fc.call_id,
            tool_name=fc.function.name,
            tool_args=fc.arguments,
            tool_call_error=not success,
            stop_after_tool_call=fc.function.stop_after_tool_call,
            metrics={"time": timer.elapsed},
        )

    def _update_metrics(self, function_name: str, elapsed_time: float) -> None:
        """Update metrics for function calls."""
        if "tool_call_times" not in self.metrics:
            self.metrics["tool_call_times"] = {}
        if function_name not in self.metrics["tool_call_times"]:
            self.metrics["tool_call_times"][function_name] = []
        self.metrics["tool_call_times"][function_name].append(elapsed_time)

    def run_function_calls(
        self, function_calls: List[FunctionCall], function_call_results: List[Message], tool_role: str = "tool"
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
                        "role": tool_role,
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
                self._handle_agent_exception(a_exc, additional_messages)
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
            function_call_result = self._create_function_call_result(
                fc, function_call_success, function_call_output, function_call_timer, tool_role
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

            # Update metrics and function call results
            self._update_metrics(fc.function.name, function_call_timer.elapsed)
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

    async def arun_function_calls(
        self, function_calls: List[FunctionCall], function_call_results: List[Message], tool_role: str = "tool"
    ):
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
                        "role": tool_role,
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
                self._handle_agent_exception(a_exc, additional_messages)
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
            function_call_result = self._create_function_call_result(
                fc, function_call_success, function_call_output, function_call_timer, tool_role
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

            # Update metrics and function call results
            self._update_metrics(fc.function.name, function_call_timer.elapsed)
            function_call_results.append(function_call_result)
            self._function_call_stack.append(fc)

            # Check function call limit
            if self.tool_call_limit and len(self._function_call_stack) >= self.tool_call_limit:
                self.tool_choice = "none"
                break

        # Add any additional messages at the end
        if additional_messages:
            function_call_results.extend(additional_messages)

    def _prepare_function_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        tool_role: str = "tool",
    ) -> Tuple[List[FunctionCall], List[Message]]:
        """
        Prepare function calls from tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message containing tool calls
            messages (List[Message]): The list of messages to append tool responses to
            model_response (ModelResponse): The model response to update
            tool_role (str): The role of the tool call. Defaults to "tool".
        Returns:
            Tuple[List[FunctionCall], List[Message]]: Tuple of function calls to run and function call results
        """
        if model_response.content is None:
            model_response.content = ""
        if model_response.tool_calls is None:
            model_response.tool_calls = []

        function_call_results: List[Message] = []
        function_calls_to_run: List[FunctionCall] = self._get_function_calls_to_run(assistant_message, messages)

        if self.show_tool_calls:
            if len(function_calls_to_run) == 1:
                model_response.content += f" - Running: {function_calls_to_run[0].get_call_str()}\n\n"
            elif len(function_calls_to_run) > 1:
                model_response.content += "Running:"
                for _f in function_calls_to_run:
                    model_response.content += f"\n - {_f.get_call_str()}"
                model_response.content += "\n\n"

        return function_calls_to_run, function_call_results

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
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            function_calls_to_run, function_call_results = self._prepare_function_calls(
                assistant_message=assistant_message,
                messages=messages,
                model_response=model_response,
                tool_role=tool_role,
            )

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)  # type: ignore  # model_response.tool_calls are initialized before calling this method

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            return model_response
        return None

    async def ahandle_tool_calls(
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
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
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
                    model_response.tool_calls.extend(function_call_response.tool_calls)  # type: ignore  # model_response.tool_calls are initialized before calling this method

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

            return model_response
        return None

    def _prepare_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        tool_role: str = "tool",
    ) -> Tuple[List[FunctionCall], List[Message]]:
        """
        Prepare function calls from tool calls in the assistant message for streaming.

        Args:
            assistant_message (Message): The assistant message containing tool calls
            messages (List[Message]): The list of messages to append tool responses to
            tool_role (str): The role to use for tool messages

        Returns:
            Tuple[List[FunctionCall], List[Message]]: Tuple of function calls to run and function call results
        """
        function_calls_to_run: List[FunctionCall] = []
        function_call_results: List[Message] = []

        for tool_call in assistant_message.tool_calls:  # type: ignore  # assistant_message.tool_calls are checked before calling this method
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

        return function_calls_to_run, function_call_results

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
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            function_calls_to_run, function_call_results = self._prepare_stream_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                tool_role=tool_role,
            )

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

    async def ahandle_stream_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        tool_role: str = "tool",
    ):
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
            function_calls_to_run, function_call_results = self._prepare_stream_tool_calls(
                assistant_message=assistant_message,
                messages=messages,
                tool_role=tool_role,
            )

            if self.show_tool_calls:
                yield ModelResponse(content="\nRunning:")
                for _f in function_calls_to_run:
                    yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                yield ModelResponse(content="\n\n")

            async for function_call_response in self.arun_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                yield function_call_response

            if len(function_call_results) > 0:
                messages.extend(function_call_results)

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

    def _process_image_url(self, image_url: str) -> Dict[str, Any]:
        """Process image (base64 or URL)."""

        if image_url.startswith("data:image") or image_url.startswith(("http://", "https://")):
            return {"type": "image_url", "image_url": {"url": image_url}}
        else:
            raise ValueError("Image URL must start with 'data:image' or 'http(s)://'.")

    def _process_image_path(self, image_path: Union[Path, str]) -> Dict[str, Any]:
        """Process image ( file path)."""
        # Process local file image
        import base64
        import mimetypes

        path = image_path if isinstance(image_path, Path) else Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            image_url = f"data:{mime_type};base64,{base64_image}"
            return {"type": "image_url", "image_url": {"url": image_url}}

    def _process_bytes_image(self, image: bytes) -> Dict[str, Any]:
        """Process bytes image data."""
        import base64

        base64_image = base64.b64encode(image).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{base64_image}"
        return {"type": "image_url", "image_url": {"url": image_url}}

    def _process_image(self, image: Image) -> Optional[Dict[str, Any]]:
        """Process an image based on the format."""

        if image.url is not None:
            image_payload = self._process_image_url(image.url)

        elif image.filepath is not None:
            image_payload = self._process_image_path(image.filepath)

        elif image.content is not None:
            image_payload = self._process_bytes_image(image.content)

        else:
            logger.warning(f"Unsupported image type: {type(image)}")
            return None

        if image.detail:
            image_payload["image_url"]["detail"] = image.detail

        return image_payload

    def add_images_to_message(self, message: Message, images: Sequence[Image]) -> Message:
        """
        Add images to a message for the model. By default, we use the OpenAI image format but other Models
        can override this method to use a different image format.

        Args:
            message: The message for the Model
            images: Sequence of images in various formats:
                - str: base64 encoded image, URL, or file path
                - Dict: pre-formatted image data
                - bytes: raw image data

        Returns:
            Message content with images added in the format expected by the model
        """
        # If no images are provided, return the message as is
        if len(images) == 0:
            return message

        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if not isinstance(message.content, str):
            return message

        # Create a default message content with text
        message_content_with_image: List[Dict[str, Any]] = [{"type": "text", "text": message.content}]

        # Add images to the message content
        for image in images:
            try:
                image_data = self._process_image(image)
                if image_data:
                    message_content_with_image.append(image_data)
            except Exception as e:
                logger.error(f"Failed to process image: {str(e)}")
                continue

        # Update the message content with the images
        message.content = message_content_with_image
        return message

    @staticmethod
    def add_audio_to_message(message: Message, audio: Sequence[Audio]) -> Message:
        """
        Add audio to a message for the model. By default, we use the OpenAI audio format but other Models
        can override this method to use a different audio format.

        Args:
            message: The message for the Model
            audio: Pre-formatted audio data like {
                        "content": encoded_string,
                        "format": "wav"
                    }

        Returns:
            Message content with audio added in the format expected by the model
        """
        if len(audio) == 0:
            return message

        # Create a default message content with text
        message_content_with_audio: List[Dict[str, Any]] = [{"type": "text", "text": message.content}]

        for audio_snippet in audio:
            # This means the audio is raw data
            if audio_snippet.content:
                import base64

                encoded_string = base64.b64encode(audio_snippet.content).decode("utf-8")

                # Create a message with audio
                message_content_with_audio.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": encoded_string,
                            "format": audio_snippet.format,
                        },
                    },
                )

        # Update the message content with the audio
        message.content = message_content_with_audio
        message.audio = None  # The message should not have an audio component after this

        return message

    @staticmethod
    def _build_tool_calls(tool_calls_data: List[Any]) -> List[Dict[str, Any]]:
        """
        Build tool calls from tool call data.

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

    def get_system_message_for_model(self) -> Optional[str]:
        return self.system_prompt

    def get_instructions_for_model(self) -> Optional[List[str]]:
        return self.instructions

    def clear(self) -> None:
        """Clears the Model's state."""

        self.metrics = {}
        self._functions = None
        self._function_call_stack = None
        self.session_id = None

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
            if k in {"metrics", "_functions", "_function_call_stack", "session_id"}:
                continue
            setattr(new_model, k, deepcopy(v, memo))

        # Clear the new model to remove any references to the old model
        new_model.clear()
        return new_model
