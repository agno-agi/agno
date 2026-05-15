"""
Gemini Interactions model class.

Uses Google's Interactions API for server-side conversation history management,
typed execution steps, and efficient multi-turn conversations.

Requires `google-genai>=2.0.0`.
"""

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Literal, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Audio, Image
from agno.models.base import Model
from agno.models.google.utils import media_to_content_item
from agno.models.message import Citations, Message, UrlCitation
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.gemini import inject_agno_client_header
from agno.utils.log import log_debug, log_error, log_warning

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai._interactions import types as interaction_types
    from google.genai._interactions.types.function_call_step import FunctionCallStep
    from google.genai._interactions.types.model_output_step import ModelOutputStep
    from google.genai._interactions.types.step_delta import (
        DeltaArgumentsDelta,
        DeltaText,
        DeltaThoughtSignature,
        DeltaThoughtSummary,
    )
    from google.genai._interactions.types.text_content import TextContent
    from google.genai._interactions.types.thought_step import ThoughtStep
except ImportError:
    raise ImportError(
        "`google-genai` not installed or not at the latest version. "
        "Please install it using `pip install -U google-genai`"
    )

# Lazy imports for content types used in output parsing
try:
    from google.genai._interactions.types.audio_content import AudioContent
    from google.genai._interactions.types.image_content import ImageContent
except ImportError:
    AudioContent = None  # type: ignore[assignment, misc]
    ImageContent = None  # type: ignore[assignment, misc]


@dataclass
class GeminiInteractions(Model):
    """
    Gemini model using the Interactions API.

    The Interactions API provides server-side conversation history management.
    Instead of resending all messages each turn, you reference a `previous_interaction_id`
    and only send new input. This reduces token costs, improves latency via implicit caching,
    and provides typed execution steps for better observability.

    Key benefits over the standard generateContent API:
    - Server-side conversation history (only send new messages each turn)
    - Implicit caching of prior turns
    - Typed execution steps (text, function_call, thought, etc.)
    - Background execution support for long-running tasks

    Note: The Interactions API is experimental, requires a Gemini API key,
    and is not available on Vertex AI.

    Example:
        ```python
        from agno.agent import Agent
        from agno.models.google import GeminiInteractions

        agent = Agent(
            model=GeminiInteractions(id="gemini-3-flash-preview"),
            markdown=True,
        )
        agent.print_response("Hello!")
        ```
    """

    id: str = "gemini-3-flash-preview"
    name: str = "GeminiInteractions"
    provider: str = "Google"

    supports_native_structured_outputs: bool = True

    # Generation parameters (must match GenerationConfigParam in the SDK)
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    seed: Optional[int] = None
    response_modalities: Optional[list[str]] = None

    # Interactions API specific parameters
    store: Optional[bool] = None  # Whether to persist interactions server-side (default: True)

    # Thinking configuration
    thinking_level: Optional[Literal["minimal", "low", "medium", "high"]] = None

    # Built-in tools
    search: bool = False
    url_context: bool = False
    code_execution: bool = False

    # Inference tier: "flex" (lower cost, higher latency), "standard", or "priority" (lowest latency)
    service_tier: Optional[Literal["flex", "standard", "priority"]] = None

    # Timeout in seconds
    timeout: Optional[float] = None

    # Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Client instance
    client: Optional[GeminiClient] = None

    def _get_previous_interaction_id(self, messages: List[Message]) -> Optional[str]:
        """Extract the previous interaction ID from message provider_data.

        Walks messages in reverse to find the most recent assistant message
        with an interaction_id. This avoids storing state at instance level,
        which would be unsafe if two concurrent agents share the same model.
        """
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.provider_data:
                iid = msg.provider_data.get("interaction_id")
                if iid:
                    return iid
        return None

    def get_client(self) -> GeminiClient:
        """Returns an instance of the GeminiClient.

        Note: The Interactions API requires a Gemini API key and is not available on Vertex AI.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("GOOGLE_API_KEY")
        if not self.api_key:
            log_error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")
        client_params["api_key"] = self.api_key

        if self.timeout is not None:
            http_options = client_params.get("http_options", {})
            if isinstance(http_options, dict):
                http_options["timeout"] = int(self.timeout * 1000)
                client_params["http_options"] = http_options

        if self.client_params:
            client_params.update(self.client_params)

        client_params = inject_agno_client_header(client_params)

        self.client = genai.Client(**client_params)
        return self.client

    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a dictionary."""
        model_dict = super().to_dict()
        model_dict.update(
            {
                "search": self.search,
                "url_context": self.url_context,
                "code_execution": self.code_execution,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_output_tokens": self.max_output_tokens,
                "stop_sequences": self.stop_sequences,
                "seed": self.seed,
                "response_modalities": self.response_modalities,
                "thinking_level": self.thinking_level,
                "store": self.store,
                "service_tier": self.service_tier,
            }
        )
        return {k: v for k, v in model_dict.items() if v is not None}

    def _format_tools(self, tools: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Format tools for the Interactions API.

        The Interactions API uses a flat list of tool definitions with a `type` discriminator.
        Functions use `{"type": "function", "name": ..., "description": ..., "parameters": ...}`.

        This method receives raw tool objects (Function instances or dicts) from the base class,
        converts them to the Interactions API format.
        """
        from agno.tools.function import Function

        formatted_tools: List[Dict[str, Any]] = []

        if tools:
            for tool in tools:
                # Convert Function objects to Interactions API format
                if isinstance(tool, Function):
                    func = tool.to_dict()
                    formatted_tools.append(
                        {
                            "type": "function",
                            "name": func.get("name"),
                            "description": func.get("description"),
                            "parameters": func.get("parameters"),
                        }
                    )
                elif isinstance(tool, dict):
                    if tool.get("type") == "function":
                        func = tool.get("function", {})
                        formatted_tools.append(
                            {
                                "type": "function",
                                "name": func.get("name"),
                                "description": func.get("description"),
                                "parameters": func.get("parameters"),
                            }
                        )
                    else:
                        # Pass through other dict-based tools (builtins)
                        formatted_tools.append(tool)

        return formatted_tools

    def _build_input(self, messages: List[Message]) -> Union[str, List[Dict[str, Any]]]:
        """Build the input steps for the Interactions API.

        The v2.x SDK uses a step_list format:
        - UserInputStep: {"type": "user_input", "content": [{"type": "text", "text": "..."}, ...]}
        - FunctionCallStep: {"type": "function_call", "id": "...", "name": "...", "arguments": {...}}
        - FunctionResultStep: {"type": "function_result", "call_id": "...", "result": "...", "name": "..."}

        Content items within a UserInputStep can be:
        - TextContentParam: {"type": "text", "text": "..."}
        - ImageContentParam: {"type": "image", "data": base64, "mime_type": "image/jpeg"}
        - AudioContentParam: {"type": "audio", "data": base64, "mime_type": "audio/wav"}
        - VideoContentParam: {"type": "video", "data": base64, "mime_type": "video/mp4"}
        - DocumentContentParam: {"type": "document", "data": base64, "mime_type": "application/pdf"}
        """
        steps: List[Dict[str, Any]] = []

        for message in messages:
            if message.role == "system":
                # System messages are passed via system_instruction param, skip here
                continue

            # User messages become UserInputStep
            if message.role == "user":
                content_items: List[Dict[str, Any]] = []

                # Text content
                if message.content and isinstance(message.content, str):
                    content_items.append({"type": "text", "text": message.content})

                # Image inputs
                if message.images:
                    for image in message.images:
                        item = media_to_content_item(image, "image", "image/jpeg")
                        if item:
                            content_items.append(item)

                # Audio inputs
                if message.audio:
                    for audio in message.audio:
                        item = media_to_content_item(audio, "audio", "audio/wav")
                        if item:
                            content_items.append(item)

                # Video inputs
                if message.videos:
                    for video in message.videos:
                        item = media_to_content_item(video, "video", "video/mp4")
                        if item:
                            content_items.append(item)

                # File/document inputs
                if message.files:
                    for file in message.files:
                        item = media_to_content_item(file, "document", "application/pdf")
                        if item:
                            content_items.append(item)

                if content_items:
                    steps.append({"type": "user_input", "content": content_items})
                else:
                    log_warning("Skipping user message with no usable content (all media may have failed to load)")

            # Assistant messages with tool calls become FunctionCallSteps
            elif message.role == "assistant":
                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        func = tool_call.get("function", {})
                        args = func.get("arguments", "{}")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        steps.append(
                            {
                                "type": "function_call",
                                "id": tool_call.get("id", str(uuid4())),
                                "name": func.get("name", ""),
                                "arguments": args,
                            }
                        )

            # Tool result messages become FunctionResultSteps
            elif message.role == "tool" and message.tool_call_id:
                steps.append(
                    {
                        "type": "function_result",
                        "call_id": message.tool_call_id,
                        "name": message.tool_name or "",
                        "result": message.content or "",
                    }
                )

        return steps

    def _get_request_kwargs(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Dict[str, Any]:
        """Build keyword arguments for interactions.create()."""
        kwargs: Dict[str, Any] = {
            "model": self.id,
        }

        # Build input from messages
        input_turns = self._build_input(messages)
        kwargs["input"] = input_turns

        # System instruction from the last system message (consistent with gemini.py)
        system_message = None
        for msg in messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_message = msg.content
        if system_message:
            kwargs["system_instruction"] = system_message

        # Previous interaction for multi-turn (read from message provider_data)
        previous_interaction_id = self._get_previous_interaction_id(messages)
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id

        # Generation config (only params supported by the Interactions API SDK)
        generation_config: Dict[str, Any] = {}
        if self.temperature is not None:
            generation_config["temperature"] = self.temperature
        if self.top_p is not None:
            generation_config["top_p"] = self.top_p
        if self.max_output_tokens is not None:
            generation_config["max_output_tokens"] = self.max_output_tokens
        if self.stop_sequences is not None:
            generation_config["stop_sequences"] = self.stop_sequences
        if self.seed is not None:
            generation_config["seed"] = self.seed
        if self.thinking_level is not None:
            generation_config["thinking_level"] = self.thinking_level
        if generation_config:
            kwargs["generation_config"] = generation_config

        # Response modalities
        if self.response_modalities:
            kwargs["response_modalities"] = self.response_modalities

        # Response format (structured output)
        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                # Pydantic model -> TextResponseFormatParam with JSON schema
                kwargs["response_format"] = {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_format.model_json_schema(),
                }
            elif isinstance(response_format, dict):
                # Raw dict passed through (could be TextResponseFormatParam, etc.)
                kwargs["response_format"] = response_format

        # Tools - already formatted by _format_tools() via the base class before invoke() is called
        # Add built-in tools that are model-specific (not from the agent's tool list)
        all_tools = list(tools) if tools else []
        if self.search:
            all_tools.append({"type": "google_search"})
        if self.url_context:
            all_tools.append({"type": "url_context"})
        if self.code_execution:
            all_tools.append({"type": "code_execution"})
        if all_tools:
            kwargs["tools"] = all_tools

        # Service tier (flex/standard/priority)
        if self.service_tier is not None:
            kwargs["service_tier"] = self.service_tier

        # Store
        if self.store is not None:
            kwargs["store"] = self.store

        return kwargs

    def _parse_image_content(self, content_item: Any) -> Optional[Image]:
        """Parse an ImageContent response item into an Agno Image."""
        image_data = getattr(content_item, "data", None)
        mime_type = getattr(content_item, "mime_type", None) or "image/png"

        if image_data:
            try:
                content_bytes = base64.b64decode(image_data)
            except Exception as e:
                log_warning(f"Failed to decode image data from model response: {e}")
                return None
            return Image(content=content_bytes, mime_type=mime_type, id=str(uuid4()))

        uri = getattr(content_item, "uri", None)
        if uri:
            return Image(url=uri, mime_type=mime_type, id=str(uuid4()))

        return None

    def _parse_audio_content(self, content_item: Any) -> Optional[Audio]:
        """Parse an AudioContent response item into an Agno Audio."""
        audio_data = getattr(content_item, "data", None)
        mime_type = getattr(content_item, "mime_type", None) or "audio/wav"

        if audio_data:
            try:
                content_bytes = base64.b64decode(audio_data)
            except Exception as e:
                log_warning(f"Failed to decode audio data from model response: {e}")
                return None
            return Audio(content=content_bytes, mime_type=mime_type, id=str(uuid4()))

        uri = getattr(content_item, "uri", None)
        if uri:
            return Audio(url=uri, mime_type=mime_type, id=str(uuid4()))

        return None

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        """Parse an Interaction response into a ModelResponse."""
        model_response = ModelResponse()
        model_response.role = "assistant"

        interaction_id = getattr(response, "id", None)

        steps = getattr(response, "steps", None)
        if not steps:
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["interaction_id"] = interaction_id
            return model_response

        for step in steps:
            if isinstance(step, ModelOutputStep):
                if step.content:
                    for content_item in step.content:
                        if isinstance(content_item, TextContent):
                            text = content_item.text or ""
                            if model_response.content is None:
                                model_response.content = text
                            else:
                                model_response.content += text
                            # Extract citations from annotations
                            annotations = getattr(content_item, "annotations", None)
                            if annotations:
                                for annotation in annotations:
                                    ann_type = getattr(annotation, "type", None)
                                    if ann_type == "url_citation":
                                        if model_response.citations is None:
                                            model_response.citations = Citations(raw=[], urls=[])
                                        if model_response.citations.raw is None:
                                            model_response.citations.raw = []
                                        model_response.citations.raw.append(annotation)
                                        if model_response.citations.urls is None:
                                            model_response.citations.urls = []
                                        model_response.citations.urls.append(
                                            UrlCitation(
                                                url=getattr(annotation, "url", None),
                                                title=getattr(annotation, "title", None),
                                            )
                                        )
                        elif ImageContent is not None and isinstance(content_item, ImageContent):
                            image = self._parse_image_content(content_item)
                            if image:
                                if model_response.images is None:
                                    model_response.images = []
                                model_response.images.append(image)
                        elif AudioContent is not None and isinstance(content_item, AudioContent):
                            audio = self._parse_audio_content(content_item)
                            if audio:
                                model_response.audio = audio

            elif isinstance(step, ThoughtStep):
                if step.summary:
                    for summary_item in step.summary:
                        if isinstance(summary_item, TextContent):
                            text = summary_item.text or ""
                            if text:
                                if model_response.reasoning_content is None:
                                    model_response.reasoning_content = text
                                else:
                                    model_response.reasoning_content += text
                if step.signature:
                    if model_response.provider_data is None:
                        model_response.provider_data = {}
                    model_response.provider_data["thought_signature"] = step.signature

            elif isinstance(step, FunctionCallStep):
                args = step.arguments
                if isinstance(args, dict):
                    args_str = json.dumps(args)
                elif args is not None:
                    args_str = str(args)
                else:
                    args_str = ""

                tool_call = {
                    "id": step.id or str(uuid4()),
                    "type": "function",
                    "function": {
                        "name": step.name or "",
                        "arguments": args_str,
                    },
                }
                if step.signature:
                    tool_call["thought_signature"] = step.signature
                model_response.tool_calls.append(tool_call)

        # Parse usage metrics
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            model_response.response_usage = MessageMetrics(
                input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
                output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "total_cached_tokens", 0) or 0,
                reasoning_tokens=getattr(usage, "total_thought_tokens", 0) or 0,
            )

        if model_response.provider_data is None:
            model_response.provider_data = {}
        model_response.provider_data["interaction_id"] = interaction_id

        return model_response

    def _parse_provider_response_delta(
        self, stream_event: Any, assistant_message: Message, stream_state: Dict[str, Any]
    ) -> tuple[ModelResponse, Dict[str, Any]]:
        """Parse a streaming event from the Interactions API into a ModelResponse.

        Args:
            stream_event: A streaming event from the Interactions API.
            assistant_message: The assistant message being built (for metrics).
            stream_state: Mutable state dict tracking pending tool calls across events.
                Keys: "pending_calls" (Dict[int, Dict]) keyed by step index.

        Returns:
            Tuple of (ModelResponse, updated stream_state).
        """
        model_response = ModelResponse()

        if isinstance(stream_event, interaction_types.InteractionCreatedEvent):
            if stream_event.interaction and hasattr(stream_event.interaction, "id"):
                model_response.provider_data = {"interaction_id": stream_event.interaction.id}
            model_response.role = "assistant"

        elif isinstance(stream_event, interaction_types.StepDelta):
            delta = stream_event.delta
            if isinstance(delta, DeltaText):
                model_response.content = delta.text or ""
            elif isinstance(delta, DeltaThoughtSummary):
                summary_content = getattr(delta, "content", None)
                if summary_content and isinstance(summary_content, TextContent):
                    model_response.reasoning_content = summary_content.text or ""
            elif isinstance(delta, DeltaThoughtSignature):
                if delta.signature:
                    model_response.provider_data = {"thought_signature": delta.signature}
            elif isinstance(delta, DeltaArgumentsDelta):
                idx = stream_event.index
                if delta.arguments and idx in stream_state["pending_calls"]:
                    stream_state["pending_calls"][idx]["args_buffer"] += delta.arguments

        elif isinstance(stream_event, interaction_types.StepStart):
            step = stream_event.step
            if isinstance(step, FunctionCallStep):
                idx = stream_event.index
                tool_call = {
                    "id": step.id or str(uuid4()),
                    "type": "function",
                    "function": {
                        "name": step.name or "",
                        "arguments": "",
                    },
                }
                if step.signature:
                    tool_call["thought_signature"] = step.signature
                args = step.arguments
                args_buffer = json.dumps(args) if isinstance(args, dict) and args else ""
                stream_state["pending_calls"][idx] = {"tool_call": tool_call, "args_buffer": args_buffer}

        elif isinstance(stream_event, interaction_types.StepStop):
            idx = stream_event.index
            pending = stream_state["pending_calls"].pop(idx, None)
            if pending is not None:
                pending["tool_call"]["function"]["arguments"] = pending["args_buffer"] or "{}"
                model_response.tool_calls.append(pending["tool_call"])

        elif isinstance(stream_event, interaction_types.InteractionCompletedEvent):
            if stream_event.interaction:
                if hasattr(stream_event.interaction, "usage") and stream_event.interaction.usage:
                    usage = stream_event.interaction.usage
                    model_response.response_usage = MessageMetrics(
                        input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
                        total_tokens=getattr(usage, "total_tokens", 0) or 0,
                        cache_read_tokens=getattr(usage, "total_cached_tokens", 0) or 0,
                        reasoning_tokens=getattr(usage, "total_thought_tokens", 0) or 0,
                    )
                if hasattr(stream_event.interaction, "id") and stream_event.interaction.id:
                    if model_response.provider_data is None:
                        model_response.provider_data = {}
                    model_response.provider_data["interaction_id"] = stream_event.interaction.id

        return model_response, stream_state

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
        retry_with_guidance: bool = False,
    ) -> ModelResponse:
        """Invoke the model using the Interactions API."""
        request_kwargs = self._get_request_kwargs(messages, tools=tools, response_format=response_format)
        log_debug(f"Calling Gemini Interactions API with params: {list(request_kwargs.keys())}", log_level=2)

        try:
            assistant_message.metrics.start_timer()
            interaction = self.get_client().interactions.create(**request_kwargs)
            assistant_message.metrics.stop_timer()

            return self._parse_provider_response(interaction)

        except Exception as e:
            log_error(f"Error from Gemini Interactions API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
        retry_with_guidance: bool = False,
    ) -> Iterator[ModelResponse]:
        """Invoke the model with streaming using the Interactions API."""
        request_kwargs = self._get_request_kwargs(messages, tools=tools, response_format=response_format)
        request_kwargs["stream"] = True
        log_debug(f"Calling Gemini Interactions API (stream) with params: {list(request_kwargs.keys())}", log_level=2)

        try:
            assistant_message.metrics.start_timer()
            stream = self.get_client().interactions.create(**request_kwargs)
            stream_state: Dict[str, Any] = {"pending_calls": {}}

            for event in stream:
                model_response, stream_state = self._parse_provider_response_delta(
                    stream_event=event, assistant_message=assistant_message, stream_state=stream_state
                )
                yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error from Gemini Interactions API (stream): {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
        retry_with_guidance: bool = False,
    ) -> ModelResponse:
        """Async invoke the model using the Interactions API."""
        request_kwargs = self._get_request_kwargs(messages, tools=tools, response_format=response_format)
        log_debug(f"Calling Gemini Interactions API (async) with params: {list(request_kwargs.keys())}", log_level=2)

        try:
            assistant_message.metrics.start_timer()
            interaction = await self.get_client().aio.interactions.create(**request_kwargs)
            assistant_message.metrics.stop_timer()

            return self._parse_provider_response(interaction)

        except Exception as e:
            log_error(f"Error from Gemini Interactions API (async): {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
        retry_with_guidance: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """Async streaming invoke using the Interactions API."""
        request_kwargs = self._get_request_kwargs(messages, tools=tools, response_format=response_format)
        request_kwargs["stream"] = True
        log_debug(
            f"Calling Gemini Interactions API (async stream) with params: {list(request_kwargs.keys())}", log_level=2
        )

        try:
            assistant_message.metrics.start_timer()
            stream = await self.get_client().aio.interactions.create(**request_kwargs)
            stream_state: Dict[str, Any] = {"pending_calls": {}}

            async for event in stream:
                model_response, stream_state = self._parse_provider_response_delta(
                    stream_event=event, assistant_message=assistant_message, stream_state=stream_state
                )
                yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error from Gemini Interactions API (async stream): {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
