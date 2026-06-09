import json
from dataclasses import dataclass
from os import getenv
from time import sleep
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Type, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ContextWindowExceededError, ModelAuthenticationError, ModelProviderError
from agno.media import Audio
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.utils.log import log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message
from agno.utils.reasoning import extract_thinking_content

# The Agno gateway endpoint (OpenAI chat-completions compatible). Override with
# AGNO_GATEWAY_BASE_URL for testing.
DEFAULT_BASE_URL = "https://gateway.agno.com/v1"

# Default model. Models are addressed as "<provider>/<model>", e.g. "openai/gpt-5.4".
DEFAULT_AGNO_MODEL = "openai/gpt-5.4"

# BYOK convenience: provider prefix -> standard env var holding that provider's key.
PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}

# Transient HTTP statuses worth retrying.
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

_ROLE_MAP = {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"}


@dataclass
class Agno(Model):
    """Use any model through the Agno gateway with a single Agno API key.

    Talks to the gateway over httpx using the OpenAI chat-completions schema, so it
    needs no provider SDK (only httpx + pydantic, both agno-core deps). The gateway
    routes to every provider by the model id prefix and handles provider specifics.

    Address models as ``<provider>/<model>``::

        Agno(id="openai/gpt-5.4")
        Agno(id="anthropic/claude-opus-4-8")

    Key resolution: explicit ``api_key`` > ``AGNO_API_KEY`` > the provider key for the
    id prefix (BYOK). All auth flows through the gateway.
    """

    id: str = DEFAULT_AGNO_MODEL
    name: str = "Agno"
    provider: str = "Agno"

    # Connection / auth
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: Optional[float] = None
    max_retries: int = 3
    default_headers: Optional[Dict[str, str]] = None

    # Generation params (OpenAI chat-completions schema)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    seed: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None
    reasoning_effort: Optional[str] = None
    strict_output: bool = False
    request_params: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ auth ---
    def _resolve_auth(self) -> Tuple[str, str]:
        # Anthropic is not yet supported: the gateway's chat-completions endpoint returns
        # empty content for Anthropic models. Support via the messages endpoint is planned.
        # Fail loudly here rather than returning a blank response.
        if self.id.startswith("anthropic/"):
            raise ModelProviderError(
                message=(
                    "Anthropic models are not yet supported through the Agno gateway. The "
                    "chat-completions endpoint returns empty content for Anthropic; support via "
                    "the messages endpoint is planned."
                ),
                model_name=self.name,
                model_id=self.id,
            )

        key = self.api_key or getenv("AGNO_API_KEY")
        if not key:
            env_var = PROVIDER_KEY_ENV.get(self.id.split("/", 1)[0])
            key = getenv(env_var) if env_var else None
        if not key:
            byok = PROVIDER_KEY_ENV.get(self.id.split("/", 1)[0])
            hint = f" or {byok} (bring your own key)" if byok else ""
            raise ModelAuthenticationError(
                message=f"No API key found for {self.id!r}. Set AGNO_API_KEY{hint}, or pass api_key=... explicitly.",
                model_name=self.name,
            )
        base = self.base_url or getenv("AGNO_GATEWAY_BASE_URL") or DEFAULT_BASE_URL
        return key, base

    def _headers(self, key: str) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if self.default_headers:
            headers.update(self.default_headers)
        return headers

    # --------------------------------------------------------------- request ---
    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        content = message.get_content(use_compressed_content=compress_tool_results)
        message_dict: Dict[str, Any] = {
            "role": _ROLE_MAP.get(message.role, message.role),
            "content": content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        if (message.images and len(message.images) > 0) or (message.audio and len(message.audio) > 0):
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                if message.images:
                    message_dict["content"].extend(images_to_message(images=message.images))
                if message.audio:
                    message_dict["content"].extend(audio_to_message(audio=message.audio))

        if message.audio_output is not None:
            message_dict["content"] = ""
            message_dict["audio"] = {"id": message.audio_output.id}

        if message.videos:
            log_warning("Video input is currently unsupported.")

        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        if message.files:
            existing = message_dict.get("content")
            if isinstance(existing, str):
                message_dict["content"] = [{"type": "text", "text": existing}]
            elif existing is None:
                message_dict["content"] = []
            for file in message.files:
                file_part = _format_file_for_message(file)
                if file_part:
                    message_dict["content"].insert(0, file_part)

        if message.content is None:
            message_dict["content"] = ""
        return message_dict

    def _format_all_messages(
        self, messages: List[Message], compress_tool_results: bool = False
    ) -> List[Dict[str, Any]]:
        from agno.utils.message import normalize_tool_messages, reformat_tool_call_ids

        messages = normalize_tool_messages(messages)
        normalized = reformat_tool_call_ids(messages, provider="openai_chat")
        return [self._format_message(m, compress_tool_results) for m in normalized]

    def _request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        base_params: Dict[str, Any] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "top_p": self.top_p,
            "stop": self.stop,
            "seed": self.seed,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
            "user": self.user,
            "reasoning_effort": self.reasoning_effort,
        }

        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                from agno.utils.models.schema_utils import get_response_schema_for_provider

                schema = get_response_schema_for_provider(response_format, "openai")
                base_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": response_format.__name__, "schema": schema, "strict": self.strict_output},
                }
            else:
                base_params["response_format"] = response_format

        params = {k: v for k, v in base_params.items() if v is not None}

        if tools:
            params["tools"] = tools
            if tool_choice is not None:
                params["tool_choice"] = tool_choice

        if self.request_params:
            params.update(self.request_params)
        return params

    def _body(self, messages, response_format, tools, tool_choice, compress_tool_results, stream) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.id,
            "messages": self._format_all_messages(messages, compress_tool_results),
            **self._request_params(response_format, tools, tool_choice),
        }
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    # ----------------------------------------------------------- transport ---
    def _raise_for_error(self, status: int, text: str) -> None:
        try:
            err = json.loads(text).get("error", {})
        except Exception:
            err = {}
        message = err.get("message", text) if isinstance(err, dict) else text
        code = err.get("code") if isinstance(err, dict) else None
        if status in (401, 403):
            raise ModelAuthenticationError(message=message, model_name=self.name)
        if code == "context_length_exceeded":
            raise ContextWindowExceededError(
                message=message, status_code=status, model_name=self.name, model_id=self.id
            )
        raise ModelProviderError(message=message, status_code=status, model_name=self.name, model_id=self.id)

    def _backoff(self, attempt: int) -> float:
        return min(8.0, 0.5 * (2**attempt))

    def invoke(
        self,
        messages,
        assistant_message,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results=False,
    ) -> ModelResponse:
        key, base = self._resolve_auth()
        body = self._body(messages, response_format, tools, tool_choice, compress_tool_results, stream=False)
        assistant_message.metrics.start_timer()
        attempt = 0
        while True:
            try:
                r = httpx.post(
                    f"{base}/chat/completions", json=body, headers=self._headers(key), timeout=self.timeout or 60.0
                )
                if r.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                    attempt += 1
                    sleep(self._backoff(attempt))
                    continue
                break
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < self.max_retries:
                    attempt += 1
                    sleep(self._backoff(attempt))
                    continue
                raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        assistant_message.metrics.stop_timer()
        if r.status_code != 200:
            self._raise_for_error(r.status_code, r.text)
        return self._parse_provider_response(r.json())

    async def ainvoke(
        self,
        messages,
        assistant_message,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results=False,
    ) -> ModelResponse:
        key, base = self._resolve_auth()
        body = self._body(messages, response_format, tools, tool_choice, compress_tool_results, stream=False)
        assistant_message.metrics.start_timer()
        async with httpx.AsyncClient(timeout=self.timeout or 60.0) as client:
            attempt = 0
            while True:
                try:
                    r = await client.post(f"{base}/chat/completions", json=body, headers=self._headers(key))
                    if r.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                        attempt += 1
                        await _asleep(self._backoff(attempt))
                        continue
                    break
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    if attempt < self.max_retries:
                        attempt += 1
                        await _asleep(self._backoff(attempt))
                        continue
                    raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        assistant_message.metrics.stop_timer()
        if r.status_code != 200:
            self._raise_for_error(r.status_code, r.text)
        return self._parse_provider_response(r.json())

    def invoke_stream(
        self,
        messages,
        assistant_message,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results=False,
    ) -> Iterator[ModelResponse]:
        key, base = self._resolve_auth()
        body = self._body(messages, response_format, tools, tool_choice, compress_tool_results, stream=True)
        assistant_message.metrics.start_timer()
        with httpx.stream(
            "POST", f"{base}/chat/completions", json=body, headers=self._headers(key), timeout=self.timeout or 60.0
        ) as r:
            if r.status_code != 200:
                self._raise_for_error(r.status_code, r.read().decode())
            for line in r.iter_lines():
                data = _sse_data(line)
                if data is not None:
                    yield self._parse_provider_response_delta(data)
        assistant_message.metrics.stop_timer()

    async def ainvoke_stream(
        self,
        messages,
        assistant_message,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results=False,
    ) -> AsyncIterator[ModelResponse]:
        key, base = self._resolve_auth()
        body = self._body(messages, response_format, tools, tool_choice, compress_tool_results, stream=True)
        assistant_message.metrics.start_timer()
        async with httpx.AsyncClient(timeout=self.timeout or 60.0) as client:
            async with client.stream("POST", f"{base}/chat/completions", json=body, headers=self._headers(key)) as r:
                if r.status_code != 200:
                    self._raise_for_error(r.status_code, (await r.aread()).decode())
                async for line in r.aiter_lines():
                    data = _sse_data(line)
                    if data is not None:
                        yield self._parse_provider_response_delta(data)
        assistant_message.metrics.stop_timer()

    # ------------------------------------------------------------- parsing ---
    def _parse_provider_response(self, response: Dict[str, Any], **kwargs) -> ModelResponse:
        model_response = ModelResponse()
        if response.get("error"):
            err = response["error"]
            raise ModelProviderError(
                message=err.get("message", "Unknown model error") if isinstance(err, dict) else str(err),
                model_name=self.name,
                model_id=self.id,
            )
        message = response["choices"][0]["message"]
        if message.get("role"):
            model_response.role = message["role"]
        if message.get("content") is not None:
            model_response.content = message["content"]
            if model_response.content:
                reasoning, output = extract_thinking_content(model_response.content)
                if reasoning:
                    model_response.reasoning_content = reasoning
                    model_response.content = output
        if message.get("tool_calls"):
            model_response.tool_calls = message["tool_calls"]
        if message.get("reasoning_content") is not None:
            model_response.reasoning_content = message["reasoning_content"]
        elif message.get("reasoning") is not None:
            model_response.reasoning_content = message["reasoning"]
        if isinstance(message.get("audio"), dict):
            try:
                model_response.audio = Audio(
                    id=message["audio"].get("id"),
                    content=message["audio"].get("data"),
                    expires_at=message["audio"].get("expires_at"),
                    transcript=message["audio"].get("transcript"),
                )
            except Exception as e:
                log_warning(f"Error processing audio: {str(e)}")
        if response.get("usage"):
            model_response.response_usage = self._get_metrics(response["usage"])
        model_response.provider_data = {k: response[k] for k in ("id", "system_fingerprint") if response.get(k)}
        return model_response

    def _parse_provider_response_delta(self, chunk: Dict[str, Any]) -> ModelResponse:
        model_response = ModelResponse()
        choices = chunk.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            if delta.get("content") is not None:
                model_response.content = delta["content"]
            if delta.get("tool_calls") is not None:
                model_response.tool_calls = delta["tool_calls"]
            if delta.get("reasoning_content") is not None:
                model_response.reasoning_content = delta["reasoning_content"]
            elif delta.get("reasoning") is not None:
                model_response.reasoning_content = delta["reasoning"]
        if chunk.get("usage"):
            model_response.response_usage = self._get_metrics(chunk["usage"])
        return model_response

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge streamed tool-call fragments (by index) into complete tool calls."""
        tool_calls: List[Dict[str, Any]] = []
        for tc in tool_calls_data:
            index = tc.get("index") or 0
            fn = tc.get("function") or {}
            if len(tool_calls) <= index:
                tool_calls.extend([{} for _ in range(index - len(tool_calls) + 1)])
            entry = tool_calls[index]
            if not entry:
                entry["id"] = tc.get("id")
                entry["type"] = tc.get("type")
                entry["function"] = {"name": fn.get("name") or "", "arguments": fn.get("arguments") or ""}
            else:
                if fn.get("name"):
                    entry["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    entry["function"]["arguments"] += fn["arguments"]
                if tc.get("id"):
                    entry["id"] = tc["id"]
                if tc.get("type"):
                    entry["type"] = tc["type"]
        return tool_calls

    def _get_metrics(self, usage: Dict[str, Any]) -> MessageMetrics:
        metrics = MessageMetrics()
        metrics.input_tokens = usage.get("prompt_tokens") or 0
        metrics.output_tokens = usage.get("completion_tokens") or 0
        metrics.total_tokens = usage.get("total_tokens") or 0
        if prompt_details := usage.get("prompt_tokens_details"):
            metrics.audio_input_tokens = prompt_details.get("audio_tokens") or 0
            metrics.cache_read_tokens = prompt_details.get("cached_tokens") or 0
        if completion_details := usage.get("completion_tokens_details"):
            metrics.audio_output_tokens = completion_details.get("audio_tokens") or 0
            metrics.reasoning_tokens = completion_details.get("reasoning_tokens") or 0
        metrics.audio_total_tokens = metrics.audio_input_tokens + metrics.audio_output_tokens
        metrics.cost = usage.get("cost")
        return metrics


def _sse_data(line: str) -> Optional[Dict[str, Any]]:
    """Parse one SSE line into a JSON object, or None for keepalives / [DONE]."""
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


async def _asleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
