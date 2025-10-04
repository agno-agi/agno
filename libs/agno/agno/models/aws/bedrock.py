import json
from dataclasses import dataclass
from decimal import Decimal
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Type, Union

from pydantic import BaseModel

from agno.exceptions import AgnoError, ModelProviderError
from agno.models.base import MessageData, Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.log import log_debug, log_error, log_warning

try:
    from boto3 import client as AwsClient
    from boto3.session import Session
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`")

try:
    import aioboto3

    AIOBOTO3_AVAILABLE = True
except ImportError:
    aioboto3 = None
    AIOBOTO3_AVAILABLE = False


BEDROCK_SUPPORTED_IMAGE_FORMATS = ["png", "jpeg", "webp", "gif"]
BEDROCK_SUPPORTED_VIDEO_FORMATS = ["mp4", "mov", "mkv", "webm", "flv", "mpeg", "mpg", "wmv", "three_gp"]
BEDROCK_SUPPORTED_FILE_FORMATS = ["pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"]


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

    For async support, you also need aioboto3 installed:
       pip install aioboto3

    Not all Bedrock models support all features. See this documentation for more information: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-supported-models-features.html

    Args:
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key_id (Optional[str]): The AWS access key ID to use.
        aws_secret_access_key (Optional[str]): The AWS secret access key to use.
        aws_sso_auth (Optional[str]): Removes the need for an access and secret access key by leveraging the current profile's authentication
        session (Optional[Session]): A boto3 Session object to use for authentication.
    """

    id: str = "mistral.mistral-small-2402-v1:0"
    name: str = "AwsBedrock"
    provider: str = "AwsBedrock"

    aws_sso_auth: Optional[bool] = False
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
    async_client: Optional[Any] = None
    async_session: Optional[Any] = None

    def get_client(self) -> AwsClient:
        """
        Get the Bedrock client.

        Returns:
            AwsClient: The Bedrock client.
        """
        if self.client is not None:
            return self.client

        if self.session:
            self.client = self.session.client("bedrock-runtime")
            return self.client

        self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        if self.aws_sso_auth:
            self.client = AwsClient(service_name="bedrock-runtime", region_name=self.aws_region)
        else:
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

    def get_async_client(self):
        """
        Get the async Bedrock client context manager.

        Returns:
            The async Bedrock client context manager.
        """
        if not AIOBOTO3_AVAILABLE:
            raise ImportError(
                "`aioboto3` not installed. Please install using `pip install aioboto3` for async support."
            )

        if self.async_session is None:
            self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
            self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
            self.aws_region = self.aws_region or getenv("AWS_REGION")

            self.async_session = aioboto3.Session()

        client_kwargs = {
            "service_name": "bedrock-runtime",
            "region_name": self.aws_region,
        }

        if self.aws_sso_auth:
            pass
        else:
            if not self.aws_access_key_id or not self.aws_secret_access_key:
                import os

                env_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
                env_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
                env_region = os.environ.get("AWS_REGION")

                if env_access_key and env_secret_key:
                    self.aws_access_key_id = env_access_key
                    self.aws_secret_access_key = env_secret_key
                    if env_region:
                        self.aws_region = env_region
                        client_kwargs["region_name"] = self.aws_region

            if self.aws_access_key_id and self.aws_secret_access_key:
                client_kwargs.update(
                    {
                        "aws_access_key_id": self.aws_access_key_id,
                        "aws_secret_access_key": self.aws_secret_access_key,
                    }
                )

        return self.async_session.client(**client_kwargs)

    def _format_tools_for_request(self, tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Format the tools for the request.

        Returns:
            List[Dict[str, Any]]: The formatted tools.
        """
        parsed_tools = []
        if tools is not None:
            for tool_def in tools:
                func_def = tool_def.get("function", {})
                properties = {}
                required = []

                for param_name, param_info in func_def.get("parameters", {}).get("properties", {}).items():
                    properties[param_name] = param_info.copy()

                    if "description" not in properties[param_name]:
                        properties[param_name]["description"] = ""

                    if "null" not in (
                        param_info.get("type") if isinstance(param_info.get("type"), list) else [param_info.get("type")]
                    ):
                        required.append(param_name)

                parsed_tools.append(
                    {
                        "toolSpec": {
                            "name": func_def.get("name") or "",
                            "description": func_def.get("description") or "",
                            "inputSchema": {"json": {"type": "object", "properties": properties, "required": required}},
                        }
                    }
                )

        return parsed_tools

    def _get_inference_config(self) -> Dict[str, Any]:
        """
        Get the inference config.

        Returns:
            Dict[str, Any]: The inference config.
        """
        request_kwargs = {
            "maxTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "stopSequences": self.stop_sequences,
        }

        return {k: v for k, v in request_kwargs.items() if v is not None}

    def _format_messages(self, messages: List[Message]) -> Tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        """
        Format the messages for the request.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]: The formatted messages.
        """
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
                    tool_use_content = []
                    for tool_call in message.tool_calls:
                        try:
                            # Parse arguments with error handling for empty or invalid JSON
                            arguments = tool_call["function"]["arguments"]
                            if not arguments or arguments.strip() == "":
                                tool_input = {}
                            else:
                                tool_input = json.loads(arguments)
                        except (json.JSONDecodeError, KeyError) as e:
                            log_warning(f"Failed to parse tool call arguments: {e}")
                            tool_input = {}

                        tool_use_content.append(
                            {
                                "toolUse": {
                                    "toolUseId": tool_call["id"],
                                    "name": tool_call["function"]["name"],
                                    "input": tool_input,
                                }
                            }
                        )
                    formatted_message["content"].extend(tool_use_content)
                else:
                    formatted_message["content"].append({"text": message.content})

                if message.images:
                    for image in message.images:
                        if not image.content:
                            raise ValueError("Image content is required for AWS Bedrock.")
                        if not image.format:
                            raise ValueError("Image format is required for AWS Bedrock.")

                        if image.format not in BEDROCK_SUPPORTED_IMAGE_FORMATS:
                            raise ValueError(
                                f"Unsupported image format: {image.format}. "
                                f"Supported formats: {BEDROCK_SUPPORTED_IMAGE_FORMATS}"
                            )

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
                        if not video.content:
                            raise ValueError("Video content is required for AWS Bedrock.")
                        if not video.format:
                            raise ValueError("Video format is required for AWS Bedrock.")

                        if video.format not in BEDROCK_SUPPORTED_VIDEO_FORMATS:
                            raise ValueError(
                                f"Unsupported video format: {video.format}. "
                                f"Supported formats: {BEDROCK_SUPPORTED_VIDEO_FORMATS}"
                            )

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

                if message.files:
                    for file in message.files:
                        if not file.content:
                            raise ValueError("File content is required for AWS Bedrock document input.")
                        if not file.format:
                            raise ValueError("File format is required for AWS Bedrock document input.")
                        if not file.name:
                            raise ValueError("File name is required for AWS Bedrock document input.")

                        if file.format not in BEDROCK_SUPPORTED_FILE_FORMATS:
                            raise ValueError(
                                f"Unsupported file format: {file.format}. "
                                f"Supported formats: {BEDROCK_SUPPORTED_FILE_FORMATS}"
                            )

                        formatted_message["content"].append(
                            {
                                "document": {
                                    "format": file.format,
                                    "name": file.name,
                                    "source": {
                                        "bytes": file.content,
                                    },
                                }
                            }
                        )

                formatted_messages.append(formatted_message)
        # TODO: Add caching: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-call.html
        return formatted_messages, system_message

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Invoke the Bedrock API.
        """
        try:
            formatted_messages, system_message = self._format_messages(messages)

            tool_config = None
            if tools is not None and tools:
                tool_config = {"tools": self._format_tools_for_request(tools)}

            body = {
                "system": system_message,
                "toolConfig": tool_config,
                "inferenceConfig": self._get_inference_config(),
            }
            body = {k: v for k, v in body.items() if v is not None}

            if self.request_params:
                log_debug(f"Calling {self.provider} with request parameters: {self.request_params}", log_level=2)
                body.update(**self.request_params)

            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()
            response = self.get_client().converse(modelId=self.id, messages=formatted_messages, **body)
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(response, response_format=response_format)

            return model_response

        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Iterator[ModelResponse]:
        """
        Invoke the Bedrock API with streaming.
        """
        try:
            formatted_messages, system_message = self._format_messages(messages)

            tool_config = None
            if tools is not None and tools:
                tool_config = {"tools": self._format_tools_for_request(tools)}

            body = {
                "system": system_message,
                "toolConfig": tool_config,
                "inferenceConfig": self._get_inference_config(),
            }
            body = {k: v for k, v in body.items() if v is not None}

            if self.request_params:
                body.update(**self.request_params)

            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            stream_state = self._create_stream_state()

            for chunk in self.get_client().converse_stream(modelId=self.id, messages=formatted_messages, **body)[
                "stream"
            ]:
                yield self._parse_provider_response_delta_with_state(chunk, stream_state)

            assistant_message.metrics.stop_timer()

        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Async invoke the Bedrock API.
        """
        try:
            formatted_messages, system_message = self._format_messages(messages)

            tool_config = None
            if tools is not None and tools:
                tool_config = {"tools": self._format_tools_for_request(tools)}

            body = {
                "system": system_message,
                "toolConfig": tool_config,
                "inferenceConfig": self._get_inference_config(),
            }
            body = {k: v for k, v in body.items() if v is not None}

            if self.request_params:
                log_debug(f"Calling {self.provider} with request parameters: {self.request_params}", log_level=2)
                body.update(**self.request_params)

            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            async with self.get_async_client() as client:
                response = await client.converse(modelId=self.id, messages=formatted_messages, **body)

            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(response, response_format=response_format)

            return model_response

        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> AsyncIterator[ModelResponse]:
        """
        Async invoke the Bedrock API with streaming.
        """
        try:
            formatted_messages, system_message = self._format_messages(messages)

            tool_config = None
            if tools is not None and tools:
                tool_config = {"tools": self._format_tools_for_request(tools)}

            body = {
                "system": system_message,
                "toolConfig": tool_config,
                "inferenceConfig": self._get_inference_config(),
            }
            body = {k: v for k, v in body.items() if v is not None}

            if self.request_params:
                body.update(**self.request_params)

            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            stream_state = self._create_stream_state()

            async with self.get_async_client() as client:
                response = await client.converse_stream(modelId=self.id, messages=formatted_messages, **body)
                async for chunk in response["stream"]:
                    yield self._parse_provider_response_delta_with_state(chunk, stream_state)

            assistant_message.metrics.stop_timer()

        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name=self.name, model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    # Overwrite the default from the base model
    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], **kwargs
    ) -> None:
        """
        Handle the results of function calls.

        Args:
            messages (List[Message]): The list of conversation messages.
            function_call_results (List[Message]): The results of the function calls.
            **kwargs: Additional arguments including tool_ids.
        """
        if function_call_results:
            tool_ids = kwargs.get("tool_ids", [])
            tool_result_content: List = []

            for _fc_message_index, _fc_message in enumerate(function_call_results):
                # Use tool_call_id from message if tool_ids list is insufficient
                tool_id = tool_ids[_fc_message_index] if _fc_message_index < len(tool_ids) else _fc_message.tool_call_id
                tool_result = {
                    "toolUseId": tool_id,
                    "content": [{"json": {"result": _fc_message.content}}],
                }
                tool_result_content.append({"toolResult": tool_result})

            messages.append(Message(role="user", content=tool_result_content))

    def _parse_provider_response(self, response: Dict[str, Any], **kwargs) -> ModelResponse:
        """
        Parse the provider response.

        Args:
            response (Dict[str, Any]): The response from the provider.

        Returns:
            ModelResponse: The parsed response.
        """
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
            model_response.response_usage = self._get_metrics(response["usage"])

        return model_response

    def process_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Iterator[ModelResponse]:
        """
        Process the synchronous response stream.

        Args:
            messages (List[Message]): The messages to include in the request.
            assistant_message (Message): The assistant message.
            stream_data (MessageData): The stream data.
        """
        for response_delta in self.invoke_stream(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        ):
            should_yield = False

            if response_delta.content:
                stream_data.response_content += response_delta.content
                should_yield = True

            if response_delta.tool_calls:
                if stream_data.response_tool_calls is None:
                    stream_data.response_tool_calls = []
                stream_data.response_tool_calls.extend(response_delta.tool_calls)
                should_yield = True

            if response_delta.extra:
                self._merge_stream_extra(stream_data=stream_data, extra=response_delta.extra)
                should_yield = True

            if should_yield:
                yield response_delta

    async def aprocess_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> AsyncIterator[ModelResponse]:
        """
        Process the asynchronous response stream.

        Args:
            messages (List[Message]): The messages to include in the request.
            assistant_message (Message): The assistant message.
            stream_data (MessageData): The stream data.
        """
        async for response_delta in self.ainvoke_stream(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        ):
            should_yield = False

            if response_delta.content:
                stream_data.response_content += response_delta.content
                should_yield = True

            if response_delta.tool_calls:
                if stream_data.response_tool_calls is None:
                    stream_data.response_tool_calls = []
                stream_data.response_tool_calls.extend(response_delta.tool_calls)
                should_yield = True

            if response_delta.extra:
                self._merge_stream_extra(stream_data=stream_data, extra=response_delta.extra)
                should_yield = True

            if should_yield:
                yield response_delta

        self._populate_assistant_message(assistant_message=assistant_message, provider_response=response_delta)

    def _create_stream_state(self) -> Dict[str, Any]:
        return {"current_tool_use": None}

    def _merge_stream_extra(self, stream_data: MessageData, extra: Dict[str, Any]) -> None:
        if not extra:
            return

        if stream_data.extra is None:
            stream_data.extra = {}

        for key, value in extra.items():
            if isinstance(value, list):
                existing = stream_data.extra.get(key)
                if isinstance(existing, list):
                    existing.extend(value)
                else:
                    stream_data.extra[key] = list(value)
            else:
                stream_data.extra[key] = value

    def _parse_provider_response_delta(self, response_delta: Dict[str, Any]) -> ModelResponse:  # type: ignore
        """Parse the provider response delta for streaming.

        Args:
            response_delta: The streaming response delta from AWS Bedrock

        Returns:
            ModelResponse: The parsed model response delta
        """
        if not hasattr(self, "_standalone_stream_state"):
            self._standalone_stream_state = self._create_stream_state()

        return self._parse_provider_response_delta_with_state(response_delta, self._standalone_stream_state)

    def _parse_provider_response_delta_with_state(
        self, response_delta: Dict[str, Any], stream_state: Dict[str, Any]
    ) -> ModelResponse:
        model_response = ModelResponse(role="assistant")

        if "contentBlockDelta" in response_delta:
            delta = response_delta["contentBlockDelta"].get("delta", {})
            if isinstance(delta, dict):
                tool_use_delta = delta.get("toolUse")
                if isinstance(tool_use_delta, dict):
                    self._append_streaming_tool_input_chunk(tool_use_delta.get("input"), stream_state)
                if "text" in delta:
                    model_response.content = delta["text"]

        elif "contentBlockStart" in response_delta:
            start = response_delta["contentBlockStart"].get("start", {})
            tool_use = start.get("toolUse") if isinstance(start, dict) else None
            if isinstance(tool_use, dict):
                self._start_streaming_tool_use(tool_use, stream_state)

        elif "contentBlockStop" in response_delta:
            tool_call = self._finalize_streaming_tool_use(stream_state)
            if tool_call is not None:
                model_response.tool_calls = [tool_call]
                tool_id = tool_call.get("id")
                if tool_id:
                    model_response.extra = {"tool_ids": [tool_id]}

        elif "metadata" in response_delta or "messageStop" in response_delta:
            body = response_delta.get("metadata") or response_delta.get("messageStop") or {}
            if "usage" in body:
                model_response.response_usage = self._get_metrics(body["usage"])

        return model_response

    def _start_streaming_tool_use(self, tool_use: Dict[str, Any], stream_state: Dict[str, Any]) -> None:
        stream_state["current_tool_use"] = {
            "toolUseId": tool_use.get("toolUseId", ""),
            "name": tool_use.get("name", ""),
            "input_chunks": [],
            "input_dict": None,
        }

        initial_input = tool_use.get("input")
        if initial_input not in (None, ""):
            if isinstance(initial_input, dict):
                stream_state["current_tool_use"]["input_dict"] = initial_input
            else:
                self._append_streaming_tool_input_chunk(initial_input, stream_state)

    def _append_streaming_tool_input_chunk(self, chunk: Any, stream_state: Dict[str, Any]) -> None:
        if not chunk:
            return

        current = stream_state.get("current_tool_use")
        if not current:
            return

        if isinstance(chunk, dict):
            existing = current.get("input_dict") or {}
            existing.update(chunk)
            current["input_dict"] = existing
            return

        if not isinstance(chunk, str):
            try:
                chunk = json.dumps(chunk)
            except (TypeError, ValueError):
                chunk = str(chunk)

        if chunk:
            current.setdefault("input_chunks", []).append(chunk)

    def _finalize_streaming_tool_use(self, stream_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = stream_state.get("current_tool_use")
        if not current:
            return None

        tool_use_id = current.get("toolUseId", "")
        tool_name = current.get("name", "")

        tool_input = current.get("input_dict")
        if tool_input is None:
            raw_chunks = "".join(current.get("input_chunks", []))
            tool_input = self._decode_streaming_tool_input(raw_chunks, tool_use_id)

        serialized_arguments = self._serialize_tool_input(tool_input, tool_use_id)

        stream_state["current_tool_use"] = None

        if not tool_name and not tool_use_id and serialized_arguments == "{}":
            return None

        return {
            "id": tool_use_id,
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": serialized_arguments,
            },
        }

    def _decode_streaming_tool_input(self, raw_input: str, tool_use_id: str) -> Any:
        if not raw_input or not raw_input.strip():
            return {}

        try:
            return json.loads(raw_input)
        except json.JSONDecodeError as exc:
            log_warning(f"Failed to decode Bedrock streaming tool input for tool call {tool_use_id}: {exc}")
            return {}

    def _serialize_tool_input(self, tool_input: Any, tool_use_id: str) -> str:
        if tool_input is None:
            return "{}"

        normalized_input = self._normalize_tool_input(tool_input)

        try:
            return json.dumps(normalized_input)
        except (TypeError, ValueError) as exc:
            log_warning(f"Failed to serialize Bedrock tool input for streaming tool call {tool_use_id}: {exc}")
            return "{}"

    def _normalize_tool_input(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._normalize_tool_input(val) for key, val in value.items()}
        if isinstance(value, list):
            return [self._normalize_tool_input(item) for item in value]
        if isinstance(value, tuple):
            return [self._normalize_tool_input(item) for item in value]
        if isinstance(value, Decimal):
            return float(value)
        return value

    def _get_metrics(self, response_usage: Dict[str, Any]) -> Metrics:
        """
        Parse the given AWS Bedrock usage into an Agno Metrics object.

        Args:
            response_usage: Usage data from AWS Bedrock

        Returns:
            Metrics: Parsed metrics data
        """
        metrics = Metrics()

        metrics.input_tokens = response_usage.get("inputTokens", 0) or 0
        metrics.output_tokens = response_usage.get("outputTokens", 0) or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics
