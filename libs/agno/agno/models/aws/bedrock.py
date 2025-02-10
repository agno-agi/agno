import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from agno.aws.api_client import AwsApiClient  # type: ignore
from agno.models.base import Model, StreamData
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.utils.log import logger
from agno.utils.timer import Timer
from agno.utils.tools import (
    get_function_call_for_tool_call,
)

try:
    from boto3 import session  # noqa: F401
except ImportError:
    logger.error("`boto3` not installed")
    raise


@dataclass
class AwsBedrock(Model):
    """
    AWS Bedrock model.

    Args:
        aws_region (Optional[str]): The AWS region to use.
        aws_profile (Optional[str]): The AWS profile to use.
        aws_client (Optional[AwsApiClient]): The AWS client to use.
        _bedrock_client (Optional[Any]): The Bedrock client to use.
        _bedrock_runtime_client (Optional[Any]): The Bedrock runtime client to use.
    """

    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None
    aws_client: Optional[AwsApiClient] = None

    _bedrock_client: Optional[Any] = None
    _bedrock_runtime_client: Optional[Any] = None

    def get_aws_region(self) -> Optional[str]:
        # Priority 1: Use aws_region from model
        if self.aws_region is not None:
            return self.aws_region

        # Priority 2: Get aws_region from env
        from os import getenv

        from agno.constants import AWS_REGION_ENV_VAR

        aws_region_env = getenv(AWS_REGION_ENV_VAR)
        if aws_region_env is not None:
            self.aws_region = aws_region_env
        return self.aws_region

    def get_aws_profile(self) -> Optional[str]:
        # Priority 1: Use aws_region from resource
        if self.aws_profile is not None:
            return self.aws_profile

        # Priority 2: Get aws_profile from env
        from os import getenv

        from agno.constants import AWS_PROFILE_ENV_VAR

        aws_profile_env = getenv(AWS_PROFILE_ENV_VAR)
        if aws_profile_env is not None:
            self.aws_profile = aws_profile_env
        return self.aws_profile

    def get_aws_client(self) -> AwsApiClient:
        if self.aws_client is not None:
            return self.aws_client

        self.aws_client = AwsApiClient(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
        return self.aws_client

    @property
    def bedrock_runtime_client(self):
        if self._bedrock_runtime_client is not None:
            return self._bedrock_runtime_client

        boto3_session: session = self.get_aws_client().boto3_session
        self._bedrock_runtime_client = boto3_session.client(service_name="bedrock-runtime")
        return self._bedrock_runtime_client

    def invoke(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invoke the Bedrock API.

        Args:
            body (Dict[str, Any]): The request body.

        Returns:
            Dict[str, Any]: The response from the Bedrock API.
        """
        return self.bedrock_runtime_client.converse(**body)

    def invoke_stream(self, body: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Invoke the Bedrock API with streaming.

        Args:
            body (Dict[str, Any]): The request body.

        Returns:
            Iterator[Dict[str, Any]]: The streamed response.
        """
        response = self.bedrock_runtime_client.converse_stream(**body)
        stream = response.get("stream")
        if stream:
            for event in stream:
                yield event

    def create_assistant_message(self, request_body: Dict[str, Any]) -> Message:
        raise NotImplementedError("Please use a subclass of AwsBedrock")

    def get_request_body(self, messages: List[Message]) -> Dict[str, Any]:
        raise NotImplementedError("Please use a subclass of AwsBedrock")

    def parse_response_message(self, response: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Please use a subclass of AwsBedrock")

    def _create_tool_calls(
        self, stop_reason: str, parsed_response: Dict[str, Any]
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        tool_ids: List[str] = []
        tool_calls: List[Dict[str, Any]] = []

        if stop_reason == "tool_use":
            tool_requests = parsed_response.get("tool_requests")
            if tool_requests:
                for tool in tool_requests:
                    if "toolUse" in tool:
                        tool_use = tool["toolUse"]
                        tool_id = tool_use["toolUseId"]
                        tool_name = tool_use["name"]
                        tool_args = tool_use["input"]

                        tool_ids.append(tool_id)
                        tool_calls.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        )

        return tool_ids, tool_calls

    def _handle_tool_calls(
        self, assistant_message: Message, messages: List[Message], model_response: ModelResponse, tool_ids
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
        # -*- Parse and run function call
        if assistant_message.tool_calls is not None:
            if model_response.tool_calls is None:
                model_response.tool_calls = []

            # Remove the tool call from the response content
            model_response.content = ""
            tool_role: str = "tool"
            function_calls_to_run: List[Any] = []
            function_call_results: List[Message] = []
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

            if self.show_tool_calls:
                model_response.content += "\nRunning:"
                for _f in function_calls_to_run:
                    model_response.content += f"\n - {_f.get_call_str()}"
                model_response.content += "\n\n"

            for function_call_response in self.run_function_calls(
                function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
            ):
                if (
                    function_call_response.event == ModelResponseEvent.tool_call_completed.value
                    and function_call_response.tool_calls is not None
                ):
                    model_response.tool_calls.extend(function_call_response.tool_calls)

            if len(function_call_results) > 0:
                fc_responses: List = []

                for _fc_message_index, _fc_message in enumerate(function_call_results):
                    tool_result = {
                        "toolUseId": tool_ids[_fc_message_index],
                        "content": [{"json": json.dumps(_fc_message.content)}],
                    }
                    tool_result_message = {"role": "user", "content": json.dumps([{"toolResult": tool_result}])}
                    fc_responses.append(tool_result_message)

                logger.debug(f"Tool call responses: {fc_responses}")
                messages.append(Message(role="user", content=json.dumps(fc_responses)))

            return model_response
        return None

    def _update_metrics(self, assistant_message, parsed_response, response_timer):
        """
        Update usage metrics in assistant_message and self.metrics based on the parsed_response.

        Args:
            assistant_message: The assistant's message object where individual metrics are stored.
            parsed_response: The parsed response containing usage metrics.
            response_timer: Timer object that has the elapsed time of the response.
        """
        # Add response time to metrics
        assistant_message.metrics["time"] = response_timer.elapsed
        if "response_times" not in self.metrics:
            self.metrics["response_times"] = []
        self.metrics["response_times"].append(response_timer.elapsed)

        # Add token usage to metrics
        usage = parsed_response.get("usage", {})
        prompt_tokens = usage.get("inputTokens")
        completion_tokens = usage.get("outputTokens")
        total_tokens = usage.get("totalTokens")

        if prompt_tokens is not None:
            assistant_message.metrics["prompt_tokens"] = prompt_tokens
            self.metrics["prompt_tokens"] = self.metrics.get("prompt_tokens", 0) + prompt_tokens

        if completion_tokens is not None:
            assistant_message.metrics["completion_tokens"] = completion_tokens
            self.metrics["completion_tokens"] = self.metrics.get("completion_tokens", 0) + completion_tokens

        if total_tokens is not None:
            assistant_message.metrics["total_tokens"] = total_tokens
            self.metrics["total_tokens"] = self.metrics.get("total_tokens", 0) + total_tokens

    def response(self, messages: List[Message]) -> ModelResponse:
        """
        Generate a response from the Bedrock API.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            ModelResponse: The response from the Bedrock API.
        """
        logger.debug("---------- Bedrock Response Start ----------")
        self._log_messages(messages)
        model_response = ModelResponse()

        # Invoke the Bedrock API
        response_timer = Timer()
        response_timer.start()
        body = self.get_request_body(messages)
        response: Dict[str, Any] = self.invoke(body=body)
        response_timer.stop()

        # Parse response
        parsed_response = self.parse_response_message(response)
        logger.debug(f"Parsed response: {parsed_response}")
        stop_reason = parsed_response["stop_reason"]

        # Create assistant message
        assistant_message = self.create_assistant_message(parsed_response)

        # Update usage metrics using the new function
        self._update_metrics(assistant_message, parsed_response, response_timer)

        # Add assistant message to messages
        messages.append(assistant_message)
        assistant_message.log()

        # Create tool calls if needed
        tool_ids, tool_calls = self._create_tool_calls(stop_reason, parsed_response)

        # Handle tool calls
        if stop_reason == "tool_use" and tool_calls:
            assistant_message.content = parsed_response["tool_requests"][0]["text"]
            assistant_message.tool_calls = tool_calls

        # Run tool calls
        if self._handle_tool_calls(assistant_message, messages, model_response, tool_ids):
            response_after_tool_calls = self.response(messages=messages)
            if response_after_tool_calls.content is not None:
                if model_response.content is None:
                    model_response.content = ""
                model_response.content += response_after_tool_calls.content
            return model_response

        # Add assistant message content to model response
        if assistant_message.content is not None:
            model_response.content = assistant_message.get_content_string()

        logger.debug("---------- AWS Response End ----------")
        return model_response

    def _handle_stream_tool_calls(self, assistant_message: Message, messages: List[Message], tool_ids: List[str]):
        """
        Handle tool calls in the assistant message.

        Args:
            assistant_message (Message): The assistant message.
            messages (List[Message]): The list of messages.
            tool_ids (List[str]): The list of tool IDs.
        """
        tool_role: str = "tool"
        function_calls_to_run: List[Any] = []
        function_call_results: List[Message] = []
        for tool_call in assistant_message.tool_calls or []:
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

        if self.show_tool_calls:
            yield ModelResponse(content="\nRunning:")
            for _f in function_calls_to_run:
                yield ModelResponse(content=f"\n - {_f.get_call_str()}")
            yield ModelResponse(content="\n\n")

        for _ in self.run_function_calls(
            function_calls=function_calls_to_run, function_call_results=function_call_results, tool_role=tool_role
        ):
            pass

        if len(function_call_results) > 0:
            fc_responses: List = []

            for _fc_message_index, _fc_message in enumerate(function_call_results):
                tool_result = {
                    "toolUseId": tool_ids[_fc_message_index],
                    "content": [{"json": json.dumps(_fc_message.content)}],
                }
                tool_result_message = {"role": "user", "content": json.dumps([{"toolResult": tool_result}])}
                fc_responses.append(tool_result_message)

            logger.debug(f"Tool call responses: {fc_responses}")
            messages.append(Message(role="user", content=json.dumps(fc_responses)))

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

    def response_stream(self, messages: List[Message]) -> Iterator[ModelResponse]:
        """
        Stream the response from the Bedrock API.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Iterator[str]: The streamed response.
        """
        logger.debug("---------- Bedrock Response Start ----------")
        self._log_messages(messages)

        stream_data: StreamData = StreamData()
        stream_data.response_timer.start()

        tool_use: Dict[str, Any] = {}
        tool_ids: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        stop_reason: Optional[str] = None
        content: List[Dict[str, Any]] = []

        request_body = self.get_request_body(messages)
        response = self.invoke_stream(body=request_body)

        # Process the streaming response
        for chunk in response:
            if "contentBlockStart" in chunk:
                tool = chunk["contentBlockStart"]["start"].get("toolUse")
                if tool:
                    tool_use["toolUseId"] = tool["toolUseId"]
                    tool_use["name"] = tool["name"]

            elif "contentBlockDelta" in chunk:
                delta = chunk["contentBlockDelta"]["delta"]
                if "toolUse" in delta:
                    if "input" not in tool_use:
                        tool_use["input"] = ""
                    tool_use["input"] += delta["toolUse"]["input"]
                elif "text" in delta:
                    stream_data.response_content += delta["text"]
                    stream_data.completion_tokens += 1
                    if stream_data.completion_tokens == 1:
                        stream_data.time_to_first_token = stream_data.response_timer.elapsed
                        logger.debug(f"Time to first token: {stream_data.time_to_first_token:.4f}s")
                    yield ModelResponse(content=delta["text"])  # Yield text content as it's received

            elif "contentBlockStop" in chunk:
                if "input" in tool_use:
                    # Finish collecting tool use input
                    try:
                        tool_use["input"] = json.loads(tool_use["input"])
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse tool input as JSON: {e}")
                        tool_use["input"] = {}
                    content.append({"toolUse": tool_use})
                    tool_ids.append(tool_use["toolUseId"])
                    # Prepare the tool call
                    tool_call = {
                        "type": "function",
                        "function": {
                            "name": tool_use["name"],
                            "arguments": json.dumps(tool_use["input"]),
                        },
                    }
                    tool_calls.append(tool_call)
                    tool_use = {}
                else:
                    # Finish collecting text content
                    content.append({"text": stream_data.response_content})

            elif "messageStop" in chunk:
                stop_reason = chunk["messageStop"]["stopReason"]
                logger.debug(f"Stop reason: {stop_reason}")

            elif "metadata" in chunk:
                metadata = chunk["metadata"]
                if "usage" in metadata:
                    stream_data.response_prompt_tokens = metadata["usage"]["inputTokens"]
                    stream_data.response_total_tokens = metadata["usage"]["totalTokens"]
                    stream_data.completion_tokens = metadata["usage"]["outputTokens"]

        stream_data.response_timer.stop()

        # Create assistant message
        if stream_data.response_content != "":
            assistant_message = Message(role="assistant", content=stream_data.response_content, tool_calls=tool_calls)

        if stream_data.completion_tokens > 0:
            logger.debug(
                f"Time per output token: {stream_data.response_timer.elapsed / stream_data.completion_tokens:.4f}s"
            )
            logger.debug(
                f"Throughput: {stream_data.completion_tokens / stream_data.response_timer.elapsed:.4f} tokens/s"
            )

        # Update metrics
        self._update_stream_metrics(stream_data, assistant_message)

        # Add assistant message to messages
        messages.append(assistant_message)
        assistant_message.log()

        # Handle tool calls if any
        if tool_calls:
            yield from self._handle_stream_tool_calls(assistant_message, messages, tool_ids)
            yield from self.response_stream(messages=messages)

        logger.debug("---------- Bedrock Response End ----------")

    async def ainvoke(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def ainvoke_stream(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def aresponse(self, messages: List[Message]) -> ModelResponse:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def aresponse_stream(self, messages: List[Message]) -> ModelResponse:
        raise NotImplementedError(f"Async not supported on {self.name}.")
