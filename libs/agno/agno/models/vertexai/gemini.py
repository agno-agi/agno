import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from agno.models.base import Metrics, Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools import Function, Toolkit
from agno.utils.log import logger

try:
    from vertexai.generative_models import (
        Candidate,
        Content,
        FunctionDeclaration,
        GenerationResponse,
        GenerativeModel,
        Part,
    )
    from vertexai.generative_models import (
        Tool as GeminiTool,
    )
except (ModuleNotFoundError, ImportError):
    raise ImportError(
        "`google-cloud-aiplatform` not installed. Please install using `pip install google-cloud-aiplatform`"
    )


@dataclass
class MessageData:
    response_content: str = ""
    response_block: Content = None
    response_candidates: Optional[List[Candidate]] = None
    response_role: Optional[str] = None
    response_parts: Optional[List] = None
    response_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_usage: Optional[Dict[str, Any]] = None
    response_tool_call_block: Content = None


@dataclass
class Gemini(Model):
    """

    Class for interacting with the VertexAI Gemini API.

    Attributes:

        name (str): The name of the API. Default is "Gemini".
        model (str): The model name. Default is "gemini-1.5-flash-002".
        provider (str): The provider of the API. Default is "VertexAI".
        generation_config (Optional[Any]): The generation configuration.
        safety_settings (Optional[Any]): The safety settings.
        generative_model_request_params (Optional[Dict[str, Any]]): The generative model request parameters.
        function_declarations (Optional[List[FunctionDeclaration]]): The function declarations.
        client (Optional[GenerativeModel]): The GenerativeModel client.
    """

    id: str = "gemini-2.0-flash-exp"
    name: str = "Gemini"
    provider: str = "VertexAI"

    # Request parameters
    generation_config: Optional[Any] = None
    safety_settings: Optional[Any] = None
    generative_model_request_params: Optional[Dict[str, Any]] = None
    function_declarations: Optional[List[FunctionDeclaration]] = None

    # Gemini client
    client: Optional[GenerativeModel] = None

    def get_client(self) -> GenerativeModel:
        """
        Returns a GenerativeModel client.

        Returns:
            GenerativeModel: GenerativeModel client.
        """
        if self.client is None:
            self.client = GenerativeModel(model_name=self.id, **self.request_kwargs)
        return self.client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns the request parameters for the generative model.

        Returns:
            Dict[str, Any]: Request parameters for the generative model.
        """
        _request_params: Dict[str, Any] = {}
        if self.generation_config:
            _request_params["generation_config"] = self.generation_config
        if self.safety_settings:
            _request_params["safety_settings"] = self.safety_settings
        if self.generative_model_request_params:
            _request_params.update(self.generative_model_request_params)
        if self.function_declarations:
            _request_params["tools"] = [GeminiTool(function_declarations=self.function_declarations)]
        return _request_params

    def format_messages(self, messages: List[Message]) -> List[Content]:
        """
        Converts a list of Message objects to Gemini-compatible Content objects.

        Args:
            messages: List of Message objects containing various types of content

        Returns:
            List of Content objects formatted for Gemini's API
        """
        formatted_messages: List[Content] = []

        for msg in messages:
            if hasattr(msg, "response_tool_call_block") and msg.response_tool_call_block is not None:
                formatted_messages.append(Content(role=msg.role, parts=msg.response_tool_call_block.parts))
            else:
                if isinstance(msg.content, str) and msg.content:
                    parts = [Part.from_text(msg.content)]
                elif isinstance(msg.content, list):
                    parts = [Part.from_text(part) for part in msg.content if isinstance(part, str)]
                else:
                    parts = []
                role = "model" if msg.role in ["system", "developer"] else "user" if msg.role == "tool" else msg.role

                if parts:
                    formatted_messages.append(Content(role=role, parts=parts))
        return formatted_messages

    def format_functions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts function parameters to a Gemini-compatible format.

        Args:
            params (Dict[str, Any]): The original parameter's dictionary.

        Returns:
            Dict[str, Any]: The converted parameters dictionary compatible with Gemini.
        """
        formatted_params = {}
        for key, value in params.items():
            if key == "properties" and isinstance(value, dict):
                converted_properties = {}
                for prop_key, prop_value in value.items():
                    property_type = prop_value.get("type")
                    if isinstance(property_type, list):
                        # Create a copy to avoid modifying the original list
                        non_null_types = [t for t in property_type if t != "null"]
                        if non_null_types:
                            # Use the first non-null type
                            converted_type = non_null_types[0]
                        else:
                            # Default type if all types are 'null'
                            converted_type = "string"
                    else:
                        converted_type = property_type

                    converted_properties[prop_key] = {"type": converted_type}
                formatted_params[key] = converted_properties
            else:
                formatted_params[key] = value
        return formatted_params

    def add_tool(
        self,
        tool: Union[Toolkit, Callable, Dict, Function],
        strict: bool = False,
        agent: Optional[Any] = None,
    ) -> None:
        """
        Adds tools to the model.

        Args:
            tool: The tool to add. Can be a Tool, Toolkit, Callable, dict, or Function.
            strict: If True, raise an error if the tool is not a Toolkit or Callable.
            agent: The agent to use for the tool.
        """
        if self.function_declarations is None:
            self.function_declarations = []

        # If the tool is a Tool or Dict, log a warning.
        if isinstance(tool, Dict):
            logger.warning("Tool of type 'dict' is not yet supported by Gemini.")

        # If the tool is a Callable or Toolkit, add its functions to the Model
        elif callable(tool) or isinstance(tool, Toolkit) or isinstance(tool, Function):
            if self._functions is None:
                self._functions: Dict[str, Any] = {}

            if isinstance(tool, Toolkit):
                # For each function in the toolkit, process entrypoint and add to self.tools
                for name, func in tool.functions.items():
                    # If the function does not exist in self._functions, add to self.tools
                    if name not in self._functions:
                        func._agent = agent
                        func.process_entrypoint()
                        self._functions[name] = func
                        function_declaration = FunctionDeclaration(
                            name=func.name,
                            description=func.description,
                            parameters=self.format_functions(func.parameters),
                        )
                        self.function_declarations.append(function_declaration)
                        logger.debug(f"Function {name} from {tool.name} added to model.")

            elif isinstance(tool, Function):
                if tool.name not in self._functions:
                    tool._agent = agent
                    tool.process_entrypoint()
                    self._functions[tool.name] = tool
                    function_declaration = FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters=self.format_functions(tool.parameters),
                    )
                    self.function_declarations.append(function_declaration)
                    logger.debug(f"Function {tool.name} added to model.")

            elif callable(tool):
                try:
                    function_name = tool.__name__
                    if function_name not in self._functions:
                        func = Function.from_callable(tool)
                        self._functions[func.name] = func
                        function_declaration = FunctionDeclaration(
                            name=func.name,
                            description=func.description,
                            parameters=self.format_functions(func.parameters),
                        )
                        self.function_declarations.append(function_declaration)
                        logger.debug(f"Function '{func.name}' added to model.")
                except Exception as e:
                    logger.warning(f"Could not add function {tool}: {e}")

    def invoke(self, messages: List[Message]) -> GenerationResponse:
        """
        Send a generate content request to VertexAI and return the response.

        Args:
            messages: List of Message objects containing various types of content

        Returns:
            GenerationResponse object containing the response content
        """
        return self.get_client().generate_content(contents=self.format_messages(messages))

    def invoke_stream(self, messages: List[Message]) -> Iterator[GenerationResponse]:
        """
        Send a generate content request to VertexAI and return the response.

        Args:
            messages: List of Message objects containing various types of content

        Returns:
            Iterator[GenerationResponse] object containing the response content
        """
        yield from self.get_client().generate_content(
            contents=self.format_messages(messages),
            stream=True,
        )

    def update_usage_metrics(
        self,
        assistant_message: Message,
        metrics: Metrics,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Update usage metrics for the assistant message.

        Args:
            assistant_message: Message object containing the response content
            metrics: Metrics object containing the usage metrics
            usage: Dict[str, Any] object containing the usage metrics
        """
        if usage:
            metrics.input_tokens = usage.prompt_token_count or 0  # type: ignore
            metrics.output_tokens = usage.candidates_token_count or 0  # type: ignore
            metrics.total_tokens = usage.total_token_count or 0  # type: ignore

        self._update_model_metrics(metrics_for_run=metrics)
        self._update_assistant_message_metrics(assistant_message=assistant_message, metrics_for_run=metrics)

    def create_assistant_message(self, response: GenerationResponse, metrics: Metrics) -> Message:
        """
        Create an assistant message from the GenerationResponse.

        Args:
            response: GenerationResponse object containing the response content
            metrics: Metrics object containing the usage metrics

        Returns:
            Message object containing the assistant message
        """
        message_data = MessageData()

        message_data.response_candidates = response.candidates
        message_data.response_block = response.candidates[0].content
        message_data.response_role = message_data.response_block.role
        message_data.response_parts = message_data.response_block.parts
        message_data.response_usage = response.usage_metadata

        # -*- Parse response
        if message_data.response_parts is not None:
            for part in message_data.response_parts:
                part_dict = type(part).to_dict(part)

                # Extract text if present
                if "text" in part_dict:
                    message_data.response_content = part_dict.get("text")

                # Parse function calls
                if "function_call" in part_dict:
                    message_data.response_tool_call_block = response.candidates[0].content
                    message_data.response_tool_calls.append(
                        {
                            "type": "function",
                            "function": {
                                "name": part_dict.get("function_call").get("name"),
                                "arguments": json.dumps(part_dict.get("function_call").get("args")),
                            },
                        }
                    )

        # -*- Create assistant message
        assistant_message = Message(
            role=message_data.response_role or "model",
            content=message_data.response_content,
            response_tool_call_block=message_data.response_tool_call_block,
        )

        # -*- Update assistant message if tool calls are present
        if len(message_data.response_tool_calls) > 0:
            assistant_message.tool_calls = message_data.response_tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(
            assistant_message=assistant_message, metrics=metrics, usage=message_data.response_usage
        )

        return assistant_message

    def format_function_call_results(
        self,
        function_call_results: List[Message],
        messages: List[Message],
    ):
        """
        Processes the results of function calls and appends them to messages.

        Args:
            function_call_results (List[Message]): The results from running function calls.
            messages (List[Message]): The list of conversation messages.
        """
        if function_call_results:
            contents, parts = zip(
                *[
                    (
                        result.content,
                        Part.from_function_response(name=result.tool_name, response={"content": result.content}),
                    )
                    for result in function_call_results
                ]
            )

            messages.append(Message(role="tool", content=contents))

    def handle_tool_calls(self, assistant_message: Message, messages: List[Message], model_response: ModelResponse):
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): A list of messages.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[ModelResponse]: The updated model response.
        """
        if assistant_message.tool_calls:
            if model_response.tool_calls is None:
                model_response.tool_calls = []

            model_response.content = assistant_message.get_content_string() or ""
            function_calls_to_run = self._get_function_calls_to_run(
                assistant_message, messages, error_response_role="tool"
            )

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    model_response.content += f"\n - Running: {function_calls_to_run[0].get_call_str()}\n\n"
                elif len(function_calls_to_run) > 1:
                    model_response.content += "\nRunning:"
                    for _f in function_calls_to_run:
                        model_response.content += f"\n - {_f.get_call_str()}"
                    model_response.content += "\n\n"

            function_call_results: List[Message] = []
            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run,
                function_call_results=function_call_results,
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)

            self.format_function_call_results(function_call_results, messages)

            return model_response
        return None

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Send a generate content request to VertexAI and return the response.

        Args:
            messages: List of Message objects containing various types of content

        Returns:
            ModelResponse object containing the response content
        """
        logger.debug("---------- VertexAI Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()
        metrics = Metrics()

        metrics.start_response_timer()
        response: GenerationResponse = self.invoke(messages=messages)
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = self.create_assistant_message(response=response, metrics=metrics)
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if self.handle_tool_calls(assistant_message, messages, model_response):
            response_after_tool_calls = self.response(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # -*- Update model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        # -*- Remove tool call blocks and tool call results from messages
        for m in messages:
            if hasattr(m, "response_tool_call_block"):
                m.response_tool_call_block = None
            if hasattr(m, "tool_call_result"):
                m.tool_call_result = None

        logger.debug("---------- VertexAI Response End ----------")
        return model_response

    def handle_stream_tool_calls(self, assistant_message: Message, messages: List[Message]):
        """
        Parse and run function calls and append the results to messages.

        Args:
            assistant_message (Message): The assistant message containing tool calls.
            messages (List[Message]): The list of conversation messages.

        Yields:
            Iterator[ModelResponse]: Yields model responses during function execution.
        """
        if assistant_message.tool_calls:
            function_calls_to_run = self._get_function_calls_to_run(
                assistant_message, messages, error_response_role="tool"
            )

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    yield ModelResponse(content=f"\n - Running: {function_calls_to_run[0].get_call_str()}\n\n")
                elif len(function_calls_to_run) > 1:
                    yield ModelResponse(content="\nRunning:")
                    for _f in function_calls_to_run:
                        yield ModelResponse(content=f"\n - {_f.get_call_str()}")
                    yield ModelResponse(content="\n\n")

            function_call_results: List[Message] = []
            for intermediate_model_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results
            ):
                yield intermediate_model_response

            self.format_function_call_results(function_call_results, messages)

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Send a generate content request to VertexAI and return the response.

        Args:
            messages: List of Message objects containing various types of content

        Yields:
            Iterator[ModelResponse]: Yields model responses during function execution
        """
        logger.debug("---------- VertexAI Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics = Metrics()

        metrics.start_response_timer()
        for response in self.invoke_stream(messages=messages):
            # -*- Parse response
            message_data.response_block = response.candidates[0].content
            if message_data.response_block is not None:
                metrics.time_to_first_token = metrics.response_timer.elapsed
            message_data.response_role = message_data.response_block.role
            if message_data.response_block.parts:
                message_data.response_parts = message_data.response_block.parts

            if message_data.response_parts is not None:
                for part in message_data.response_parts:
                    part_dict = type(part).to_dict(part)

                    # -*- Yield text if present
                    if "text" in part_dict:
                        text = part_dict.get("text")
                        yield ModelResponse(content=text)
                        message_data.response_content += text

                    # -*- Skip function calls if there are no parts
                    if not message_data.response_block.parts and message_data.response_parts:
                        continue
                    # -*- Parse function calls
                    if "function_call" in part_dict:
                        message_data.response_tool_call_block = response.candidates[0].content
                        message_data.response_tool_calls.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": part_dict.get("function_call").get("name"),
                                    "arguments": json.dumps(part_dict.get("function_call").get("args")),
                                },
                            }
                        )
            message_data.response_usage = response.usage_metadata

        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(
            role=message_data.response_role or "assistant",
            content=message_data.response_content,
            response_tool_call_block=message_data.response_tool_call_block,
        )

        # -*-  Update assistant message if tool calls are present
        if len(message_data.response_tool_calls) > 0:
            assistant_message.tool_calls = message_data.response_tool_calls

        self.update_usage_metrics(
            assistant_message=assistant_message, metrics=metrics, usage=message_data.response_usage
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self.handle_stream_tool_calls(assistant_message, messages)
            yield from self.response_stream(messages=messages)

        # -*- Remove tool call blocks and tool call results from messages
        for m in messages:
            if hasattr(m, "response_tool_call_block"):
                m.response_tool_call_block = None
            if hasattr(m, "tool_call_result"):
                m.tool_call_result = None
        logger.debug("---------- VertexAI Response End ----------")

    async def ainvoke(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def ainvoke_stream(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def aresponse_stream(self, messages: List[Message]) -> ModelResponse:
        raise NotImplementedError(f"Async not supported on {self.name}.")
