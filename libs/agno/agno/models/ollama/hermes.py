import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from agno.models.message import Message
from agno.models.ollama.chat import Metrics, Ollama
from agno.models.response import ModelResponse
from agno.utils.log import logger


@dataclass
class MessageData:
    response_role: Optional[str] = None
    response_message: Optional[Dict[str, Any]] = None
    response_content: Any = ""
    response_content_chunk: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_call_blocks: Any = field(default_factory=list)
    tool_call_chunk: str = ""
    in_tool_call: bool = False
    end_tool_call: bool = False
    response_usage: Optional[Mapping[str, Any]] = None


@dataclass
class OllamaHermes(Ollama):
    """
    A class for interacting with the OllamaHermes model via Ollama. This is a subclass of the Ollama model,
    which customizes tool call streaming for the hermes3 model.
    """

    id: str = "hermes3"
    name: str = "OllamaHermes"
    provider: str = "Ollama"

    def handle_tool_call_chunk(self, content, tool_call_buffer, message_data) -> Tuple[str, bool]:
        """
        Handle a tool call chunk for response stream.

        Args:
            content: The content of the tool call.
            tool_call_buffer: The tool call buffer.
            message_data: The message data.

        Returns:
            Tuple[str, bool]: The tool call buffer and a boolean indicating if the tool call is complete.
        """
        if content != "</tool_call>":
            tool_call_buffer += content

        if message_data.end_tool_call:
            try:
                tool_call_data = json.loads(tool_call_buffer)
                message_data.tool_call_blocks.append(tool_call_data)
                message_data.end_tool_call = False
            except json.JSONDecodeError:
                logger.error("Failed to parse tool call JSON.")
            return "", False

        return tool_call_buffer, True

    def _format_tool_calls(self, message_data: MessageData) -> MessageData:
        if message_data.tool_call_blocks is not None:
            for block in message_data.tool_call_blocks:
                tool_name = block.get("name")
                tool_args = block.get("arguments")

                function_def = {
                    "name": tool_name,
                    "arguments": json.dumps(tool_args) if tool_args is not None else None,
                }
                message_data.tool_calls.append({"type": "function", "function": function_def})
        return message_data

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Generate a streaming response from Ollama.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Iterator[ModelResponse]: An iterator of the model responses.
        """
        logger.debug("---------- Ollama OllamaHermes Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        for response in self.invoke_stream(messages=messages):
            message_data.response_message = response.get("message", {})
            if message_data.response_message:
                metrics.output_tokens += 1
                if metrics.output_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

                message_data.response_content_chunk = message_data.response_message.get("content", "").strip("`")

            if message_data.response_content_chunk:
                if message_data.response_content_chunk.strip().startswith("</tool_call>"):
                    message_data.end_tool_call = True
                if message_data.in_tool_call:
                    message_data.tool_call_chunk, message_data.in_tool_call = self.handle_tool_call_chunk(
                        message_data.response_content_chunk, message_data.tool_call_chunk, message_data
                    )
                elif message_data.response_content_chunk.strip().startswith("<tool_call>"):
                    message_data.in_tool_call = True
                else:
                    yield ModelResponse(content=message_data.response_content_chunk)
                    message_data.response_content += message_data.response_content_chunk

            if response.get("done"):
                message_data.response_usage = response
        metrics.stop_response_timer()

        # Format tool calls
        message_data = self._format_tool_calls(message_data)

        # -*- Create assistant message
        assistant_message = Message(role="assistant", content=message_data.response_content)

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
        logger.debug("---------- Ollama OllamaHermes Response End ----------")

    async def aresponse_stream(self, messages: List[Message]) -> Any:
        """
        Generate an asynchronous streaming response from Ollama.

        Args:
            messages (List[Message]): A list of messages.

        Returns:
            Any: An asynchronous iterator of the model responses.
        """
        logger.debug("---------- Ollama OllamaHermes Async Response Start ----------")
        self._log_messages(messages)
        message_data = MessageData()
        metrics: Metrics = Metrics()

        # -*- Generate response
        metrics.start_response_timer()
        async for response in self.ainvoke_stream(messages=messages):
            message_data.response_message = response.get("message", {})
            if message_data.response_message:
                metrics.output_tokens += 1
                if metrics.output_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

                message_data.response_content_chunk = message_data.response_message.get("content", "").strip("`")
                message_data.response_content_chunk = message_data.response_message.get("content", "").strip(
                    "<|end_of_text|>"
                )
                message_data.response_content_chunk = message_data.response_message.get("content", "").strip(
                    "<|begin_of_text|>"
                )

            if message_data.response_content_chunk:
                if message_data.response_content_chunk.strip().startswith("</tool_call>"):
                    message_data.end_tool_call = True
                if message_data.in_tool_call:
                    message_data.tool_call_chunk, message_data.in_tool_call = self.handle_tool_call_chunk(
                        message_data.response_content_chunk, message_data.tool_call_chunk, message_data
                    )
                elif message_data.response_content_chunk.strip().startswith("<tool_call>"):
                    message_data.in_tool_call = True
                else:
                    yield ModelResponse(content=message_data.response_content_chunk)
                    message_data.response_content += message_data.response_content_chunk

            if response.get("done"):
                message_data.response_usage = response
        metrics.stop_response_timer()

        # Format tool calls
        message_data = self._format_tool_calls(message_data)

        # -*- Create assistant message
        assistant_message = Message(role="assistant", content=message_data.response_content)

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
            for tool_call_response in self.handle_stream_tool_calls(assistant_message, messages):
                yield tool_call_response
            async for post_tool_call_response in self.ahandle_post_tool_call_messages_stream(messages=messages):
                yield post_tool_call_response
        logger.debug("---------- Ollama OllamaHermes Async Response End ----------")
