import json
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Dict, Iterator, List, Mapping, Optional

from agno.models.message import Message
from agno.models.ollama.chat import Metrics, Ollama
from agno.models.response import ModelResponse
from agno.utils.log import logger
from agno.utils.tools import (
    extract_tool_call_from_string,
    remove_tool_calls_from_string,
)


@dataclass
class MessageData:
    response_role: Optional[str] = None
    response_message: Optional[Dict[str, Any]] = None
    response_content: Any = ""
    response_content_chunk: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_usage: Optional[Mapping[str, Any]] = None
    response_is_tool_call = False
    is_closing_tool_call_tag = False
    tool_calls_counter = 0


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
        request_params: Dict[str, Any] = {}
        if self.format is not None:
            request_params["format"] = self.format
        if self.options is not None:
            request_params["options"] = self.options
        if self.keep_alive is not None:
            request_params["keep_alive"] = self.keep_alive
        if self.request_params is not None:
            request_params.update(self.request_params)
        return request_params

    def create_assistant_message(self, response: Mapping[str, Any], metrics: Metrics) -> Message:
        """
        Create an assistant message from the response.

        Args:
            response: The response from Ollama.
            metrics: The metrics for this response.

        Returns:
            Message: The assistant message.
        """
        message_data = MessageData()

        message_data.response_message = response.get("message")
        if message_data.response_message:
            message_data.response_content = message_data.response_message.get("content")
            message_data.response_role = message_data.response_message.get("role")

        assistant_message = Message(
            role=message_data.response_role or "assistant",
            content=message_data.response_content,
        )
        # -*- Check if the response contains a tool call
        try:
            if message_data.response_content is not None:
                if "<tool_call>" in message_data.response_content and "</tool_call>" in message_data.response_content:
                    # Break the response into tool calls
                    tool_call_responses = message_data.response_content.split("</tool_call>")
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
                            message_data.tool_calls.append(
                                {
                                    "type": "function",
                                    "function": function_def,
                                }
                            )
        except Exception as e:
            logger.warning(e)
            pass

        if message_data.tool_calls is not None:
            assistant_message.tool_calls = message_data.tool_calls

        # -*- Update metrics
        self.update_usage_metrics(assistant_message=assistant_message, metrics=metrics, response=response)
        return assistant_message

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

    def handle_tool_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
    ) -> Optional[ModelResponse]:
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            model_response (ModelResponse): The model response.

        Returns:
            Optional[ModelResponse]: The model response.
        """
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            model_response.content = str(remove_tool_calls_from_string(assistant_message.get_content_string()))
            model_response.content += "\n\n"
            function_calls_to_run = self._get_function_calls_to_run(assistant_message, messages)
            function_call_results: List[Message] = []

            if self.show_tool_calls:
                if len(function_calls_to_run) == 1:
                    model_response.content += f" - Running: {function_calls_to_run[0].get_call_str()}\n\n"
                elif len(function_calls_to_run) > 1:
                    model_response.content += "Running:"
                    for _f in function_calls_to_run:
                        model_response.content += f"\n - {_f.get_call_str()}"
                    model_response.content += "\n\n"

            for _ in self.run_function_calls(
                function_calls=function_calls_to_run,
                function_call_results=function_call_results,
            ):
                pass

            self.format_function_call_results(function_call_results, messages)

            return model_response
        return None

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from OllamaTools.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of the model responses.
        """
        logger.debug("---------- Ollama Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        for response in self.invoke_stream(messages=messages):
            #  Parse response
            message_data.response_message = response.get("message", {})
            if message_data.response_message:
                metrics.output_tokens += 1
                if metrics.output_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

            if message_data.response_message:
                message_data.response_content_chunk = message_data.response_message.get("content", "")

            # Add response content to assistant message
            if message_data.response_content_chunk is not None:
                message_data.response_content += message_data.response_content_chunk

            # Detect if response is a tool call
            # If the response is a tool call, it will start a <tool token
            if not message_data.response_is_tool_call and "<tool" in message_data.response_content_chunk:
                message_data.response_is_tool_call = True
                # logger.debug(f"Response is tool call: {message_data.response_is_tool_call}")

            # If response is a tool call, count the number of tool calls
            if message_data.response_is_tool_call:
                # If the response is an opening tool call tag, increment the tool call counter
                if "<tool" in message_data.response_content_chunk:
                    message_data.tool_calls_counter += 1

                # If the response is a closing tool call tag, decrement the tool call counter
                if message_data.response_content.strip().endswith("</tool_call>"):
                    message_data.tool_calls_counter -= 1

                # If the response is a closing tool call tag and the tool call counter is 0,
                # tool call response is complete
                if message_data.tool_calls_counter == 0 and message_data.response_content_chunk.strip().endswith(">"):
                    message_data.response_is_tool_call = False
                    # logger.debug(f"Response is tool call: {message_data.response_is_tool_call}")
                    message_data.is_closing_tool_call_tag = True

            # Yield content if not a tool call and content is not None
            if not message_data.response_is_tool_call and message_data.response_content_chunk is not None:
                if message_data.is_closing_tool_call_tag and message_data.response_content_chunk.strip().endswith(">"):
                    message_data.is_closing_tool_call_tag = False
                    continue

                yield ModelResponse(content=message_data.response_content_chunk)

            if response.get("done"):
                message_data.response_usage = response
        metrics.stop_response_timer()

        # -*- Create assistant message
        assistant_message = Message(role="assistant", content=message_data.response_content)

        # -*- Parse tool calls from the assistant message content
        try:
            if "<tool_call>" in message_data.response_content and "</tool_call>" in message_data.response_content:
                # Break the response into tool calls
                tool_call_responses = message_data.response_content.split("</tool_call>")
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
                        message_data.tool_calls.append(
                            {
                                "type": "function",
                                "function": function_def,
                            }
                        )

        except Exception as e:
            yield ModelResponse(content=f"Error parsing tool call: {e}")
            logger.warning(e)
            pass

        if len(message_data.tool_calls) > 0:
            assistant_message.tool_calls = message_data.tool_calls

        # -*- Update usage metrics
        self.update_usage_metrics(
            assistant_message=assistant_message, metrics=metrics, response=message_data.response_usage
        )

        # -*- Add assistant message to messages
        messages.append(assistant_message)

        # -*- Log response and metrics
        assistant_message.log()
        metrics.log()

        # -*- Handle tool calls
        if assistant_message.tool_calls is not None and len(assistant_message.tool_calls) > 0:
            yield from self.handle_stream_tool_calls(assistant_message, messages)
            yield from self.handle_post_tool_call_messages_stream(messages=messages)
        logger.debug("---------- Ollama Response End ----------")

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
            You are a function calling AI model with self-recursion.
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
