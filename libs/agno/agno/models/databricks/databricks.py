import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.databricks.async_client import AsyncDatabricksClient
from agno.databricks.client import DatabricksClient
from agno.databricks.settings import DatabricksSettings
from agno.exceptions import ContextWindowExceededError, ModelAuthenticationError, ModelProviderError
from agno.media import Audio
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message
from agno.utils.reasoning import extract_thinking_content


@dataclass
class Databricks(Model):
    """Databricks model provider for serving-endpoint chat completions.

    Connects to Databricks Model Serving endpoints via the Databricks REST API.
    Supports streaming, tool calling, and structured output via OpenAI-compatible API.
    """

    id: str = "databricks-endpoint"
    name: str = "Databricks"
    provider: str = "Databricks"
    supports_native_structured_outputs: bool = False
    supports_json_schema_outputs: bool = False

    endpoint: Optional[str] = None
    host: Optional[str] = None
    workspace_url: Optional[str] = None
    token: Optional[str] = None

    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    user: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    strict_output: bool = True
    request_params: Optional[Dict[str, Any]] = None
    default_headers: Optional[Dict[str, str]] = None
    role_map: Optional[Dict[str, str]] = None
    include_stream_usage: bool = True

    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    settings: Optional[DatabricksSettings] = None
    client: Optional[DatabricksClient] = None  # type: ignore[assignment]
    async_client: Optional[AsyncDatabricksClient] = None  # type: ignore[assignment]

    default_role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }

    def __post_init__(self):
        super().__post_init__()
        if self.endpoint is None:
            self.endpoint = self.id
        self._warned_unsupported_params: set = set()

    def _get_settings(self) -> DatabricksSettings:
        overrides: Dict[str, Any] = {}
        if self.host is not None:
            overrides["host"] = self.host
            if self.workspace_url is None:
                overrides["workspace_url"] = self.host
        if self.workspace_url is not None:
            overrides["workspace_url"] = self.workspace_url
        if self.token is not None:
            overrides["token"] = self.token
        if self.timeout is not None:
            overrides["timeout"] = self.timeout
        if self.max_retries is not None:
            overrides["max_retries"] = self.max_retries
        if self.default_headers is not None:
            overrides["default_headers"] = self.default_headers

        if self.settings is None:
            if overrides:
                self.settings = DatabricksSettings.from_values(**overrides)
            else:
                self.settings = DatabricksSettings()
        elif overrides:
            self.settings = self.settings.with_overrides(**overrides)

        return self.settings

    def get_client(self) -> DatabricksClient:
        if self.client is None:
            self.client = DatabricksClient(
                settings=self._get_settings(),
            )
        return self.client

    def get_async_client(self) -> AsyncDatabricksClient:
        if self.async_client is None:
            self.async_client = AsyncDatabricksClient(
                settings=self._get_settings(),
            )
        return self.async_client

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> Dict[str, Any]:
        ignored_params: Dict[str, Any] = {
            "frequency_penalty": self.frequency_penalty,
            "logit_bias": self.logit_bias,
            "presence_penalty": self.presence_penalty,
            "seed": self.seed,
            "user": self.user,
            "metadata": self.metadata,
        }
        base_params: Dict[str, Any] = {
            "logprobs": self.logprobs,
            "top_logprobs": self.top_logprobs,
            "max_tokens": self.max_tokens,
            "stop": self.stop,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        ignored_param_names = frozenset(name for name, value in ignored_params.items() if value is not None)
        new_warnings = ignored_param_names - self._warned_unsupported_params
        if new_warnings:
            self._warned_unsupported_params.update(new_warnings)
            log_warning(
                "Ignoring unsupported Databricks Chat Completions parameter(s): "
                + ", ".join(sorted(new_warnings))
            )

        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                from agno.utils.models.schema_utils import get_response_schema_for_provider

                schema = get_response_schema_for_provider(response_format, "openai")
                base_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.__name__,
                        "schema": schema,
                        "strict": self.strict_output,
                    },
                }
            else:
                base_params["response_format"] = response_format

        request_params = {k: v for k, v in base_params.items() if v is not None}

        if tools:
            request_params["tools"] = tools
            if tool_choice is not None:
                request_params["tool_choice"] = tool_choice

        if self.request_params:
            critical_keys = {"model", "messages", "stream"}
            overridden = critical_keys & self.request_params.keys()
            if overridden:
                log_warning(f"request_params overrides critical key(s): {', '.join(sorted(overridden))}")
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

    def to_dict(self) -> Dict[str, Any]:
        model_dict = super().to_dict()
        model_dict.update(
            {
                "endpoint": self.endpoint,
                "host": self.host,
                "workspace_url": self.workspace_url,
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "top_logprobs": self.top_logprobs,
                "max_tokens": self.max_tokens,
                "presence_penalty": self.presence_penalty,
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "user": self.user,
                "metadata": self.metadata,
            }
        )
        return {k: v for k, v in model_dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Databricks":
        import dataclasses

        known_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        tool_result = message.get_content(use_compressed_content=compress_tool_results)

        message_dict: Dict[str, Any] = {
            "role": (self.role_map or self.default_role_map).get(message.role, message.role),
            "content": tool_result,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        if (message.images is not None and len(message.images) > 0) or (
            message.audio is not None and len(message.audio) > 0
        ):
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                if message.images is not None:
                    message_dict["content"].extend(images_to_message(images=message.images))
                if message.audio is not None:
                    message_dict["content"].extend(audio_to_message(audio=message.audio))

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported by Databricks.")

        if message.audio_output is not None:
            message_dict["content"] = ""
            message_dict["audio"] = {"id": message.audio_output.id}

        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict.pop("tool_calls", None)

        if message.files is not None:
            content = message_dict.get("content")
            if isinstance(content, str):
                text = content
                message_dict["content"] = [{"type": "text", "text": text}]
            elif content is None:
                message_dict["content"] = []

            for file in message.files:
                file_part = _format_file_for_message(file)
                if file_part:
                    message_dict["content"].insert(0, file_part)

        if message.content is None and not isinstance(message_dict.get("content"), list):
            message_dict["content"] = ""

        return message_dict

    def _format_all_messages(
        self, messages: List[Message], compress_tool_results: bool = False
    ) -> List[Dict[str, Any]]:
        from agno.utils.message import normalize_tool_messages, reformat_tool_call_ids

        messages = normalize_tool_messages(messages)
        normalized = reformat_tool_call_ids(messages, provider="openai_chat")
        return [self._format_message(m, compress_tool_results) for m in normalized]

    def _build_payload(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "model": self.endpoint or self.id,
            "messages": self._format_all_messages(messages, compress_tool_results),
            "stream": stream,
        }
        payload.update(
            self.get_request_params(
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
            )
        )

        if stream and self.include_stream_usage:
            payload["stream_options"] = {"include_usage": True}

        return payload

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        assistant_message.metrics.start_timer()
        try:
            payload = self._build_payload(
                messages,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
            )
            provider_response = self.get_client().request_json("POST", "/serving-endpoints/chat/completions", json=payload)
            return self._parse_provider_response(provider_response, response_format=response_format)
        except ContextWindowExceededError:
            raise
        except ModelAuthenticationError:
            raise
        except ModelProviderError:
            raise
        except Exception as e:
            log_error(f"Error from Databricks API: {str(e)}")
            provider_error = ModelProviderError(message=str(e), model_name=self.name, model_id=self.id)
            raise ModelProviderError.classify(provider_error) from e
        finally:
            assistant_message.metrics.stop_timer()

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        assistant_message.metrics.start_timer()
        try:
            payload = self._build_payload(
                messages,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
            )
            provider_response = await self.get_async_client().request_json(
                "POST", "/serving-endpoints/chat/completions", json=payload
            )
            return self._parse_provider_response(provider_response, response_format=response_format)
        except ContextWindowExceededError:
            raise
        except ModelAuthenticationError:
            raise
        except ModelProviderError:
            raise
        except Exception as e:
            log_error(f"Error from Databricks API: {str(e)}")
            provider_error = ModelProviderError(message=str(e), model_name=self.name, model_id=self.id)
            raise ModelProviderError.classify(provider_error) from e
        finally:
            assistant_message.metrics.stop_timer()

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> Iterator[ModelResponse]:
        assistant_message.metrics.start_timer()
        try:
            payload = self._build_payload(
                messages,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
                stream=True,
            )
            with self.get_client().stream("POST", "/serving-endpoints/chat/completions", json=payload) as response:
                for line in response.iter_lines():
                    model_response = self._parse_sse_line(line)
                    if model_response is not None:
                        yield model_response
        except ContextWindowExceededError:
            raise
        except ModelAuthenticationError:
            raise
        except ModelProviderError:
            raise
        except Exception as e:
            log_error(f"Error from Databricks API: {str(e)}")
            provider_error = ModelProviderError(message=str(e), model_name=self.name, model_id=self.id)
            raise ModelProviderError.classify(provider_error) from e
        finally:
            assistant_message.metrics.stop_timer()

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        assistant_message.metrics.start_timer()
        try:
            payload = self._build_payload(
                messages,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
                stream=True,
            )
            async with self.get_async_client().stream("POST", "/serving-endpoints/chat/completions", json=payload) as response:
                async for line in response.aiter_lines():
                    model_response = self._parse_sse_line(line)
                    if model_response is not None:
                        yield model_response
        except ContextWindowExceededError:
            raise
        except ModelAuthenticationError:
            raise
        except ModelProviderError:
            raise
        except Exception as e:
            log_error(f"Error from Databricks API: {str(e)}")
            provider_error = ModelProviderError(message=str(e), model_name=self.name, model_id=self.id)
            raise ModelProviderError.classify(provider_error) from e
        finally:
            assistant_message.metrics.stop_timer()

    def _parse_sse_line(self, line: str) -> Optional[ModelResponse]:
        if not line:
            return None

        cleaned = line.strip()
        if not cleaned.startswith("data:"):
            return None

        payload = cleaned.removeprefix("data:").strip()
        if payload == "[DONE]":
            return None

        try:
            response_delta = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                message=f"Failed to decode Databricks streaming payload: {payload}",
                model_name=self.name,
                model_id=self.id,
            ) from exc

        return self._parse_provider_response_delta(response_delta)

    def _parse_provider_response(
        self,
        response: Dict[str, Any],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        model_response = ModelResponse()

        if response is None:
            return model_response
        if not isinstance(response, dict):
            raise ModelProviderError(
                message=f"Unexpected response type from Databricks: {type(response).__name__}",
                model_name=self.name,
                model_id=self.id,
            )

        if response.get("error"):
            error = response["error"]
            message = error.get("message", "Unknown model error") if isinstance(error, dict) else str(error)
            error_code = error.get("code") if isinstance(error, dict) else None
            msg_lower = str(message).lower()
            if (
                error_code == "context_length_exceeded"
                or "context_length_exceeded" in msg_lower
                or "maximum context length" in msg_lower
            ):
                raise ContextWindowExceededError(
                    message=message,
                    model_name=self.name,
                    model_id=self.id,
                )
            raise ModelProviderError(message=message, model_name=self.name, model_id=self.id)

        choices = response.get("choices") or []
        if not choices:
            return model_response

        response_message = choices[0].get("message", {})

        if response_message.get("role") is not None:
            model_response.role = response_message.get("role")

        if response_message.get("content") is not None:
            model_response.content = response_message.get("content")
            if model_response.content:
                reasoning_content, output_content = extract_thinking_content(model_response.content)
                if reasoning_content:
                    model_response.reasoning_content = reasoning_content
                    model_response.content = output_content

        tool_calls = response_message.get("tool_calls")
        if tool_calls:
            model_response.tool_calls = tool_calls

        response_audio = response_message.get("audio")
        if response_audio and isinstance(response_audio, dict):
            try:
                model_response.audio = Audio(
                    id=response_audio.get("id"),
                    content=response_audio.get("data"),
                    expires_at=response_audio.get("expires_at"),
                    transcript=response_audio.get("transcript"),
                )
            except Exception as e:
                log_warning(f"Error processing audio: {str(e)}")

        if response_message.get("reasoning_content") is not None:
            model_response.reasoning_content = response_message.get("reasoning_content")
        elif response_message.get("reasoning") is not None:
            model_response.reasoning_content = response_message.get("reasoning")

        usage = response.get("usage")
        if usage is not None:
            model_response.response_usage = self._get_metrics(usage)

        provider_data: Dict[str, Any] = {}
        if response.get("id"):
            provider_data["id"] = response.get("id")
        if response.get("model"):
            provider_data["model"] = response.get("model")
        if response.get("system_fingerprint"):
            provider_data["system_fingerprint"] = response.get("system_fingerprint")
        if response.get("object"):
            provider_data["object"] = response.get("object")
        if provider_data:
            model_response.provider_data = provider_data

        return model_response

    def _parse_provider_response_delta(self, response_delta: Dict[str, Any]) -> ModelResponse:
        model_response = ModelResponse()

        choices = response_delta.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            if delta.get("content") is not None:
                model_response.content = delta.get("content")

                provider_data: Dict[str, Any] = {}
                if response_delta.get("id"):
                    provider_data["id"] = response_delta.get("id")
                if response_delta.get("model"):
                    provider_data["model"] = response_delta.get("model")
                if response_delta.get("system_fingerprint"):
                    provider_data["system_fingerprint"] = response_delta.get("system_fingerprint")
                if provider_data:
                    model_response.provider_data = provider_data

            delta_tool_calls = delta.get("tool_calls")
            if isinstance(delta_tool_calls, list):
                model_response.tool_calls = delta_tool_calls

            if delta.get("reasoning_content") is not None:
                model_response.reasoning_content = delta.get("reasoning_content")
            elif delta.get("reasoning") is not None:
                model_response.reasoning_content = delta.get("reasoning")

            response_audio = delta.get("audio")
            if response_audio and isinstance(response_audio, dict):
                try:
                    audio_data = response_audio.get("data")
                    audio_id = response_audio.get("id")
                    audio_expires_at = response_audio.get("expires_at")
                    audio_transcript = response_audio.get("transcript")
                    if audio_data is not None or audio_transcript is not None or audio_id is not None:
                        model_response.audio = Audio(
                            id=audio_id or str(uuid4()),
                            content=audio_data or "",
                            expires_at=audio_expires_at,
                            transcript=audio_transcript,
                            sample_rate=24000,
                            mime_type="pcm16",
                        )
                except Exception as e:
                    log_warning(f"Error processing audio: {str(e)}")

        usage = response_delta.get("usage")
        if usage is not None:
            model_response.response_usage = self._get_metrics(usage)

        return model_response

    @staticmethod
    def parse_tool_calls(tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tool_calls: List[Dict[str, Any]] = []

        for tool_call in tool_calls_data:
            index = tool_call.get("index", 0) or 0
            tool_call_id = tool_call.get("id")
            tool_call_type = tool_call.get("type")
            function = tool_call.get("function") or {}
            function_name = function.get("name")
            function_arguments = function.get("arguments")

            if len(tool_calls) <= index:
                tool_calls.extend([
                    {"id": None, "type": None, "function": {"name": "", "arguments": ""}}
                    for _ in range(index - len(tool_calls) + 1)
                ])

            tool_call_entry = tool_calls[index]
            if not tool_call_entry:
                tool_call_entry["id"] = tool_call_id
                tool_call_entry["type"] = tool_call_type
                tool_call_entry["function"] = {
                    "name": function_name or "",
                    "arguments": function_arguments or "",
                }
            else:
                if function_name:
                    tool_call_entry["function"]["name"] = function_name
                if function_arguments:
                    tool_call_entry["function"]["arguments"] += function_arguments
                if tool_call_id:
                    tool_call_entry["id"] = tool_call_id
                if tool_call_type:
                    tool_call_entry["type"] = tool_call_type

        return tool_calls

    def _get_metrics(self, response_usage: Dict[str, Any]) -> MessageMetrics:
        metrics = MessageMetrics()
        metrics.input_tokens = response_usage.get("prompt_tokens", 0) or 0
        metrics.output_tokens = response_usage.get("completion_tokens", 0) or 0
        metrics.total_tokens = response_usage.get("total_tokens", 0) or 0

        prompt_token_details = response_usage.get("prompt_tokens_details") or {}
        metrics.audio_input_tokens = prompt_token_details.get("audio_tokens", 0) or 0
        metrics.cache_read_tokens = prompt_token_details.get("cached_tokens", 0) or 0

        completion_token_details = response_usage.get("completion_tokens_details") or {}
        metrics.audio_output_tokens = completion_token_details.get("audio_tokens", 0) or 0
        metrics.reasoning_tokens = completion_token_details.get("reasoning_tokens", 0) or 0
        metrics.cost = response_usage.get("cost")
        return metrics
