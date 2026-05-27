import asyncio
from collections.abc import AsyncIterator
from copy import copy
from dataclasses import dataclass
from enum import Enum
from os import getenv
from time import perf_counter
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Type, Union
from uuid import uuid4

import httpx
from agno.exceptions import ModelProviderError
from agno.media import AudioResponse
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message
from pydantic import BaseModel

from agno_custom.models.base import MessageData, Model

try:
    from openai import APIConnectionError, APIStatusError, RateLimitError
    from openai import AsyncOpenAI as AsyncOpenAIClient
    from openai import OpenAI as OpenAIClient
    from openai.types.chat import ChatCompletionAudio
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        ChoiceDelta,
    )
    from openai.types.responses import Response
except (ImportError, ModuleNotFoundError) as e:
    raise ImportError("`openai` not installed. Please install using `pip install openai`") from e


class OpenAIPromptCacheRetention(Enum):
    IN_MEMORY = "in_memory"  # default value: volatile gpu memory 5-10 mins max of 1 hr
    LOCAL = "24h"  # more persistent local memory up to 24 hours


class ServiceTier(Enum):
    AUTO = "auto"
    DEFAULT = "default"
    PRIORITY = "priority"  # faster but more expensive
    FLEX = "flex"  # cheaper but slower


@dataclass
class OpenAIChat(Model):
    """
    A class for interacting with OpenAI models using the Chat completions API.

    When ``reasoning_effort`` is set on models that only support effort via the Responses API
    (auto-detected for ``gpt-5*``, ``o3*``, ``o4-mini*``), requests are delegated to Agno's
    ``OpenAIResponses`` so ``reasoning: {effort: ...}`` is used. Other models keep
    ``reasoning_effort`` on chat completions. Override with ``use_reasoning_via_responses_api``.

    For more information, see: https://platform.openai.com/docs/api-reference/chat/create
    """

    id: str = "gpt-4o"
    name: str = "OpenAIChat"
    provider: str = "OpenAI"
    supports_native_structured_outputs: bool = True

    # Request parameters
    store: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    # When reasoning_effort is set: some models only accept effort via the Responses API
    # (reasoning.effort), not chat.completions. None = auto-route gpt-5*, o3*, o4-mini*;
    # True/False = force Responses vs chat regardless of model id.
    use_reasoning_via_responses_api: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    modalities: Optional[List[str]] = None  # "text" and/or "audio"
    audio: Optional[Dict[str, Any]] = (
        None  # E.g. {"voice": "alloy", "format": "wav"}. `format` must be one of `wav`, `mp3`, `flac`, `opus`, or `pcm16`. `voice` must be one of `ash`, `ballad`, `coral`, `sage`, `verse`, `alloy`, `echo`, and `shimmer`.
    )
    presence_penalty: Optional[float] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    user: Optional[str] = None
    top_p: Optional[float] = None
    service_tier: Optional[ServiceTier] = None  # "auto", "default", "priority", or "flex"
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None
    role_map: Optional[Dict[str, str]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None
    prompt_cache_key: str = None
    prompt_cache_retention: Optional[OpenAIPromptCacheRetention] = None

    # Redundant request settings
    redundant_calls: int = 1  # Number of parallel requests to race; set to 1 to disable
    # Tracks the "winning" cache key suffix (e.g., uuid) from previous redundant calls.
    # Allows the system to "stick" to the fast server while exploring fresh ones.
    sticky_cache_state: Optional[Dict[str, str]] = None

    # Adaptive redundancy settings
    adaptive_redundancy: bool = False
    adaptive_redundancy_initial_delay: float = 2.0
    adaptive_redundancy_trace_factor: float = 2.0  # Deviation multiplier (K) for threshold
    adaptive_mode_id: Optional[str] = None
    _current_adaptive_state: Optional[Dict[str, Any]] = None

    # Registry to persist adaptive state across instances with same mode_id
    # Format: {mode_id: {"srtt": float, "rttvar": float, "total_calls": int, "triggered_calls": int}}
    _adaptive_delay_registry: ClassVar[Dict[str, Dict[str, Any]]] = {}

    # The role to map the message role to.
    default_role_map = {
        "system": "developer",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }
    strict_mode: bool = True

    def _model_id_suggests_responses_reasoning_api(self) -> bool:
        mid = (self.id or "").lower()
        if mid.startswith("gpt-5"):
            return True
        if mid.startswith("o3") or mid.startswith("o4-mini"):
            return True
        return False

    def _should_route_reasoning_through_responses_api(self) -> bool:
        if self.reasoning_effort is None:
            return False
        if self.use_reasoning_via_responses_api is True:
            return True
        if self.use_reasoning_via_responses_api is False:
            return False
        return self._model_id_suggests_responses_reasoning_api()

    def _build_openai_responses_model(self) -> Any:
        """Delegate reasoning.effort and tool/formatting to Agno's OpenAIResponses (pinned agno)."""
        from agno.models.openai.responses import OpenAIResponses

        from agno_custom.models.openai.gpt5_responses import GPT5ReasoningOpenAIResponses

        reasoning: Optional[Dict[str, Any]] = None
        if self.reasoning_effort is not None:
            reasoning = {"effort": self.reasoning_effort}

        impl: type = OpenAIResponses
        if (self.id or "").lower().startswith("gpt-5") and reasoning:
            impl = GPT5ReasoningOpenAIResponses

        return impl(
            id=self.id,
            name=self.name,
            api_key=self.api_key,
            organization=self.organization,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            default_headers=self.default_headers,
            default_query=self.default_query,
            http_client=self.http_client,
            client_params=self.client_params,
            store=self.store,
            metadata=self.metadata,
            temperature=self.temperature,
            top_p=self.top_p,
            user=self.user,
            max_output_tokens=self.max_completion_tokens,
            reasoning=reasoning,
            request_params=self.request_params,
        )

    def _messages_for_openai_responses_api(self, messages: List[Message]) -> List[Message]:
        """
        Responses API requires function_call.call_id to match function_call_output.call_id.
        Team/chat history can mix internal ids (fc_*) with OpenAI call_* ids on the same tool
        invocation; OpenAIResponses formats function_call from tool_call['call_id'] and output
        from Message.tool_call_id — remap tool rows to the canonical call id.
        """
        id_to_canonical: Dict[str, str] = {}
        for msg in messages:
            if msg.role != "assistant" or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                if not isinstance(tc, dict):
                    continue
                raw_id = tc.get("id")
                raw_call_id = tc.get("call_id")
                # Prefer OpenAI call_* when present; avoids wrong fc_* in call_id with real id in id.
                canonical: Optional[str] = None
                for candidate in (raw_call_id, raw_id):
                    if candidate is not None and str(candidate).startswith("call_"):
                        canonical = str(candidate)
                        break
                if canonical is None:
                    if raw_call_id is not None:
                        canonical = str(raw_call_id)
                    elif raw_id is not None:
                        canonical = str(raw_id)
                if canonical is None:
                    continue
                tc["call_id"] = canonical
                for key in (raw_id, raw_call_id):
                    if key is not None:
                        id_to_canonical[str(key)] = canonical

        out: List[Message] = []
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id is not None:
                tid = str(msg.tool_call_id)
                canon = id_to_canonical.get(tid, tid)
                if canon != tid:
                    m = copy(msg)
                    m.tool_call_id = canon
                    out.append(m)
                else:
                    out.append(msg)
            else:
                out.append(msg)
        return out

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("OPENAI_API_KEY")
            if not self.api_key:
                log_error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> OpenAIClient:
        """
        Returns an OpenAI client.

        Returns:
            OpenAIClient: An instance of the OpenAI client.
        """
        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        return OpenAIClient(**client_params)

    def get_async_client(self) -> AsyncOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAIClient: An instance of the asynchronous OpenAI client.
        """
        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100),
                timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=5.0),
            )
        return AsyncOpenAIClient(**client_params)

    def get_request_kwargs(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "store": self.store,
            "reasoning_effort": None if self._should_route_reasoning_through_responses_api() else self.reasoning_effort,
            "frequency_penalty": self.frequency_penalty,
            "logit_bias": self.logit_bias,
            "logprobs": self.logprobs,
            "top_logprobs": self.top_logprobs,
            "max_tokens": self.max_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "modalities": self.modalities,
            "audio": self.audio,
            "presence_penalty": self.presence_penalty,
            "seed": self.seed,
            "stop": self.stop,
            "temperature": self.temperature,
            "user": self.user,
            "top_p": self.top_p,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
            "metadata": self.metadata,
        }

        # NOTE: New feature, prompt cache config

        if self.prompt_cache_key:
            base_params["prompt_cache_key"] = self.prompt_cache_key

        if self.prompt_cache_retention:
            base_params["prompt_cache_retention"] = self.prompt_cache_retention.value

        if self.service_tier:
            base_params["service_tier"] = self.service_tier.value

        # Handle response format - always use JSON schema approach
        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                # Convert Pydantic to JSON schema for regular endpoint
                from agno.utils.models.schema_utils import get_response_schema_for_provider

                schema = get_response_schema_for_provider(response_format, "openai")
                base_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.__name__,
                        "schema": schema,
                        "strict": self.strict_mode,
                    },
                }
            else:
                # Handle other response format types (like {"type": "json_object"})
                base_params["response_format"] = response_format

        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}

        # Add tools
        if tools is not None and len(tools) > 0:
            request_params["tools"] = tools

            if tool_choice is not None:
                request_params["tool_choice"] = tool_choice

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "store": self.store,
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "top_logprobs": self.top_logprobs,
                "max_tokens": self.max_tokens,
                "max_completion_tokens": self.max_completion_tokens,
                "modalities": self.modalities,
                "audio": self.audio,
                "presence_penalty": self.presence_penalty,
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "user": self.user,
                "service_tier": self.service_tier.value if self.service_tier else None,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
                "sticky_cache_state": self.sticky_cache_state,
                "prompt_cache_retention": self.prompt_cache_retention.value if self.prompt_cache_retention else None,
                "adaptive_redundancy": self.adaptive_redundancy,
                "adaptive_redundancy_initial_delay": self.adaptive_redundancy_initial_delay,
                "adaptive_redundancy_trace_factor": self.adaptive_redundancy_trace_factor,
                "adaptive_mode_id": self.adaptive_mode_id,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role] if self.role_map else self.default_role_map[message.role],
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if (message.images is not None and len(message.images) > 0) or (
            message.audio is not None and len(message.audio) > 0
        ):
            # Ignore non-string message content
            # because we assume that the images/audio are already added to the message
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                if message.images is not None:
                    message_dict["content"].extend(images_to_message(images=message.images))

                if message.audio is not None:
                    message_dict["content"].extend(audio_to_message(audio=message.audio))

        if message.audio_output is not None:
            message_dict["content"] = None
            message_dict["audio"] = {"id": message.audio_output.id}

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        if message.files is not None:
            # Ensure content is a list of parts
            content = message_dict.get("content")
            if isinstance(content, str):  # wrap existing text
                text = content
                message_dict["content"] = [{"type": "text", "text": text}]
            elif content is None:
                message_dict["content"] = []
            # Insert each file part before text parts
            for file in message.files:
                file_part = _format_file_for_message(file)
                if file_part:
                    message_dict["content"].insert(0, file_part)

        # Manually add the content field even if it is None
        if message.content is None:
            message_dict["content"] = None
        return message_dict

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        """
        Send a chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """

        try:
            if self._should_route_reasoning_through_responses_api():
                return self._build_openai_responses_model().invoke(
                    messages=self._messages_for_openai_responses_api(messages),
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            return self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.get_request_kwargs(response_format=response_format, tools=tools, tool_choice=tool_choice),
            )
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Optional[Message] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        """
        Sends an asynchronous chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.
            assistant_message (Optional[Message]): The assistant message for V2 compatibility.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        try:
            if self._should_route_reasoning_through_responses_api():
                # V2: Create assistant_message if not provided
                if assistant_message is None:
                    assistant_message = Message(role=self.assistant_message_role)
                return await self._build_openai_responses_model().ainvoke(
                    messages=self._messages_for_openai_responses_api(messages),
                    assistant_message=assistant_message,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            # Prepare shared inputs
            formatted_messages = [self._format_message(m) for m in messages]  # type: ignore
            request_kwargs = self.get_request_kwargs(
                response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            # Ensure at least one call, race N parallel calls and take the first success
            n_calls = max(1, int(self.redundant_calls or 1))

            # If adaptive redundancy is enabled, force n_calls to 1 for the initial logic
            # We handle the redundancy manually below.
            if self.adaptive_redundancy:
                n_calls = 1

            client = self.get_async_client()

            async def _do_call() -> ChatCompletion:
                return await client.chat.completions.create(
                    model=self.id,
                    messages=formatted_messages,
                    **request_kwargs,
                )

            if n_calls > 1:
                log_debug(f"Racing {n_calls} redundant calls")

            # Standard single call (non-adaptive, n_calls=1)
            if n_calls == 1 and not self.adaptive_redundancy:
                return await _do_call()

            async def _do_call_with_kwargs(idx: int, kwargs: Dict[str, Any]) -> tuple[int, ChatCompletion]:
                res = await client.chat.completions.create(
                    model=self.id,
                    messages=formatted_messages,
                    **kwargs,
                )
                return idx, res

            # ------------------------------------------------------------------
            # ADAPTIVE REDUNDANCY & GENERIC RACE
            # ------------------------------------------------------------------

            tasks: List[asyncio.Task] = []
            suffixes: Dict[int, str] = {}

            if self.adaptive_redundancy:
                # 1. Initialize State & Threshold
                self._init_adaptive_state()
                delay_threshold = self._get_adaptive_threshold()

                # 2. Prepare Call 1 (Sticky/Winner)
                if self.sticky_cache_state is None:
                    self.sticky_cache_state = {}

                current_winner = self.sticky_cache_state.get("suffix") or str(uuid4())
                self.sticky_cache_state["suffix"] = current_winner
                suffixes[0] = current_winner

                call1_kwargs = request_kwargs.copy()
                call1_kwargs["prompt_cache_key"] = f"{call1_kwargs.get('prompt_cache_key', '')}_{current_winner}"

                t1_start = perf_counter()
                t1 = asyncio.create_task(_do_call_with_kwargs(0, call1_kwargs))
                tasks.append(t1)

                srtt = self._current_adaptive_state.get("srtt", 0.0) if self._current_adaptive_state else 0.0
                rttvar = self._current_adaptive_state.get("rttvar", 0.0) if self._current_adaptive_state else 0.0

                log_debug(
                    f"Adaptive Redundancy [{self.adaptive_mode_id or 'local'}]: "
                    f"Threshold={delay_threshold:.3f}s (Mean={srtt:.3f}s, Dev={rttvar:.3f}s). Starting Call 1."
                )

                # 3. Wait for threshold or Call 1
                done_initial, _ = await asyncio.wait([t1], timeout=delay_threshold)

                if done_initial:
                    try:
                        idx, result = t1.result()
                        duration = perf_counter() - t1_start
                        self._update_adaptive_stats(duration)
                        log_debug(f"Adaptive Redundancy: Call 1 finished in {duration:.3f}s (Success)")
                        return result
                    except Exception:
                        log_warning(
                            f"Adaptive Redundancy [{self.adaptive_mode_id}]: Call 1 failed. Starting Call 2 immediately."
                        )
                else:
                    # Timeout exceeded
                    log_debug(
                        f"Adaptive Redundancy [{self.adaptive_mode_id}]: Threshold {delay_threshold:.3f}s exceeded. Triggering redundant Call 2."
                    )
                    if self._current_adaptive_state:
                        self._current_adaptive_state["triggered_calls"] = (
                            self._current_adaptive_state.get("triggered_calls", 0) + 1
                        )

                # Start Call 2 (Fresh) if we reached here
                fresh_suffix = str(uuid4())
                suffixes[1] = fresh_suffix

                call2_kwargs = request_kwargs.copy()
                call2_kwargs["prompt_cache_key"] = f"{call2_kwargs.get('prompt_cache_key', '')}_{fresh_suffix}"

                t2 = asyncio.create_task(_do_call_with_kwargs(1, call2_kwargs))
                tasks.append(t2)

            elif n_calls > 1:
                # Standard Redundant Logic
                if self.sticky_cache_state is None:
                    self.sticky_cache_state = {}

                current_winner = self.sticky_cache_state.get("suffix") or str(uuid4())
                self.sticky_cache_state["suffix"] = current_winner

                for i in range(n_calls):
                    call_kwargs = request_kwargs.copy()
                    suffix = current_winner if i == 0 else str(uuid4())
                    suffixes[i] = suffix
                    call_kwargs["prompt_cache_key"] = f"{call_kwargs.get('prompt_cache_key', '')}_{suffix}"
                    tasks.append(asyncio.create_task(_do_call_with_kwargs(i, call_kwargs)))
            else:
                # Fallback single call
                tasks.append(asyncio.create_task(_do_call_with_kwargs(0, request_kwargs)))

            last_exc: Optional[BaseException] = None
            _start_time = perf_counter()

            # Race Loop
            try:
                while tasks:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        try:
                            req_idx, result = t.result()

                            # Determine Duration
                            if self.adaptive_redundancy and req_idx == 0 and "t1_start" in locals():
                                duration = perf_counter() - t1_start
                            else:
                                duration = perf_counter() - _start_time

                            log_debug(f"Redundant call {req_idx} completed first in {duration:.3f}s")

                            # Update Adaptive Stats (if taking the slow path result)
                            if self.adaptive_redundancy:
                                if req_idx > 0 and self._current_adaptive_state is not None:
                                    self._current_adaptive_state["redundancy_wins"] = (
                                        self._current_adaptive_state.get("redundancy_wins", 0) + 1
                                    )
                                self._update_adaptive_stats(duration)

                            # Sticky Update
                            if self.sticky_cache_state is not None and req_idx > 0:
                                winning_suffix = suffixes.get(req_idx)
                                if winning_suffix:
                                    log_debug(f"Sticky Cache Update: Switching winner to {winning_suffix}")
                                    self.sticky_cache_state["suffix"] = winning_suffix

                            # Cancel pending
                            for p in pending:
                                p.cancel()
                            if pending:
                                await asyncio.gather(*pending, return_exceptions=True)
                            return result
                        except (RateLimitError, APIConnectionError, APIStatusError) as e:
                            last_exc = e
                            log_warning(f"OpenAI redundant call failed, trying next: {e}")
                            continue
                        except Exception as e:
                            last_exc = e
                            log_warning(f"OpenAI redundant call unexpected error, trying next: {e}")
                            continue
                    tasks = list(pending)
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            if last_exc:
                raise last_exc
            raise RuntimeError("All redundant OpenAI calls failed without exception.")

            if last_exc:
                raise last_exc
            raise RuntimeError("All redundant OpenAI calls failed without exception.")
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[ChatCompletionChunk]:
        """
        Send a streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatCompletionChunk]: An iterator of chat completion chunks.
        """

        try:
            if self._should_route_reasoning_through_responses_api():
                yield from self._build_openai_responses_model().invoke_stream(
                    messages=self._messages_for_openai_responses_api(messages),
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                return
            yield from self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                stream_options={"include_usage": True},
                **self.get_request_kwargs(response_format=response_format, tools=tools, tool_choice=tool_choice),
            )  # type: ignore
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Optional[Message] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """
        Sends an asynchronous streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.
            assistant_message (Optional[Message]): The assistant message for V2 compatibility.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """

        try:
            if self._should_route_reasoning_through_responses_api():
                # V2: Create assistant_message if not provided
                if assistant_message is None:
                    assistant_message = Message(role=self.assistant_message_role)
                async for chunk in self._build_openai_responses_model().ainvoke_stream(
                    messages=self._messages_for_openai_responses_api(messages),
                    assistant_message=assistant_message,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                ):
                    yield chunk
                return
            async_stream = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                stream_options={"include_usage": True},
                **self.get_request_kwargs(response_format=response_format, tools=tools, tool_choice=tool_choice),
            )
            async for chunk in async_stream:
                yield chunk
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
            try:
                error_message = e.response.json().get("error", {})
            except Exception:
                error_message = e.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def process_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[ModelResponse]:
        if self._should_route_reasoning_through_responses_api():
            yield from self._build_openai_responses_model().process_response_stream(
                messages=self._messages_for_openai_responses_api(messages),
                assistant_message=assistant_message,
                stream_data=stream_data,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice or self._tool_choice,
            )
            return
        yield from super().process_response_stream(
            messages=messages,
            assistant_message=assistant_message,
            stream_data=stream_data,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )

    async def aprocess_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[ModelResponse]:
        if self._should_route_reasoning_through_responses_api():
            async for mr in self._build_openai_responses_model().aprocess_response_stream(
                messages=self._messages_for_openai_responses_api(messages),
                assistant_message=assistant_message,
                stream_data=stream_data,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice or self._tool_choice,
            ):
                yield mr
            return
        async for mr in super().aprocess_response_stream(
            messages=messages,
            assistant_message=assistant_message,
            stream_data=stream_data,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        ):
            yield mr

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[Any]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data: Chat completion deltas or already-shaped dicts (Responses API).

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        if not tool_calls_data:
            return []
        if isinstance(tool_calls_data[0], dict):
            out = list(tool_calls_data)
            for entry in out:
                if isinstance(entry, dict) and entry.get("id") is not None and entry.get("call_id") is None:
                    entry["call_id"] = entry["id"]
            return out
        tool_calls: List[Dict[str, Any]] = []
        for _tool_call in tool_calls_data:
            _index = _tool_call.index or 0
            _tool_call_id = _tool_call.id
            _tool_call_type = _tool_call.type
            _function_name = _tool_call.function.name if _tool_call.function else None
            _function_arguments = _tool_call.function.arguments if _tool_call.function else None

            if len(tool_calls) <= _index:
                tool_calls.extend([{}] * (_index - len(tool_calls) + 1))
            tool_call_entry = tool_calls[_index]
            if not tool_call_entry:
                tool_call_entry["id"] = _tool_call_id
                tool_call_entry["type"] = _tool_call_type
                tool_call_entry["function"] = {
                    "name": _function_name or "",
                    "arguments": _function_arguments or "",
                }
            else:
                if _function_name:
                    tool_call_entry["function"]["name"] += _function_name
                if _function_arguments:
                    tool_call_entry["function"]["arguments"] += _function_arguments
                if _tool_call_id:
                    tool_call_entry["id"] = _tool_call_id
                if _tool_call_type:
                    tool_call_entry["type"] = _tool_call_type
        for entry in tool_calls:
            if entry.get("id") is not None and entry.get("call_id") is None:
                entry["call_id"] = entry["id"]
        return tool_calls

    def parse_provider_response(
        self,
        response: Union[ChatCompletion, Response],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.
        """
        # V2: If already a ModelResponse, return it directly
        if isinstance(response, ModelResponse):
            return response

        if isinstance(response, Response):
            return self._build_openai_responses_model().parse_provider_response(
                response, response_format=response_format
            )

        model_response = ModelResponse()

        if hasattr(response, "error") and response.error:
            raise ModelProviderError(
                message=response.error.get("message", "Unknown model error"),
                model_name=self.name,
                model_id=self.id,
            )

        # Get response message - check if response has choices attribute
        if not hasattr(response, "choices") or not response.choices:
            log_error(f"Invalid response object: {type(response)}, expected ChatCompletion with choices")
            raise ModelProviderError(
                message="Invalid response format - missing choices",
                model_name=self.name,
                model_id=self.id,
            )

        response_message = response.choices[0].message

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                log_warning(f"Error processing tool calls: {e}")

        # Add audio transcript to content if available
        response_audio: Optional[ChatCompletionAudio] = response_message.audio
        if response_audio and response_audio.transcript and not model_response.content:
            model_response.content = response_audio.transcript

        # Add audio if present
        if hasattr(response_message, "audio") and response_message.audio is not None:
            # If the audio output modality is requested, we can extract an audio response
            try:
                if isinstance(response_message.audio, dict):
                    model_response.audio = AudioResponse(
                        id=response_message.audio.get("id"),
                        content=response_message.audio.get("data"),
                        expires_at=response_message.audio.get("expires_at"),
                        transcript=response_message.audio.get("transcript"),
                    )
                else:
                    model_response.audio = AudioResponse(
                        id=response_message.audio.id,
                        content=response_message.audio.data,
                        expires_at=response_message.audio.expires_at,
                        transcript=response_message.audio.transcript,
                    )
            except Exception as e:
                log_warning(f"Error processing audio: {e}")

        if hasattr(response_message, "reasoning_content") and response_message.reasoning_content is not None:
            model_response.reasoning_content = response_message.reasoning_content

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from OpenAI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()
        if response_delta.choices and len(response_delta.choices) > 0:
            delta: ChoiceDelta = response_delta.choices[0].delta

            # Add content
            if delta.content is not None:
                model_response.content = delta.content

            # Add tool calls
            if delta.tool_calls is not None:
                model_response.tool_calls = delta.tool_calls  # type: ignore

            # Add audio if present
            if hasattr(delta, "audio") and delta.audio is not None:
                try:
                    if isinstance(delta.audio, dict):
                        model_response.audio = AudioResponse(
                            id=delta.audio.get("id"),
                            content=delta.audio.get("data"),
                            expires_at=delta.audio.get("expires_at"),
                            transcript=delta.audio.get("transcript"),
                            sample_rate=24000,
                            mime_type="pcm16",
                        )
                    else:
                        model_response.audio = AudioResponse(
                            id=delta.audio.id,
                            content=delta.audio.data,
                            expires_at=delta.audio.expires_at,
                            transcript=delta.audio.transcript,
                            sample_rate=24000,
                            mime_type="pcm16",
                        )
                except Exception as e:
                    log_warning(f"Error processing audio: {e}")

        # Add usage metrics if present
        if response_delta.usage is not None:
            model_response.response_usage = response_delta.usage

        return model_response

    def _init_adaptive_state(self):
        """Initialize or retrieve adaptive state from registry."""
        if self.adaptive_mode_id and self._current_adaptive_state is None:
            if self.adaptive_mode_id not in self._adaptive_delay_registry:
                self._adaptive_delay_registry[self.adaptive_mode_id] = {
                    "srtt": self.adaptive_redundancy_initial_delay,
                    "rttvar": self.adaptive_redundancy_initial_delay / 2,
                    "total_calls": 0,
                    "triggered_calls": 0,
                    "redundancy_wins": 0,
                }
            self._current_adaptive_state = self._adaptive_delay_registry.get(self.adaptive_mode_id)

    def _get_adaptive_threshold(self) -> float:
        """Calculate current delay threshold: SRTT + (K * RTTVAR)."""
        if self._current_adaptive_state:
            srtt = self._current_adaptive_state.get("srtt", self.adaptive_redundancy_initial_delay)
            rttvar = self._current_adaptive_state.get("rttvar", 0.0)
            return srtt + (self.adaptive_redundancy_trace_factor * rttvar)
        return self.adaptive_redundancy_initial_delay

    def _update_adaptive_stats(self, duration: float):
        """Update Jacobson's stats and log trigger rate."""
        if self._current_adaptive_state:
            # Update Total Calls
            self._current_adaptive_state["total_calls"] = self._current_adaptive_state.get("total_calls", 0) + 1

            # Jacobson's Algorithm
            srtt = self._current_adaptive_state.get("srtt", self.adaptive_redundancy_initial_delay)
            rttvar = self._current_adaptive_state.get("rttvar", 0.0)

            err = duration - srtt
            self._current_adaptive_state["srtt"] = srtt + 0.125 * err
            self._current_adaptive_state["rttvar"] = rttvar + 0.25 * (abs(err) - rttvar)

            # Trigger Rates
            total = self._current_adaptive_state.get("total_calls", 1)
            triggered = self._current_adaptive_state.get("triggered_calls", 0)
            wins = self._current_adaptive_state.get("redundancy_wins", 0)

            trigger_rate = (triggered / total) * 100 if total > 0 else 0.0
            win_rate = (wins / triggered) * 100 if triggered > 0 else 0.0

            log_debug(
                f"Adaptive Stats [{self.adaptive_mode_id or 'local'}]: "
                f"Mean={self._current_adaptive_state['srtt']:.3f}s, Dev={self._current_adaptive_state['rttvar']:.3f}s, "
                f"Triggered: {trigger_rate:.1f}% ({triggered}/{total}), "
                f"Wins: {win_rate:.1f}% ({wins}/{triggered})"
            )
