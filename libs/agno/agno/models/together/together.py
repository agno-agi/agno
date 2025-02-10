import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional

from agno.models.message import Message
from agno.models.openai.chat import Metrics, StreamData
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.tools.function import FunctionCall
from agno.utils.log import logger
from agno.utils.tools import get_function_call_for_tool_call

try:
    from openai.types.chat.chat_completion_chunk import (
        ChoiceDelta,
        ChoiceDeltaToolCall,
    )
    from openai.types.completion_usage import CompletionUsage
except ImportError:
    logger.error("`openai` not installed")
    raise


@dataclass
class Together(OpenAILike):
    """
    A class for interacting with Together models.

    Attributes:
        id (str): The id of the Together model to use. Default is "mistralai/Mixtral-8x7B-Instruct-v0.1".
        name (str): The name of this chat model instance. Default is "Together"
        provider (str): The provider of the model. Default is "Together".
        api_key (str): The api key to authorize request to Together.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "mistralai/Mixtral-8x7B-Instruct-v0.1"
    name: str = "Together"
    provider: str = "Together " + id
    api_key: Optional[str] = getenv("TOGETHER_API_KEY")
    base_url: str = "https://api.together.xyz/v1"
    monkey_patch: bool = False

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        if not self.monkey_patch:
            yield from super().response_stream(messages)
            return

        logger.debug("---------- Together Response Start ----------")
        # -*- Log messages for debugging
        self._log_messages(messages)

        stream_data: StreamData = StreamData()
        metrics: Metrics = Metrics()
        assistant_message_content = ""
        response_is_tool_call = False

        # -*- Generate response
        metrics.start_response_timer()
        for response in self.invoke_stream(messages=messages):
            if len(response.choices) > 0:
                metrics.completion_tokens += 1
                if metrics.completion_tokens == 1:
                    metrics.time_to_first_token = metrics.response_timer.elapsed

                response_delta: ChoiceDelta = response.choices[0].delta
                response_content: Optional[str] = response_delta.content
                response_tool_calls: Optional[List[ChoiceDeltaToolCall]] = response_delta.tool_calls

                if response_content is not None:
                    stream_data.response_content += response_content
                    yield ModelResponse(content=response_content)

                if response_tool_calls is not None:
                    if stream_data.response_tool_calls is None:
                        stream_data.response_tool_calls = []
                    stream_data.response_tool_calls.extend(response_tool_calls)

            if response.usage:
                response_usage: Optional[CompletionUsage] = response.usage
                if response_usage:
                    metrics.input_tokens = response_usage.prompt_tokens
                    metrics.prompt_tokens = response_usage.prompt_tokens
                    metrics.output_tokens = response_usage.completion_tokens
                    metrics.completion_tokens = response_usage.completion_tokens
                    metrics.total_tokens = response_usage.total_tokens
        metrics.stop_response_timer()
        logger.debug(f"Time to generate response: {metrics.response_timer.elapsed:.4f}s")

        # -*- Create assistant message
        assistant_message = Message(
            role="assistant",
            content=assistant_message_content,
        )
        # -*- Check if the response is a tool call
        try:
            if response_is_tool_call and assistant_message_content != "":
                _tool_call_content = assistant_message_content.strip()
                _tool_call_list = json.loads(_tool_call_content)
                if isinstance(_tool_call_list, list):
                    # Build tool calls
                    _tool_calls: List[Dict[str, Any]] = []
                    logger.debug(f"Building tool calls from {_tool_call_list}")
                    for _tool_call in _tool_call_list:
                        tool_call_name = _tool_call.get("name")
                        tool_call_args = _tool_call.get("arguments")
                        _function_def = {"name": tool_call_name}
                        if tool_call_args is not None:
                            _function_def["arguments"] = json.dumps(tool_call_args)
                        _tool_calls.append(
                            {
                                "type": "function",
                                "function": _function_def,
                            }
                        )
                    assistant_message.tool_calls = _tool_calls
        except Exception:
            logger.warning(f"Could not parse tool calls from response: {assistant_message_content}")
            pass

        # -*- Update usage metrics
        # Add response time to metrics
        assistant_message.metrics["time"] = metrics.response_timer.elapsed
        if "response_times" not in self.metrics:
            self.metrics["response_times"] = []
        self.metrics["response_times"].append(metrics.response_timer.elapsed)

        # Add token usage to metrics
        logger.debug(f"Estimated completion tokens: {metrics.completion_tokens}")
        assistant_message.metrics["completion_tokens"] = metrics.completion_tokens
        if "completion_tokens" not in self.metrics:
            self.metrics["completion_tokens"] = metrics.completion_tokens
        else:
            self.metrics["completion_tokens"] += metrics.completion_tokens

        # -*- Add assistant message to messages
        messages.append(assistant_message)
        assistant_message.log()
        metrics.log()

        # -*- Parse and run tool calls
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
            # -*- Yield new response using results of tool calls
            yield from self.response_stream(messages=messages)
        logger.debug("---------- Together Response End ----------")
