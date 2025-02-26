import json
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, AsyncIterator, Dict, Iterator, List, Mapping, Optional, Union

from agno.models.message import Message, MessageMetrics
from agno.models.ollama.chat import ChatResponse, Ollama, OllamaResponseUsage
from agno.models.response import ModelResponse
from agno.tools.function import FunctionCall
from agno.utils.log import logger
from agno.utils.timer import Timer
from agno.utils.tools import (
    extract_tool_call_from_string,
    remove_tool_calls_from_string,
)


@dataclass
class ToolCall:
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_usage: Optional[Mapping[str, Any]] = None
    response_is_tool_call: bool = field(default=False)
    is_closing_tool_call_tag: bool = field(default=False)
    tool_calls_counter: int = field(default=0)
    tool_call_content: str = field(default="")


@dataclass
class OllamaTools(Ollama):
    """
    An Ollama class that uses XML tags for tool calls.

    For more information, see: https://github.com/ollama/ollama/blob/main/docs/api.md
    """

    id: str = "llama3.2"
    name: str = "OllamaTools"
    provider: str = "Ollama"

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The API kwargs for the model.
        """
        base_params: Dict[str, Any] = {
            "format": self.format,
            "options": self.options,
            "keep_alive": self.keep_alive,
            "request_params": self.request_params,
        }
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}
        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def parse_provider_response(self, response: ChatResponse) -> ModelResponse:
        """
        Parse the provider response.

        Args:
            response (ChatResponse): The response from the provider.

        Returns:
            ModelResponse: The model response.
        """
        model_response = ModelResponse()
        # Get response message
        response_message = response.get("message")

        if response_message.get("role") is not None:
            model_response.role = response_message.get("role")

        content = response_message.get("content")
        if content is not None:
            model_response.content = content
            # Check for tool calls in content
            if "<tool_call>" in content and "</tool_call>" in content:
                if model_response.tool_calls is None:
                    model_response.tool_calls = []

                # Break the response into tool calls
                tool_call_responses = content.split("</tool_call>")
                for tool_call_response in tool_call_responses:
                    # Add back the closing tag if this is not the last tool call
                    if tool_call_response != tool_call_responses[-1]:
                        tool_call_response += "</tool_call>"

                    if "<tool_call>" in tool_call_response and "</tool_call>" in tool_call_response:
                        # Extract tool call string from response
                        tool_call_content = extract_tool_call_from_string(tool_call_response)
                        # Convert the extracted string to a dictionary
                        try:
                            tool_call_dict = json.loads(tool_call_content)
                        except json.JSONDecodeError:
                            raise ValueError(f"Could not parse tool call from: {tool_call_content}")

                        tool_call_name = tool_call_dict.get("name")
                        tool_call_args = tool_call_dict.get("arguments")
                        function_def = {
                            "name": tool_call_name,
                            "arguments": json.dumps(tool_call_args) if tool_call_args is not None else None,
                        }
                        model_response.tool_calls.append({"type": "function", "function": function_def})

        # Get response usage
        if response.get("done"):
            model_response.response_usage = OllamaResponseUsage(
                input_tokens=response.get("prompt_eval_count", 0),
                output_tokens=response.get("eval_count", 0),
                total_duration=response.get("total_duration", 0),
                load_duration=response.get("load_duration", 0),
                prompt_eval_duration=response.get("prompt_eval_duration", 0),
                eval_duration=response.get("eval_duration", 0),
            )
            if model_response.response_usage.input_tokens or model_response.response_usage.output_tokens:
                model_response.response_usage.total_tokens = (
                    model_response.response_usage.input_tokens + model_response.response_usage.output_tokens
                )

        return model_response

    def _create_function_call_result(
        self, fc: FunctionCall, success: bool, output: Optional[Union[List[Any], str]], timer: Timer
    ) -> Message:
        """Create a function call result message."""
        content = (
            "<tool_response>\n"
            + json.dumps({"name": fc.function.name, "content": output if success else fc.error})
            + "\n</tool_response>"
        )

        return Message(
            role=self.tool_message_role,
            content=content,
            tool_call_id=fc.call_id,
            tool_name=fc.function.name,
            tool_args=fc.arguments,
            tool_call_error=not success,
            stop_after_tool_call=fc.function.stop_after_tool_call,
            metrics=MessageMetrics(time=timer.elapsed),
        )

    def format_function_call_results(self, function_call_results: List[Message], messages: List[Message]) -> None:
        """
        Format the function call results and append them to the messages.

        Args:
            function_call_results (List[Message]): The list of function call results.
            messages (List[Message]): The list of messages.
        """
        if len(function_call_results) > 0:
            for _fc_message in function_call_results:
                _fc_message.content = (
                    "<tool_response>\n"
                    + json.dumps({"name": _fc_message.tool_name, "content": _fc_message.content})
                    + "\n</tool_response>"
                )
                messages.append(_fc_message)

    def _prepare_function_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
    ) -> List[FunctionCall]:
        """
        Prepare function calls from tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message containing tool calls
            messages (List[Message]): The list of messages to append tool responses to
            model_response (ModelResponse): The model response to update
        Returns:
            List[FunctionCall]: The function calls to run
        """
        if model_response.content is None:
            model_response.content = ""
        if model_response.tool_calls is None:
            model_response.tool_calls = []

        model_response.content = str(remove_tool_calls_from_string(assistant_message.get_content_string()))
        model_response.content += "\n\n"
        function_calls_to_run = self.get_function_calls_to_run(assistant_message, messages)

        if self.show_tool_calls:
            self._show_tool_calls(function_calls_to_run, model_response)

        return function_calls_to_run

    def process_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data
    ) -> Iterator[ModelResponse]:
        """
        Process a streaming response from the model.
        """
        tool_call_data = ToolCall()

        for response_delta in self.invoke_stream(messages=messages):
            model_response_delta = self.parse_provider_response_delta(response_delta, tool_call_data)
            if model_response_delta:
                yield from self._populate_stream_data_and_assistant_message(
                    stream_data=stream_data, assistant_message=assistant_message, model_response=model_response_delta
                )

    async def aprocess_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data
    ) -> AsyncIterator[ModelResponse]:
        """
        Process a streaming response from the model.
        """
        tool_call_data = ToolCall()

        async for response_delta in self.ainvoke_stream(messages=messages):
            model_response_delta = self.parse_provider_response_delta(response_delta, tool_call_data)
            if model_response_delta:
                for model_response in self._populate_stream_data_and_assistant_message(
                    stream_data=stream_data, assistant_message=assistant_message, model_response=model_response_delta
                ):
                    yield model_response

    def parse_provider_response_delta(self, response_delta, tool_call_data: ToolCall) -> ModelResponse:
        """
        Parse the provider response delta.

        Args:
            response_delta: The response from the provider.

        Returns:
            Iterator[ModelResponse]: An iterator of the model response.
        """
        model_response = ModelResponse()

        response_message = response_delta.get("message")

        # logger.info(f"Response message: {response_delta}")

        if response_message is not None:
            content_delta = response_message.get("content", "")
            if content_delta is not None and content_delta != "":
                # Append content delta to tool call content
                tool_call_data.tool_call_content += content_delta

            # Log tool call data to help debug tool call processing

            # Detect if response is a tool call
            # If the response is a tool call, it will start a <tool token
            if not tool_call_data.response_is_tool_call and "<tool" in content_delta:
                tool_call_data.response_is_tool_call = True

            # If response is a tool call, count the number of tool calls
            if tool_call_data.response_is_tool_call:
                # If the response is an opening tool call tag, increment the tool call counter
                if "<tool" in content_delta:
                    tool_call_data.tool_calls_counter += 1

                # If the response is a closing tool call tag, decrement the tool call counter
                if tool_call_data.tool_call_content.strip().endswith("</tool_call>"):
                    tool_call_data.tool_calls_counter -= 1

                # If the response is a closing tool call tag and the tool call counter is 0,
                # tool call response is complete
                if tool_call_data.tool_calls_counter == 0 and content_delta.strip().endswith(">"):
                    tool_call_data.response_is_tool_call = False
                    tool_call_data.is_closing_tool_call_tag = True

                    try:
                        model_response.tool_calls = _parse_tool_calls_from_content(tool_call_data.tool_call_content)
                        tool_call_data = ToolCall()
                    except Exception as e:
                        logger.warning(e)
                        pass

            # Yield content if not a tool call and content is not None
            if not tool_call_data.response_is_tool_call and content_delta is not None:
                if tool_call_data.is_closing_tool_call_tag and content_delta.strip().endswith(">"):
                    tool_call_data.is_closing_tool_call_tag = False

                model_response.content = content_delta

        if response_delta.get("done"):
            model_response.response_usage = {
                "input_tokens": response_delta.get("prompt_eval_count", 0),
                "output_tokens": response_delta.get("eval_count", 0),
                "total_tokens": response_delta.get("prompt_eval_count", 0) + response_delta.get("eval_count", 0),
                "additional_metrics": {
                    "total_duration": response_delta.get("total_duration", 0),
                    "load_duration": response_delta.get("load_duration", 0),
                    "prompt_eval_duration": response_delta.get("prompt_eval_duration", 0),
                    "eval_duration": response_delta.get("eval_duration", 0),
                },
            }

        return model_response

    def get_instructions_to_generate_tool_calls(self) -> List[str]:
        if self._functions is not None:
            return [
                "At the very first turn you don't have <tool_results> so you shouldn't not make up the results.",
                "To respond to the users message, you can use only one tool at a time.",
                "When using a tool, only respond with the tool call. Nothing else. Do not add any additional notes, explanations or white space.",
                "Do not stop calling functions until the task has been accomplished or you've reached max iteration of 10.",
            ]
        return []

    def get_tool_call_prompt(self) -> Optional[str]:
        if self._functions is not None and len(self._functions) > 0:
            tool_call_prompt = dedent(
                """\
            You are a function calling with a language model.
            You are provided with function signatures within <tools></tools> XML tags.
            You may use agentic frameworks for reasoning and planning to help with user query.
            Please call a function and wait for function results to be provided to you in the next iteration.
            Don't make assumptions about what values to plug into functions.
            When you call a function, don't add any additional notes, explanations or white space.
            Once you have called a function, results will be provided to you within <tool_response></tool_response> XML tags.
            Do not make assumptions about tool results if <tool_response> XML tags are not present since the function is not yet executed.
            Analyze the results once you get them and call another function if needed.
            Your final response should directly answer the user query with an analysis or summary of the results of function calls.
            """
            )
            tool_call_prompt += "\nHere are the available tools:"
            tool_call_prompt += "\n<tools>\n"
            tool_definitions: List[str] = []
            for _f_name, _function in self._functions.items():
                _function_def = _function.get_definition_for_prompt()
                if _function_def:
                    tool_definitions.append(_function_def)
            tool_call_prompt += "\n".join(tool_definitions)
            tool_call_prompt += "\n</tools>\n\n"
            tool_call_prompt += dedent(
                """\
            Use the following pydantic model json schema for each tool call you will make: {'title': 'FunctionCall', 'type': 'object', 'properties': {'arguments': {'title': 'Arguments', 'type': 'object'}, 'name': {'title': 'Name', 'type': 'string'}}, 'required': ['arguments', 'name']}
            For each function call return a json object with function name and arguments within <tool_call></tool_call> XML tags as follows:
            <tool_call>
            {"arguments": <args-dict>, "name": <function-name>}
            </tool_call>\n
            """
            )
            return tool_call_prompt
        return None

    def get_system_message_for_model(self) -> Optional[str]:
        return self.get_tool_call_prompt()

    def get_instructions_for_model(self) -> Optional[List[str]]:
        return self.get_instructions_to_generate_tool_calls()


def _parse_tool_calls_from_content(response_content: str) -> List[Dict[str, Any]]:
    """
    Parse tool calls from response content.

    Args:
        response_content (str): The response content containing tool calls

    Returns:
        List[Dict[str, Any]]: List of parsed tool calls

    Raises:
        ValueError: If tool call content cannot be parsed
    """
    tool_calls = []

    if "<tool_call>" in response_content and "</tool_call>" in response_content:
        # Break the response into tool calls
        tool_call_responses = response_content.split("</tool_call>")
        for tool_call_response in tool_call_responses:
            # Add back the closing tag if this is not the last tool call
            if tool_call_response != tool_call_responses[-1]:
                tool_call_response += "</tool_call>"

            if "<tool_call>" in tool_call_response and "</tool_call>" in tool_call_response:
                # Extract tool call string from response
                tool_call_content = extract_tool_call_from_string(tool_call_response)
                # Convert the extracted string to a dictionary
                try:
                    tool_call_dict = json.loads(tool_call_content)
                except json.JSONDecodeError:
                    raise ValueError(f"Could not parse tool call from: {tool_call_content}")

                tool_call_name = tool_call_dict.get("name")
                tool_call_args = tool_call_dict.get("arguments")
                function_def = {"name": tool_call_name}
                if tool_call_args is not None:
                    function_def["arguments"] = json.dumps(tool_call_args)
                tool_calls.append(
                    {
                        "type": "function",
                        "function": function_def,
                    }
                )

    return tool_calls
