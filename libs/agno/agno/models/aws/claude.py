import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

from agno.models.aws.bedrock import AwsBedrock
from agno.models.base import MessageData
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger


@dataclass
class BedrockResponseUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Claude(AwsBedrock):
    """
    AWS Bedrock Claude model.

    Args:
        id (str): The model to use.
        max_tokens (int): The maximum number of tokens to generate.
        temperature (Optional[float]): The temperature to use.
        top_p (Optional[float]): The top p to use.
        top_k (Optional[int]): The top k to use.
        stop_sequences (Optional[List[str]]): The stop sequences to use.
        anthropic_version (str): The anthropic version to use.
        request_params (Optional[Dict[str, Any]]): The request parameters to use.
        client_params (Optional[Dict[str, Any]]): The client parameters to use.

    """

    id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    # -*- Request parameters
    max_tokens: int = 4096
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    anthropic_version: str = "bedrock-2023-05-31"

    # -*- Request parameters
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    client_params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = super().to_dict()
        _dict["max_tokens"] = self.max_tokens
        _dict["temperature"] = self.temperature
        _dict["top_p"] = self.top_p
        _dict["top_k"] = self.top_k
        _dict["stop_sequences"] = self.stop_sequences
        return _dict

    @property
    def api_kwargs(self) -> Dict[str, Any]:
        _request_params: Dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "anthropic_version": self.anthropic_version,
        }
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def _format_tools(self) -> Optional[Dict[str, Any]]:
        """
        Refactors the tools in a format accepted by the Bedrock API.
        """
        tools = []
        for f_name, function in self._functions.items():
            properties = {}
            required = []

            for param_name, param_info in function.parameters.get("properties", {}).items():
                param_type = param_info.get("type")
                if isinstance(param_type, list):
                    param_type = [t for t in param_type if t != "null"][0]

                properties[param_name] = {
                    "type": param_type or "string",
                    "description": param_info.get("description") or "",
                }

                if "null" not in (
                    param_info.get("type") if isinstance(param_info.get("type"), list) else [param_info.get("type")]
                ):
                    required.append(param_name)

            tools.append(
                {
                    "toolSpec": {
                        "name": f_name,
                        "description": function.description or "",
                        "inputSchema": {"json": {"type": "object", "properties": properties, "required": required}},
                    }
                }
            )

        return {"tools": tools}

    def format_messages(self, messages: List[Message]) -> Dict[str, Any]:
        """
        Create the request body for the Bedrock API.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Dict[str, Any]: The request body for the Bedrock API.
        """
        system_prompt = None
        messages_for_api = []
        for m in messages:
            if m.role == "system":
                system_prompt = m.content
            else:
                messages_for_api.append({"role": m.role, "content": [{"text": m.content}]})

        request_body = {
            "messages": messages_for_api,
            "modelId": self.id,
        }

        if system_prompt:
            request_body["system"] = [{"text": system_prompt}]

        # Add inferenceConfig
        inference_config: Dict[str, Any] = {}
        rename_map = {"max_tokens": "maxTokens", "top_p": "topP", "top_k": "topK", "stop_sequences": "stopSequences"}

        for k, v in self.api_kwargs.items():
            if k in rename_map:
                inference_config[rename_map[k]] = v
            elif k in ["temperature"]:
                inference_config[k] = v

        if inference_config:
            request_body["inferenceConfig"] = inference_config  # type: ignore

        if self._functions:
            tools = self._format_tools()
            request_body["toolConfig"] = tools  # type: ignore

        return request_body

    def parse_provider_response(self, response: Dict[str, Any]) -> ModelResponse:
        """
        Parse the response from the Bedrock API.

        Args:
            response (Dict[str, Any]): The response from the Bedrock API.

        Returns:
            ModelResponse: The parsed response.
        """
        model_response = ModelResponse()

        # Extract message from output
        if "output" in response and "message" in response["output"]:
            message = response["output"]["message"]

            # Add role
            if "role" in message:
                model_response.role = message["role"]

            # Extract and join text content from content list
            if "content" in message:
                content = message["content"]
                if isinstance(content, list) and content:
                    text_content = [item.get("text", "") for item in content if "text" in item]
                    model_response.content = "\n".join(text_content)

        # Add usage metrics
        if "usage" in response:
            # This ensures that the usage can be parsed upstream
            model_response.response_usage = BedrockResponseUsage(
                input_tokens=response.get("usage", {}).get("inputTokens", 0),
                output_tokens=response.get("usage", {}).get("outputTokens", 0),
                total_tokens=response.get("usage", {}).get("totalTokens", 0),
            )

        # If we have a stop reason, it works a bit differently
        stop_reason = None
        if "stopReason" in response:
            stop_reason = response["stopReason"]

        if stop_reason and stop_reason == "tool_use":
            tool_requests = response["output"]["message"]["content"]

            tool_ids = []
            tool_calls = []
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
            if tool_calls:
                model_response.tool_calls = tool_calls
            if tool_requests:
                model_response.content = tool_requests[0]["text"]
                model_response.extra["tool_ids"] = tool_ids

        return model_response

    # Override the base class method
    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], tool_ids: List[str]
    ) -> None:
        """
        Format function call results.
        """
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

    # Override the base class method
    def process_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> Iterator[ModelResponse]:
        """
        Process the streaming response from the Bedrock API.
        """

        tool_use: Dict[str, Any] = {}
        tool_ids: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        content: List[Dict[str, Any]] = []

        # Process the streaming response
        for chunk in self.invoke_stream(messages=messages):
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
                    # Update metrics
                    assistant_message.metrics.completion_tokens += 1
                    if not assistant_message.metrics.time_to_first_token:
                        assistant_message.metrics.set_time_to_first_token()

                    # Update provider response content
                    stream_data.response_content += delta["text"]
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
                        "id": tool_use["toolUseId"],
                        "type": "function",
                        "function": {
                            "name": tool_use["name"],
                            "arguments": json.dumps(tool_use["input"]),
                        },
                    }
                    tool_calls.append(tool_call)
                    # Reset tool use
                    tool_use = {}
                else:
                    # Finish collecting text content
                    content.append({"text": stream_data.response_content})

            elif "metadata" in chunk:
                metadata = chunk["metadata"]
                if "usage" in metadata:
                    response_usage = BedrockResponseUsage(
                        input_tokens=metadata["usage"]["inputTokens"],
                        output_tokens=metadata["usage"]["outputTokens"],
                        total_tokens=metadata["usage"]["totalTokens"],
                    )

                    # Update metrics
                    self.add_usage_metrics_to_assistant_message(
                        assistant_message=assistant_message, response_usage=response_usage
                    )

        if tool_ids:
            stream_data.extra["tool_ids"] = tool_ids

        if tool_calls:
            stream_data.response_tool_calls = tool_calls
