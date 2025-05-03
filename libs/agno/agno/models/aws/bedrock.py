import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Tuple

from agno.exceptions import AgnoError, ModelProviderError
from agno.models.base import MessageData, Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning

try:
    from boto3 import client as AwsClient
    from boto3.session import Session
    from botocore.exceptions import ClientError
except ImportError:
    log_error("`boto3` not installed. Please install it via `pip install boto3`.")
    raise


@dataclass
class AwsBedrock(Model):
    """
    AWS Bedrock model.

    To use this model, you need to either:
    1. Set the following environment variables:
       - AWS_ACCESS_KEY_ID
       - AWS_SECRET_ACCESS_KEY
       - AWS_REGION
    2. Or provide a boto3 Session object

    Not all Bedrock models support all features. See this documentation for more information: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-supported-models-features.html

    Args:
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key_id (Optional[str]): The AWS access key ID to use.
        aws_secret_access_key (Optional[str]): The AWS secret access key to use.
        session (Optional[Session]): A boto3 Session object to use for authentication.
    """

    id: str = "mistral.mistral-small-2402-v1:0"
    name: str = "AwsBedrock"
    provider: str = "AwsBedrock"

    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    session: Optional[Session] = None

    # Request parameters
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    request_params: Optional[Dict[str, Any]] = None

    client: Optional[AwsClient] = None

    def get_client(self) -> AwsClient:
        if self.client is not None:
            return self.client

        if self.session:
            self.client = self.session.client("bedrock-runtime")
            return self.client

        self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise AgnoError(
                message="AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or provide a boto3 session.",
                status_code=400,
            )

        self.client = AwsClient(
            service_name="bedrock-runtime",
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )
        return self.client

    def _format_tools_for_request(self) -> List[Dict[str, Any]]:
        tools = []
        if self._functions is not None:
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

        return tools

    def _get_inference_config(self) -> Dict[str, Any]:
        request_kwargs = {
            "maxTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "stopSequences": self.stop_sequences,
        }

        return {k: v for k, v in request_kwargs.items() if v is not None}

    def _format_messages(self, messages: List[Message]) -> Tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        formatted_messages: List[Dict[str, Any]] = []
        system_message = None
        for message in messages:
            if message.role == "system":
                system_message = [{"text": message.content}]
            else:
                formatted_message: Dict[str, Any] = {"role": message.role, "content": []}
                # Handle tool results
                if isinstance(message.content, list):
                    formatted_message["content"].extend(message.content)
                elif message.tool_calls:
                    formatted_message["content"].extend(
                        [
                            {
                                "toolUse": {
                                    "toolUseId": tool_call["id"],
                                    "name": tool_call["function"]["name"],
                                    "input": json.loads(tool_call["function"]["arguments"]),
                                }
                            }
                            for tool_call in message.tool_calls
                        ]
                    )
                else:
                    formatted_message["content"].append({"text": message.content})

                if message.images:
                    for image in message.images:
                        if not image.content or not image.format:
                            raise ValueError("Image content and format are required.")

                        if image.format not in ["png", "jpeg", "webp", "gif"]:
                            raise ValueError(f"Unsupported image format: {image.format}")

                        formatted_message["content"].append(
                            {
                                "image": {
                                    "format": image.format,
                                    "source": {
                                        "bytes": image.content,
                                    },
                                }
                            }
                        )
                if message.audio:
                    log_warning("Audio input is currently unsupported.")

                if message.videos:
                    for video in message.videos:
                        if not video.content or not video.format:
                            raise ValueError("Video content and format are required.")

                        if video.format not in [
                            "mp4",
                            "mov",
                            "mkv",
                            "webm",
                            "flv",
                            "mpeg",
                            "mpg",
                            "wmv",
                            "three_gp",
                        ]:
                            raise ValueError(f"Unsupported video format: {video.format}")

                        formatted_message["content"].append(
                            {
                                "video": {
                                    "format": video.format,
                                    "source": {
                                        "bytes": video.content,
                                    },
                                }
                            }
                        )
                if message.files is not None and len(message.files) > 0:
                    log_warning("File input is currently unsupported.")

                formatted_messages.append(formatted_message)
        # TODO: Add caching: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-call.html
        return formatted_messages, system_message

    def invoke(self, messages: List[Message]) -> Dict[str, Any]:
        """
        Invoke the Bedrock API.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Dict[str, Any]: The response from the Bedrock API.
        """
        try:
            formatted_messages, system_message = self._format_messages(messages)

            tool_config = None
            if self._functions is not None:
                tool_config = {"tools": self._format_tools_for_request()}

            body = {
                "system": system_message,
                "toolConfig": tool_config,
                "inferenceConfig": self._get_inference_config(),
            }
            body = {k: v for k, v in body.items() if v is not None}

            if self.request_params:
                body.update(**self.request_params)

            return self.get_client().converse(modelId=self.id, messages=formatted_messages, **body)
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[Dict[str, Any]]:
        """
        Invoke the Bedrock API with streaming.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Iterator[Dict[str, Any]]: The streamed response.
        """
        try:
            formatted_messages, system_message = self._format_messages(messages)

            tool_config = None
            if self._functions is not None:
                tool_config = {"tools": self._format_tools_for_request()}

            body = {
                "system": system_message,
                "toolConfig": tool_config,
                "inferenceConfig": self._get_inference_config(),
            }
            body = {k: v for k, v in body.items() if v is not None}

            if self.request_params:
                body.update(**self.request_params)

            return self.get_client().converse_stream(modelId=self.id, messages=formatted_messages, **body)["stream"]
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # Overwrite the default from the base model
    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], tool_ids: List[str]
    ) -> None:
        """
        Handle the results of function calls.

        Args:
            messages (List[Message]): The list of conversation messages.
            function_call_results (List[Message]): The results of the function calls.
            tool_ids (List[str]): The tool ids.
        """
        if function_call_results:
            tool_result_content: List = []

            for _fc_message_index, _fc_message in enumerate(function_call_results):
                tool_result = {
                    "toolUseId": tool_ids[_fc_message_index],
                    "content": [{"json": {"result": _fc_message.content}}],
                }
                tool_result_content.append({"toolResult": tool_result})

            messages.append(Message(role="user", content=tool_result_content))

    def parse_provider_response(self, response: Dict[str, Any]) -> ModelResponse:
        model_response = ModelResponse()

        if "output" in response and "message" in response["output"]:
            message = response["output"]["message"]
            # Set the role of the message
            model_response.role = message["role"]

            # Get the content of the message
            content = message["content"]

            # Tools
            if "stopReason" in response and response["stopReason"] == "tool_use":
                model_response.tool_calls = []
                model_response.extra = model_response.extra or {}
                model_response.extra["tool_ids"] = []
                for tool in content:
                    if "toolUse" in tool:
                        model_response.extra["tool_ids"].append(tool["toolUse"]["toolUseId"])
                        model_response.tool_calls.append(
                            {
                                "id": tool["toolUse"]["toolUseId"],
                                "type": "function",
                                "function": {
                                    "name": tool["toolUse"]["name"],
                                    "arguments": json.dumps(tool["toolUse"]["input"]),
                                },
                            }
                        )

            # Extract text content if it's a list of dictionaries
            if isinstance(content, list) and content and isinstance(content[0], dict):
                content = [item.get("text", "") for item in content if "text" in item]
                content = "\n".join(content)  # Join multiple text items if present

            model_response.content = content

        if "usage" in response:
            model_response.response_usage = {
                "input_tokens": response["usage"]["inputTokens"],
                "output_tokens": response["usage"]["outputTokens"],
                "total_tokens": response["usage"]["totalTokens"],
            }

        return model_response

    def process_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> Iterator[ModelResponse]:
        """Process the synchronous response stream."""
        tool_use: Dict[str, Any] = {}
        content = []
        tool_ids = []

        for response_delta in self.invoke_stream(messages=messages):
            model_response = ModelResponse(role="assistant")
            should_yield = False
            if "contentBlockStart" in response_delta:
                # Handle tool use requests
                tool = response_delta["contentBlockStart"]["start"].get("toolUse")
                if tool:
                    tool_use["toolUseId"] = tool["toolUseId"]
                    tool_use["name"] = tool["name"]

            elif "contentBlockDelta" in response_delta:
                delta = response_delta["contentBlockDelta"]["delta"]
                if "toolUse" in delta:
                    if "input" not in tool_use:
                        tool_use["input"] = ""
                    tool_use["input"] += delta["toolUse"]["input"]
                elif "text" in delta:
                    model_response.content = delta["text"]

            elif "contentBlockStop" in response_delta:
                if "input" in tool_use:
                    # Finish collecting tool use input
                    try:
                        tool_use["input"] = json.loads(tool_use["input"])
                    except json.JSONDecodeError as e:
                        log_error(f"Failed to parse tool input as JSON: {e}")
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
                    # Append the tool call to the list of "done" tool calls
                    model_response.tool_calls.append(tool_call)
                    # Reset the tool use
                    tool_use = {}
                else:
                    # Finish collecting text content
                    content.append({"text": stream_data.response_content})

            elif "messageStop" in response_delta or "metadata" in response_delta:
                body = response_delta.get("metadata") or response_delta.get("messageStop") or {}
                if "usage" in body:
                    usage = body["usage"]
                    model_response.response_usage = {
                        "input_tokens": usage.get("inputTokens", 0),
                        "output_tokens": usage.get("outputTokens", 0),
                        "total_tokens": usage.get("totalTokens", 0),
                    }

            # Update metrics
            if not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()

            if model_response.content:
                stream_data.response_content += model_response.content
                should_yield = True

            if model_response.tool_calls:
                if stream_data.response_tool_calls is None:
                    stream_data.response_tool_calls = []
                stream_data.response_tool_calls.extend(model_response.tool_calls)
                should_yield = True

            if model_response.response_usage is not None:
                self._add_usage_metrics_to_assistant_message(
                    assistant_message=assistant_message, response_usage=model_response.response_usage
                )

            if should_yield:
                yield model_response

        if tool_ids:
            if stream_data.extra is None:
                stream_data.extra = {}
            stream_data.extra["tool_ids"] = tool_ids

    def parse_provider_response_delta(self, response_delta: Dict[str, Any]) -> ModelResponse:  # type: ignore
        pass

    async def ainvoke(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def ainvoke_stream(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")
