"""
Gemini Interactions model class.

Uses Google's Interactions API for server-side conversation history management,
typed execution steps, and efficient multi-turn conversations.

Requires `google-genai>=2.0.0`.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.gemini import inject_agno_client_header
from agno.utils.log import log_debug, log_error, log_info

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
    from google.oauth2.service_account import Credentials
except ImportError:
    raise ImportError(
        "`google-genai` not installed or not at the latest version. "
        "Please install it using `pip install -U google-genai`"
    )


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

    Note: The Interactions API is experimental and may change in future versions.

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

    # Generation parameters
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    response_modalities: Optional[list[str]] = None

    # Interactions API specific parameters
    store: Optional[bool] = None  # Whether to persist interactions server-side (default: True)
    background: Optional[bool] = None  # Offload to background execution

    # Thinking configuration
    thinking_budget: Optional[int] = None
    include_thoughts: Optional[bool] = None
    thinking_level: Optional[str] = None  # "low", "high"

    # Built-in tools
    search: bool = False
    url_context: bool = False

    # Timeout in seconds
    timeout: Optional[float] = None

    # Cumulative token counts in streaming
    collect_metrics_on_completion: bool = True

    # Client parameters
    credentials: Optional[Credentials] = None
    api_key: Optional[str] = None
    vertexai: bool = False
    project_id: Optional[str] = None
    location: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Client instance
    client: Optional[GeminiClient] = None

    # Track interaction ID for multi-turn conversations
    _previous_interaction_id: Optional[str] = field(default=None, init=False, repr=False)

    def get_client(self) -> GeminiClient:
        """Returns an instance of the GeminiClient."""
        if self.client:
            return self.client

        client_params: Dict[str, Any] = {}
        vertexai = self.vertexai or getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"

        if not vertexai:
            self.api_key = self.api_key or getenv("GOOGLE_API_KEY")
            if not self.api_key:
                log_error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")
            client_params["api_key"] = self.api_key
        else:
            log_info("Using Vertex AI API")
            client_params["vertexai"] = True
            project_id = self.project_id or getenv("GOOGLE_CLOUD_PROJECT")
            if not project_id:
                log_error("GOOGLE_CLOUD_PROJECT not set. Please set the GOOGLE_CLOUD_PROJECT environment variable.")
            location = self.location or getenv("GOOGLE_CLOUD_LOCATION")
            if not location:
                log_error("GOOGLE_CLOUD_LOCATION not set. Please set the GOOGLE_CLOUD_LOCATION environment variable.")
            client_params["project"] = project_id
            client_params["location"] = location
            if self.credentials:
                client_params["credentials"] = self.credentials

        client_params = {k: v for k, v in client_params.items() if v is not None}

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
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "max_output_tokens": self.max_output_tokens,
                "stop_sequences": self.stop_sequences,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "seed": self.seed,
                "response_modalities": self.response_modalities,
                "thinking_budget": self.thinking_budget,
                "include_thoughts": self.include_thoughts,
                "thinking_level": self.thinking_level,
                "store": self.store,
                "background": self.background,
                "vertexai": self.vertexai,
                "project_id": self.project_id,
                "location": self.location,
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
        - UserInputStep: {"type": "user_input", "content": [{"type": "text", "text": "..."}]}
        - FunctionCallStep: {"type": "function_call", "id": "...", "name": "...", "arguments": {...}}
        - FunctionResultStep: {"type": "function_result", "call_id": "...", "result": "...", "name": "..."}
        """
        steps: List[Dict[str, Any]] = []

        for message in messages:
            if message.role == "system":
                # System messages are passed via system_instruction param, skip here
                continue

            # User messages become UserInputStep
            if message.role == "user":
                content_items: List[Dict[str, Any]] = []
                if message.content and isinstance(message.content, str):
                    content_items.append({"type": "text", "text": message.content})
                if content_items:
                    steps.append({"type": "user_input", "content": content_items})

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

        # System instruction from the first system message
        system_message = None
        for msg in messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_message = msg.content
                break
        if system_message:
            kwargs["system_instruction"] = system_message

        # Previous interaction for multi-turn
        if self._previous_interaction_id:
            kwargs["previous_interaction_id"] = self._previous_interaction_id

        # Generation config
        generation_config: Dict[str, Any] = {}
        if self.temperature is not None:
            generation_config["temperature"] = self.temperature
        if self.top_p is not None:
            generation_config["top_p"] = self.top_p
        if self.top_k is not None:
            generation_config["top_k"] = self.top_k
        if self.max_output_tokens is not None:
            generation_config["max_output_tokens"] = self.max_output_tokens
        if self.stop_sequences is not None:
            generation_config["stop_sequences"] = self.stop_sequences
        if self.presence_penalty is not None:
            generation_config["presence_penalty"] = self.presence_penalty
        if self.frequency_penalty is not None:
            generation_config["frequency_penalty"] = self.frequency_penalty
        if self.seed is not None:
            generation_config["seed"] = self.seed
        if self.thinking_budget is not None:
            generation_config["thinking_budget"] = self.thinking_budget
        if self.thinking_level is not None:
            generation_config["thinking_level"] = self.thinking_level
        if generation_config:
            kwargs["generation_config"] = generation_config

        # Response modalities
        if self.response_modalities:
            kwargs["response_modalities"] = self.response_modalities

        # Response format
        if response_format is not None and isinstance(response_format, type) and issubclass(response_format, BaseModel):
            kwargs["response_format"] = response_format.model_json_schema()
            kwargs["response_mime_type"] = "application/json"

        # Tools - already formatted by _format_tools() via the base class before invoke() is called
        # Add built-in tools that are model-specific (not from the agent's tool list)
        all_tools = list(tools) if tools else []
        if self.search:
            all_tools.append({"type": "google_search"})
        if self.url_context:
            all_tools.append({"type": "url_context"})
        if all_tools:
            kwargs["tools"] = all_tools

        # Store and background
        if self.store is not None:
            kwargs["store"] = self.store
        if self.background is not None:
            kwargs["background"] = self.background

        return kwargs

    def _parse_interaction_response(self, interaction: Any) -> ModelResponse:
        """Parse an Interaction response into a ModelResponse."""
        model_response = ModelResponse()
        model_response.role = "assistant"

        # Track the interaction ID for multi-turn
        if hasattr(interaction, "id") and interaction.id:
            self._previous_interaction_id = interaction.id

        # Parse steps from the interaction
        steps = getattr(interaction, "steps", None)
        if not steps:
            # Store interaction ID in provider_data
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["interaction_id"] = self._previous_interaction_id
            return model_response

        for step in steps:
            if isinstance(step, ModelOutputStep):
                # ModelOutputStep contains a list of content items (TextContent, ImageContent, etc.)
                if step.content:
                    for content_item in step.content:
                        if isinstance(content_item, TextContent):
                            text = content_item.text or ""
                            if model_response.content is None:
                                model_response.content = text
                            else:
                                model_response.content += text

            elif isinstance(step, ThoughtStep):
                # ThoughtStep.summary is Optional[List[TextContent | ImageContent]]
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
        if hasattr(interaction, "usage") and interaction.usage:
            usage = interaction.usage
            model_response.response_usage = MessageMetrics(
                input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
                output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
            )

        # Store interaction ID in provider_data
        if model_response.provider_data is None:
            model_response.provider_data = {}
        model_response.provider_data["interaction_id"] = self._previous_interaction_id

        return model_response

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        """Parse a raw Interaction response. Delegates to _parse_interaction_response."""
        return self._parse_interaction_response(response)

    def _parse_provider_response_delta(self, response: Any, **kwargs: Any) -> ModelResponse:
        """Not used directly - streaming is handled in invoke_stream/ainvoke_stream."""
        return ModelResponse()

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

            return self._parse_interaction_response(interaction)

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

            # Track pending function call during streaming - arguments arrive incrementally
            pending_tool_call: Optional[Dict[str, Any]] = None
            pending_args_buffer: str = ""

            for event in stream:
                model_response = ModelResponse()

                if isinstance(event, interaction_types.InteractionCreatedEvent):
                    if event.interaction and hasattr(event.interaction, "id"):
                        self._previous_interaction_id = event.interaction.id
                        model_response.provider_data = {"interaction_id": event.interaction.id}
                    model_response.role = "assistant"
                    yield model_response

                elif isinstance(event, interaction_types.StepDelta):
                    delta = event.delta
                    if isinstance(delta, DeltaText):
                        model_response.content = delta.text or ""
                        yield model_response
                    elif isinstance(delta, DeltaThoughtSummary):
                        model_response.reasoning_content = getattr(delta, "content", "") or ""
                        yield model_response
                    elif isinstance(delta, DeltaThoughtSignature):
                        if delta.signature:
                            model_response.provider_data = {"thought_signature": delta.signature}
                            yield model_response
                    elif isinstance(delta, DeltaArgumentsDelta):
                        # Accumulate argument deltas into the pending tool call
                        if delta.arguments:
                            pending_args_buffer += delta.arguments

                elif isinstance(event, interaction_types.StepStart):
                    step = event.step
                    if isinstance(step, FunctionCallStep):
                        # Start a new pending tool call - arguments will come via DeltaArgumentsDelta
                        pending_tool_call = {
                            "id": step.id or str(uuid4()),
                            "type": "function",
                            "function": {
                                "name": step.name or "",
                                "arguments": "",
                            },
                        }
                        if step.signature:
                            pending_tool_call["thought_signature"] = step.signature
                        # Initialize args buffer with any args already present
                        args = step.arguments
                        if isinstance(args, dict) and args:
                            pending_args_buffer = json.dumps(args)
                        else:
                            pending_args_buffer = ""

                elif isinstance(event, interaction_types.StepStop):
                    # Emit the complete tool call when the step finishes
                    if pending_tool_call is not None:
                        pending_tool_call["function"]["arguments"] = pending_args_buffer or "{}"
                        model_response.tool_calls.append(pending_tool_call)
                        pending_tool_call = None
                        pending_args_buffer = ""
                        yield model_response

                elif isinstance(event, interaction_types.InteractionCompletedEvent):
                    if event.interaction:
                        if hasattr(event.interaction, "usage") and event.interaction.usage:
                            usage = event.interaction.usage
                            model_response.response_usage = MessageMetrics(
                                input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
                                output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
                                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                            )
                        if hasattr(event.interaction, "id") and event.interaction.id:
                            self._previous_interaction_id = event.interaction.id
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

            return self._parse_interaction_response(interaction)

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

            # Track pending function call during streaming - arguments arrive incrementally
            pending_tool_call: Optional[Dict[str, Any]] = None
            pending_args_buffer: str = ""

            async for event in stream:
                model_response = ModelResponse()

                if isinstance(event, interaction_types.InteractionCreatedEvent):
                    if event.interaction and hasattr(event.interaction, "id"):
                        self._previous_interaction_id = event.interaction.id
                        model_response.provider_data = {"interaction_id": event.interaction.id}
                    model_response.role = "assistant"
                    yield model_response

                elif isinstance(event, interaction_types.StepDelta):
                    delta = event.delta
                    if isinstance(delta, DeltaText):
                        model_response.content = delta.text or ""
                        yield model_response
                    elif isinstance(delta, DeltaThoughtSummary):
                        model_response.reasoning_content = getattr(delta, "content", "") or ""
                        yield model_response
                    elif isinstance(delta, DeltaThoughtSignature):
                        if delta.signature:
                            model_response.provider_data = {"thought_signature": delta.signature}
                            yield model_response
                    elif isinstance(delta, DeltaArgumentsDelta):
                        # Accumulate argument deltas into the pending tool call
                        if delta.arguments:
                            pending_args_buffer += delta.arguments

                elif isinstance(event, interaction_types.StepStart):
                    step = event.step
                    if isinstance(step, FunctionCallStep):
                        pending_tool_call = {
                            "id": step.id or str(uuid4()),
                            "type": "function",
                            "function": {
                                "name": step.name or "",
                                "arguments": "",
                            },
                        }
                        if step.signature:
                            pending_tool_call["thought_signature"] = step.signature
                        args = step.arguments
                        if isinstance(args, dict) and args:
                            pending_args_buffer = json.dumps(args)
                        else:
                            pending_args_buffer = ""

                elif isinstance(event, interaction_types.StepStop):
                    if pending_tool_call is not None:
                        pending_tool_call["function"]["arguments"] = pending_args_buffer or "{}"
                        model_response.tool_calls.append(pending_tool_call)
                        pending_tool_call = None
                        pending_args_buffer = ""
                        yield model_response

                elif isinstance(event, interaction_types.InteractionCompletedEvent):
                    if event.interaction:
                        if hasattr(event.interaction, "usage") and event.interaction.usage:
                            usage = event.interaction.usage
                            model_response.response_usage = MessageMetrics(
                                input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
                                output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
                                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                            )
                        if hasattr(event.interaction, "id") and event.interaction.id:
                            self._previous_interaction_id = event.interaction.id
                    yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error from Gemini Interactions API (async stream): {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
