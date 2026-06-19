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
from typing import Any, ClassVar, Dict, Iterator, List, Literal, Optional, Tuple, Type, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Audio, Image
from agno.models.base import Model
from agno.models.google.utils import media_to_content_item
from agno.models.message import Citations, Message, UrlCitation
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunOutput
from agno.utils.gemini import inject_agno_client_header
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai import interactions as interaction_types
    from google.genai.interactions import (
        AudioContent,
        CodeExecutionCallStep,
        CodeExecutionResultStep,
        FileSearchCallStep,
        FileSearchResultStep,
        FunctionCallStep,
        FunctionResultStep,
        GoogleMapsCallStep,
        GoogleMapsResultStep,
        GoogleSearchCallStep,
        GoogleSearchResultStep,
        ImageContent,
        MCPServerToolCallStep,
        MCPServerToolResultStep,
        ModelOutputStep,
        TextContent,
        ThoughtStep,
        URLContextCallStep,
        URLContextResultStep,
    )

    # The streaming delta types were relocated and renamed in google-genai 2.9.0:
    # they moved from the `step_delta` submodule (named `Delta<X>`) to the top-level
    # `interactions` namespace (renamed `<X>Delta`). Support both layouts so we don't
    # force an SDK upgrade. Local `Delta*` aliases keep the rest of this module stable.
    try:
        # google-genai >= 2.9.0
        from google.genai.interactions import (  # type: ignore[attr-defined]
            ArgumentsDelta as DeltaArgumentsDelta,
            CodeExecutionCallDelta as DeltaCodeExecutionCall,
            CodeExecutionResultDelta as DeltaCodeExecutionResult,
            FileSearchCallDelta as DeltaFileSearchCall,
            FileSearchResultDelta as DeltaFileSearchResult,
            FunctionResultDelta as DeltaFunctionResult,
            GoogleMapsCallDelta as DeltaGoogleMapsCall,
            GoogleMapsResultDelta as DeltaGoogleMapsResult,
            GoogleSearchCallDelta as DeltaGoogleSearchCall,
            GoogleSearchResultDelta as DeltaGoogleSearchResult,
            ImageDelta as DeltaImage,
            MCPServerToolCallDelta as DeltaMCPServerToolCall,
            MCPServerToolResultDelta as DeltaMCPServerToolResult,
            TextDelta as DeltaText,
            ThoughtSignatureDelta as DeltaThoughtSignature,
            ThoughtSummaryDelta as DeltaThoughtSummary,
            URLContextCallDelta as DeltaURLContextCall,
            URLContextResultDelta as DeltaURLContextResult,
        )
    except ImportError:
        # google-genai < 2.9.0: delta types live under the `step_delta` submodule,
        # exposed as a submodule attribute (not a sub-package), so the Delta* types
        # need attribute access rather than a direct import.
        from google.genai.interactions import step_delta  # type: ignore[attr-defined]

        DeltaArgumentsDelta = step_delta.DeltaArgumentsDelta
        DeltaImage = step_delta.DeltaImage
        DeltaText = step_delta.DeltaText
        DeltaThoughtSignature = step_delta.DeltaThoughtSignature
        DeltaThoughtSummary = step_delta.DeltaThoughtSummary
        # Typed call deltas. Non-function call families stream their typed
        # Arguments object here (DeltaArgumentsDelta only fires for functions).
        DeltaCodeExecutionCall = step_delta.DeltaCodeExecutionCall
        DeltaFileSearchCall = step_delta.DeltaFileSearchCall
        DeltaGoogleMapsCall = step_delta.DeltaGoogleMapsCall
        DeltaGoogleSearchCall = step_delta.DeltaGoogleSearchCall
        DeltaMCPServerToolCall = step_delta.DeltaMCPServerToolCall
        DeltaURLContextCall = step_delta.DeltaURLContextCall
        # Result deltas. Every *ResultStep arrives empty at StepStart and its
        # actual payload streams here (one or more deltas, then StepStop).
        DeltaCodeExecutionResult = step_delta.DeltaCodeExecutionResult
        DeltaFileSearchResult = step_delta.DeltaFileSearchResult
        DeltaFunctionResult = step_delta.DeltaFunctionResult
        DeltaGoogleMapsResult = step_delta.DeltaGoogleMapsResult
        DeltaGoogleSearchResult = step_delta.DeltaGoogleSearchResult
        DeltaMCPServerToolResult = step_delta.DeltaMCPServerToolResult
        DeltaURLContextResult = step_delta.DeltaURLContextResult
except ImportError:
    raise ImportError(
        "`google-genai` not installed or not at the latest version. "
        "Please install it using `pip install -U google-genai`"
    )

# Tuples used to detect call/result steps generically across all tool families.
_CALL_STEP_TYPES = (
    FunctionCallStep,
    CodeExecutionCallStep,
    URLContextCallStep,
    MCPServerToolCallStep,
    GoogleSearchCallStep,
    FileSearchCallStep,
    GoogleMapsCallStep,
)
_RESULT_STEP_TYPES = (
    FunctionResultStep,
    CodeExecutionResultStep,
    URLContextResultStep,
    MCPServerToolResultStep,
    GoogleSearchResultStep,
    FileSearchResultStep,
    GoogleMapsResultStep,
)
# Typed call deltas (non-function). Function calls use DeltaArgumentsDelta
# and are handled separately because they buffer args as a JSON string.
_TYPED_CALL_DELTA_TYPES = (
    DeltaCodeExecutionCall,
    DeltaURLContextCall,
    DeltaMCPServerToolCall,
    DeltaGoogleSearchCall,
    DeltaFileSearchCall,
    DeltaGoogleMapsCall,
)
_RESULT_DELTA_TYPES = (
    DeltaFunctionResult,
    DeltaCodeExecutionResult,
    DeltaURLContextResult,
    DeltaMCPServerToolResult,
    DeltaGoogleSearchResult,
    DeltaFileSearchResult,
    DeltaGoogleMapsResult,
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

    # Raw GenerationConfigParam passthrough. Accepts either a dict or a
    # Pydantic model (e.g. google.genai.types.GenerateContentConfig). Merged
    # into the generation_config built from the fields above; keys here
    # override field-derived values. Pydantic models are dumped with
    # exclude_none so unset fields don't flood the request.
    generation_config: Optional[Union[Dict[str, Any], BaseModel]] = None

    # Interactions API specific parameters
    store: Optional[bool] = None  # Whether to persist interactions server-side (default: True)

    # Thinking configuration
    thinking_level: Optional[Literal["minimal", "low", "medium", "high"]] = None

    # Built-in tools
    search: bool = False
    url_context: bool = False
    code_execution: bool = False
    # Remote MCP servers. Supported on the model path and on Deep Research;
    # NOT supported on Antigravity (the docs list it as out-of-scope).
    # Each entry:
    #   {"name": "...", "url": "https://...", "headers": {...}, "allowed_tools": [...]}
    # `type` is added automatically; only `url` is strictly required.
    mcp_servers: Optional[List[Dict[str, Any]]] = None
    # File Search store names to ground responses on your own corpora, e.g.
    # ["fileSearchStores/my-store-name"]. Supported on the model path and on
    # Deep Research; NOT supported on Antigravity.
    file_search_store_names: Optional[List[str]] = None

    # Agent path (e.g. Deep Research, Antigravity). When `agent` is set, the
    # request uses the agent + agent_config path instead of model +
    # generation_config. The SDK enforces these are mutually exclusive.
    # Examples:
    #   agent="deep-research-preview-04-2026"
    #   agent="antigravity-preview-05-2026"
    agent: Optional[str] = None
    # Deep Research agent_config knobs (only sent when `agent` is a deep-research id):
    collaborative_planning: Optional[bool] = None  # turn 1 returns a plan; flip to False to execute
    thinking_summaries: Optional[Literal["auto", "none"]] = None
    visualization: Optional[Literal["off", "auto"]] = None
    # Antigravity environment. One of:
    #   - "remote"                  -> provision a fresh remote sandbox
    #   - "env_<id>"                -> reuse an existing environment by id
    #   - {...EnvironmentConfig}    -> custom sources / network rules
    # Only forwarded on the agent path; ignored otherwise.
    environment: Optional[Union[str, Dict[str, Any]]] = None
    # Background polling cadence. Used for agents that run in background
    # mode (Deep Research). Antigravity runs in the foreground and does
    # not engage these knobs.
    agent_poll_interval: float = 10.0  # seconds between status polls
    agent_max_wait: float = 1800.0  # max seconds to wait for a terminal status (Deep Research can take minutes)
    # Terminal statuses for a background agent interaction. "completed" /
    # "failed" are documented; the rest are defensive. ClassVar so the
    # dataclass does not treat it as an instance field.
    _TERMINAL_STATUSES: ClassVar[Tuple[str, ...]] = ("completed", "failed", "cancelled", "incomplete")

    # Inference tier: "flex" (lower cost, higher latency), "standard", or "priority" (lowest latency)
    service_tier: Optional[Literal["flex", "standard", "priority"]] = None

    # Timeout in seconds
    timeout: Optional[float] = None

    # Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Client instance
    client: Optional[GeminiClient] = None

    def _find_previous_interaction(self, messages: List[Message]) -> tuple[Optional[str], int]:
        """Find the most recent assistant message with an interaction_id.

        Returns (interaction_id, index_in_messages) or (None, -1). The index
        marks the last turn the server has seen; messages after it are the
        new turns to send. Walks in reverse so we pick the most recent.
        """
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.role == "assistant" and msg.provider_data:
                iid = msg.provider_data.get("interaction_id")
                if iid:
                    return iid, i
        return None, -1

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
                "generation_config": self.generation_config,
                "agent": self.agent,
                "environment": self.environment,
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
        """Build keyword arguments for interactions.create().

        Two mutually exclusive paths (enforced by the SDK):
          - model path:  model + generation_config (default)
          - agent path:  agent + agent_config (when self.agent is set, e.g.
            a Deep Research agent id)
        """
        use_agent_path = self.agent is not None
        kwargs: Dict[str, Any] = {}
        if use_agent_path:
            kwargs["agent"] = self.agent
        else:
            kwargs["model"] = self.id

        # System instruction from the last system message (consistent with gemini.py)
        system_message = None
        for msg in messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_message = msg.content

        if system_message and not use_agent_path:
            # Agent path (Deep Research, etc.) rejects `system_instruction` and
            # treats anything in `input` as the research request. Agno's
            # auto-injected formatting boilerplate is not user research intent,
            # so it is dropped on the agent path rather than folded in.
            kwargs["system_instruction"] = system_message

        # When store=False on the model path, the user has opted out of
        # server-side state - send the full message history and don't chain
        # via previous_interaction_id. Otherwise (including the agent path,
        # which forces store=True), leverage server-side state: pass
        # previous_interaction_id and send only the messages AFTER the prior
        # assistant turn (the server already has everything up to that point).
        if self.store is False and not use_agent_path:
            input_messages: List[Message] = messages
        else:
            previous_interaction_id, boundary_idx = self._find_previous_interaction(messages)
            input_messages = messages if boundary_idx == -1 else messages[boundary_idx + 1 :]
            if previous_interaction_id:
                kwargs["previous_interaction_id"] = previous_interaction_id

        kwargs["input"] = self._build_input(input_messages)

        if use_agent_path:
            # agent_config is only valid with the agent path. For Deep Research
            # agents, send the deep-research config knobs. The SDK rejects
            # generation_config on this path.
            agent_config: Dict[str, Any] = {}
            if str(self.agent).startswith("deep-research"):
                agent_config["type"] = "deep-research"
                if self.collaborative_planning is not None:
                    agent_config["collaborative_planning"] = self.collaborative_planning
                if self.thinking_summaries is not None:
                    agent_config["thinking_summaries"] = self.thinking_summaries
                if self.visualization is not None:
                    agent_config["visualization"] = self.visualization
            # Only send agent_config if it carries a discriminating `type`.
            if agent_config.get("type"):
                kwargs["agent_config"] = agent_config
        else:
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
            # Merge user-provided raw config last - their keys override field-derived values.
            # If it's a Pydantic model (e.g. GenerateContentConfig), dump it with
            # exclude_none so the request isn't flooded with unset fields.
            if self.generation_config:
                extra = (
                    self.generation_config.model_dump(exclude_none=True)
                    if isinstance(self.generation_config, BaseModel)
                    else self.generation_config
                )
                generation_config.update(extra)
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
        if self.mcp_servers:
            for server in self.mcp_servers:
                # Discriminator goes last so a stray "type" in the user's
                # server dict can't clobber it.
                all_tools.append({**server, "type": "mcp_server"})
        if self.file_search_store_names:
            all_tools.append({"type": "file_search", "file_search_store_names": self.file_search_store_names})
        if all_tools:
            kwargs["tools"] = all_tools

        # Service tier (flex/standard/priority)
        if self.service_tier is not None:
            kwargs["service_tier"] = self.service_tier

        # Store
        if self.store is not None:
            kwargs["store"] = self.store

        if use_agent_path:
            # The agent path always requires server-side state.
            kwargs["store"] = True

            # Per-agent background semantics:
            #   - Deep Research REQUIRES background=True (long-running, server
            #     drives the autonomous loop).
            #   - Antigravity does NOT support background=True (the SDK
            #     rejects it; the agent runs in the foreground).
            # Anything else: leave background unset and let the SDK default
            # apply.
            agent_id = str(self.agent)
            if agent_id.startswith("deep-research"):
                kwargs["background"] = True
                log_debug(
                    "Deep Research requires background execution; forcing background=True and store=True.",
                    log_level=2,
                )
            else:
                log_debug(
                    "Agent path forcing store=True (server-side state is required).",
                    log_level=2,
                )

            # Antigravity (and any future agent that takes one) reads its
            # sandbox spec from `environment`. Forwarded as-is.
            if self.environment is not None:
                kwargs["environment"] = self.environment

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

    def _call_step_info(self, step: Any) -> Tuple[str, Dict[str, Any]]:
        """Return (tool_name, tool_args) for any call step type.

        Each tool family has its own *CallStep schema; this normalizes them
        into a single (name, args) tuple suitable for ToolExecution.
        """
        if isinstance(step, FunctionCallStep):
            return step.name or "", dict(step.arguments) if step.arguments else {}
        if isinstance(step, CodeExecutionCallStep):
            args = step.arguments.model_dump(exclude_none=True) if step.arguments else {}
            return "code_execution", args
        if isinstance(step, URLContextCallStep):
            args = step.arguments.model_dump(exclude_none=True) if step.arguments else {}
            return "url_context", args
        if isinstance(step, MCPServerToolCallStep):
            args = dict(step.arguments) if step.arguments else {}
            if step.server_name:
                args.setdefault("_server_name", step.server_name)
            return step.name or "mcp_tool", args
        if isinstance(step, GoogleSearchCallStep):
            args = step.arguments.model_dump(exclude_none=True) if step.arguments else {}
            if step.search_type:
                args["search_type"] = step.search_type
            return "google_search", args
        if isinstance(step, FileSearchCallStep):
            return "file_search", {}
        if isinstance(step, GoogleMapsCallStep):
            args = step.arguments.model_dump(exclude_none=True) if step.arguments else {}
            return "google_maps", args
        return "unknown", {}

    def _extract_step_result(self, step: Any, model_response: ModelResponse) -> Tuple[Optional[str], Optional[bool]]:
        """Flatten any *ResultStep's payload to (result_text, is_error).

        Image content embedded in results is routed onto model_response.images
        so downstream consumers can render it. Typed result objects (e.g.
        URLContext.Result, GoogleSearch.Result) are JSON-serialized.
        """
        is_error = getattr(step, "is_error", None)
        raw = getattr(step, "result", None)
        if raw is None:
            return None, is_error
        if isinstance(raw, str):
            return raw, is_error
        if isinstance(raw, list):
            text_parts: List[str] = []
            for item in raw:
                if isinstance(item, TextContent):
                    if item.text:
                        text_parts.append(item.text)
                elif ImageContent is not None and isinstance(item, ImageContent):
                    image = self._parse_image_content(item)
                    if image:
                        if model_response.images is None:
                            model_response.images = []
                        model_response.images.append(image)
                elif hasattr(item, "model_dump"):
                    text_parts.append(json.dumps(item.model_dump(exclude_none=True)))
                else:
                    text_parts.append(str(item))
            return ("\n".join(text_parts) if text_parts else None), is_error
        if hasattr(raw, "model_dump"):
            return json.dumps(raw.model_dump(exclude_none=True)), is_error
        try:
            return json.dumps(raw), is_error
        except (TypeError, ValueError):
            return str(raw), is_error

    def _delta_args_to_dict(self, delta: Any) -> Optional[Dict[str, Any]]:
        """Extract the typed `arguments` from a *Call delta as a plain dict.

        Non-function call families stream their complete typed Arguments
        object on a single delta (e.g. DeltaGoogleSearchCall carries a
        GoogleSearchCallArguments(queries=[...])); FunctionCallStep uses
        DeltaArgumentsDelta with JSON fragments and is handled separately.
        """
        args = getattr(delta, "arguments", None)
        if args is None:
            return None
        if isinstance(args, dict):
            return dict(args)
        if hasattr(args, "model_dump"):
            return args.model_dump(exclude_none=True)
        return None

    def _append_result_delta(self, delta: Any, pending_result: Dict[str, Any], model_response: ModelResponse) -> None:
        """Append one *Result delta's content into a pending_result accumulator.

        Result steps arrive empty at StepStart; their actual payload streams
        across one or more deltas before StepStop. Text accumulates into
        text_parts; ImageContent routes to model_response.images; typed
        result objects (URL/Search/Maps Result, etc.) are JSON-serialized.
        """
        is_error = getattr(delta, "is_error", None)
        if is_error is not None:
            pending_result["is_error"] = is_error
        raw = getattr(delta, "result", None)
        if raw is None:
            return
        if isinstance(raw, str):
            pending_result["text_parts"].append(raw)
            return
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, TextContent):
                    if item.text:
                        pending_result["text_parts"].append(item.text)
                elif ImageContent is not None and isinstance(item, ImageContent):
                    image = self._parse_image_content(item)
                    if image:
                        if model_response.images is None:
                            model_response.images = []
                        model_response.images.append(image)
                elif hasattr(item, "model_dump"):
                    pending_result["text_parts"].append(json.dumps(item.model_dump(exclude_none=True)))
                else:
                    pending_result["text_parts"].append(str(item))
            return
        if hasattr(raw, "model_dump"):
            pending_result["text_parts"].append(json.dumps(raw.model_dump(exclude_none=True)))
        else:
            pending_result["text_parts"].append(str(raw))

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        """Parse an Interaction response into a ModelResponse."""
        model_response = ModelResponse()
        model_response.role = "assistant"

        interaction_id = getattr(response, "id", None)

        # Surface any non-success terminal status as an error rather than
        # returning a silently empty/partial response. "completed" is the
        # only success state; "failed" carries an error reason, while
        # "cancelled" / "incomplete" indicate the autonomous loop stopped
        # before finishing the work.
        status = getattr(response, "status", None)
        if status in ("failed", "cancelled", "incomplete"):
            error_detail = getattr(response, "error", None)
            raise ModelProviderError(
                message=f"Interaction ended with status '{status}': {error_detail or 'no error detail provided'}",
                model_name=self.name,
                model_id=self.id,
            )

        steps = getattr(response, "steps", None)
        if not steps:
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["interaction_id"] = interaction_id
            return model_response

        # Index every *ResultStep by call_id so each *CallStep can be paired
        # with its result in a single forward pass. Used on the agent path
        # where calls + results are returned together as a typed audit log.
        results_by_call_id: Dict[str, Any] = {}
        if self.agent is not None:
            for step in steps:
                if isinstance(step, _RESULT_STEP_TYPES):
                    results_by_call_id[step.call_id] = step

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
                            # Extract citations from annotations. Deep Research
                            # also emits file_citation / place_citation in
                            # addition to url_citation.
                            annotations = getattr(content_item, "annotations", None)
                            if annotations:
                                for annotation in annotations:
                                    ann_type = getattr(annotation, "type", None)
                                    if ann_type not in ("url_citation", "file_citation", "place_citation"):
                                        continue
                                    if model_response.citations is None:
                                        model_response.citations = Citations(raw=[], urls=[])
                                    if model_response.citations.raw is None:
                                        model_response.citations.raw = []
                                    model_response.citations.raw.append(annotation)
                                    if ann_type == "url_citation":
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

            elif isinstance(step, _CALL_STEP_TYPES) and self.agent is not None:
                # Agent path: every call/result pair is already executed by the
                # autonomous loop (Antigravity sandbox, Deep Research). Record
                # each as a ToolExecution so the run_response/AgentOS UI shows
                # the same tool history we'd see for client-executed tools,
                # without sending function_result back (the API would 400).
                #
                # Exception: a FunctionCallStep with no matching FunctionResult
                # is a client-declared tool the server is asking us to run -
                # fall through to the client-dispatch branch below so the run
                # loop can execute it and post the result back. The other six
                # families are always server-built-in.
                result_step = results_by_call_id.get(step.id)
                if isinstance(step, FunctionCallStep) and result_step is None:
                    pass  # handled by the next branch
                else:
                    tool_name, tool_args = self._call_step_info(step)
                    if result_step is not None:
                        result_text, is_error = self._extract_step_result(result_step, model_response)
                    else:
                        result_text, is_error = None, None
                    if model_response.tool_executions is None:
                        model_response.tool_executions = []
                    model_response.tool_executions.append(
                        ToolExecution(
                            tool_call_id=step.id,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            result=result_text,
                            tool_call_error=bool(is_error) if is_error is not None else None,
                        )
                    )
                    log_info(f"Server-side tool call: {tool_name}({json.dumps(tool_args) if tool_args else ''})")
                    continue

            if isinstance(step, FunctionCallStep):
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
                # FunctionCallStep dropped the `signature` field in google-genai 2.9.0.
                step_signature = getattr(step, "signature", None)
                if step_signature:
                    tool_call["thought_signature"] = step_signature
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

        # Every event carries an event_id used to resume a dropped/ended stream
        # (background interactions like Deep Research end the initial SSE early
        # and continue server-side; we reconnect from last_event_id).
        event_id = getattr(stream_event, "event_id", None)
        if event_id:
            stream_state["last_event_id"] = event_id

        if isinstance(stream_event, interaction_types.InteractionCreatedEvent):
            if stream_event.interaction and hasattr(stream_event.interaction, "id"):
                iid = stream_event.interaction.id
                model_response.provider_data = {"interaction_id": iid}
                stream_state["interaction_id"] = iid
            model_response.role = "assistant"

        elif isinstance(stream_event, interaction_types.InteractionStatusUpdate):
            # Progress ping for a background interaction. No user-visible
            # content; just record the latest status for the reconnect loop.
            status = getattr(stream_event, "status", None)
            if status:
                stream_state["status"] = status
            iid = getattr(stream_event, "interaction_id", None)
            if iid:
                stream_state["interaction_id"] = iid

        elif isinstance(stream_event, interaction_types.ErrorEvent):
            stream_state["completed"] = True
            detail = getattr(stream_event, "error", None) or getattr(stream_event, "message", None)
            raise ModelProviderError(
                message=f"Interaction stream error: {detail or 'no detail provided'}",
                model_name=self.name,
                model_id=self.id,
            )

        elif isinstance(stream_event, interaction_types.StepDelta):
            delta = stream_event.delta
            if isinstance(delta, DeltaText):
                model_response.content = delta.text or ""
            elif isinstance(delta, DeltaImage):
                # Streamed visualization charts (visualization="auto").
                image = self._parse_image_content(delta)
                if image:
                    if model_response.images is None:
                        model_response.images = []
                    model_response.images.append(image)
            elif isinstance(delta, DeltaThoughtSummary):
                summary_content = getattr(delta, "content", None)
                if summary_content and isinstance(summary_content, TextContent):
                    text = summary_content.text or ""
                    model_response.reasoning_content = text
            elif isinstance(delta, DeltaThoughtSignature):
                if delta.signature:
                    # Merge instead of overwrite so other provider_data keys
                    # (e.g. interaction_id) on the same chunk survive.
                    if model_response.provider_data is None:
                        model_response.provider_data = {}
                    model_response.provider_data["thought_signature"] = delta.signature
            elif isinstance(delta, DeltaArgumentsDelta):
                # Function calls stream args as JSON fragments here; the buffer
                # is parsed on StepStop. Client tool_calls use stream index;
                # agent-path calls use a separate idx->call_id lookup.
                idx = stream_event.index
                if delta.arguments:
                    if idx in stream_state["pending_calls"]:
                        stream_state["pending_calls"][idx]["args_buffer"] += delta.arguments
                    else:
                        call_id = stream_state.setdefault("agent_idx_to_call_id", {}).get(idx)
                        agent_pending = (
                            stream_state.setdefault("pending_agent_calls", {}).get(call_id) if call_id else None
                        )
                        if agent_pending is not None:
                            agent_pending["args_buffer"] += delta.arguments
            elif isinstance(delta, _TYPED_CALL_DELTA_TYPES):
                # Non-function call families stream their complete typed
                # Arguments object on a single delta. Replace tool_args so
                # google_search etc. surface their queries / code / urls.
                idx = stream_event.index
                call_id = stream_state.setdefault("agent_idx_to_call_id", {}).get(idx)
                if call_id is not None:
                    agent_pending = stream_state.setdefault("pending_agent_calls", {}).get(call_id)
                    if agent_pending is not None:
                        args_dict = self._delta_args_to_dict(delta)
                        if args_dict:
                            agent_pending["tool_args"] = args_dict
            elif isinstance(delta, _RESULT_DELTA_TYPES):
                # Result content streams here after the result step's StepStart.
                # Accumulate into the pending_result for assembly on StepStop.
                idx = stream_event.index
                pending_result = stream_state.setdefault("pending_results", {}).get(idx)
                if pending_result is not None:
                    self._append_result_delta(delta, pending_result, model_response)

        elif isinstance(stream_event, interaction_types.StepStart):
            step = stream_event.step
            # Agent path: register pending entries for both calls and results.
            # Calls accumulate args via subsequent deltas; results accumulate
            # content via subsequent deltas. The pair is joined and emitted
            # as a ToolExecution on the result step's StepStop.
            if isinstance(step, _CALL_STEP_TYPES) and self.agent is not None:
                pending_agent_calls = stream_state.setdefault("pending_agent_calls", {})
                agent_idx_to_call_id = stream_state.setdefault("agent_idx_to_call_id", {})
                tool_name, tool_args = self._call_step_info(step)
                pending_agent_calls[step.id] = {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "args_buffer": "",
                    "is_function_call": isinstance(step, FunctionCallStep),
                    "signature": getattr(step, "signature", None),
                }
                agent_idx_to_call_id[stream_event.index] = step.id
            elif isinstance(step, _RESULT_STEP_TYPES) and self.agent is not None:
                # Register a pending_result keyed by stream index. The actual
                # payload arrives on subsequent _RESULT_DELTA_TYPES deltas;
                # we emit ToolExecution on this index's StepStop.
                pending_results = stream_state.setdefault("pending_results", {})
                pending = {
                    "call_id": step.call_id,
                    "text_parts": [],
                    "is_error": getattr(step, "is_error", None),
                }
                # Defensive: if the SDK ever populates step.result at StepStart
                # (current behavior is None), seed it now.
                if getattr(step, "result", None) is not None:
                    self._append_result_delta(step, pending, model_response)
                pending_results[stream_event.index] = pending
            elif isinstance(step, FunctionCallStep):
                idx = stream_event.index
                tool_call = {
                    "id": step.id or str(uuid4()),
                    "type": "function",
                    "function": {
                        "name": step.name or "",
                        "arguments": "",
                    },
                }
                # FunctionCallStep dropped the `signature` field in google-genai 2.9.0.
                step_signature = getattr(step, "signature", None)
                if step_signature:
                    tool_call["thought_signature"] = step_signature
                args = step.arguments
                args_buffer = json.dumps(args) if isinstance(args, dict) and args else ""
                stream_state["pending_calls"][idx] = {"tool_call": tool_call, "args_buffer": args_buffer}

        elif isinstance(stream_event, interaction_types.StepStop):
            idx = stream_event.index
            # Client tool_calls: finalize args buffer and emit.
            pending = stream_state["pending_calls"].pop(idx, None)
            if pending is not None:
                pending["tool_call"]["function"]["arguments"] = pending["args_buffer"] or "{}"
                model_response.tool_calls.append(pending["tool_call"])
            # Agent path: finalize the streamed args buffer on the pending
            # call (FunctionCallStep only - the others set tool_args directly
            # from their typed delta). Merge over initial StepStart args so
            # streamed keys win without clobbering anything already known.
            agent_idx_to_call_id = stream_state.setdefault("agent_idx_to_call_id", {})
            call_id_for_call = agent_idx_to_call_id.pop(idx, None)
            if call_id_for_call is not None:
                pending_agent_calls = stream_state.setdefault("pending_agent_calls", {})
                agent_pending = pending_agent_calls.get(call_id_for_call)
                if agent_pending is not None and agent_pending["args_buffer"]:
                    try:
                        parsed = json.loads(agent_pending["args_buffer"])
                        if isinstance(parsed, dict):
                            merged = dict(agent_pending["tool_args"] or {})
                            merged.update(parsed)
                            agent_pending["tool_args"] = merged
                    except json.JSONDecodeError:
                        pass
            # Agent path: a pending_result at this index is now complete -
            # assemble the text, look up its matching pending_agent_call by
            # call_id, and emit the ToolExecution.
            pending_results = stream_state.setdefault("pending_results", {})
            pending_result = pending_results.pop(idx, None)
            if pending_result is not None:
                result_text = "\n".join(pending_result["text_parts"]) if pending_result["text_parts"] else None
                is_error = pending_result["is_error"]
                pending_agent_calls = stream_state.setdefault("pending_agent_calls", {})
                pending_call = pending_agent_calls.pop(pending_result["call_id"], None)
                if pending_call is not None:
                    if model_response.tool_executions is None:
                        model_response.tool_executions = []
                    model_response.tool_executions.append(
                        ToolExecution(
                            tool_call_id=pending_result["call_id"],
                            tool_name=pending_call["tool_name"],
                            tool_args=pending_call["tool_args"],
                            result=result_text,
                            tool_call_error=bool(is_error) if is_error is not None else None,
                        )
                    )
                    # Tag the event so the streaming consumer in
                    # agent/_response.py routes tool_executions into
                    # run_response.tools and emits the UI tool-call event.
                    model_response.event = ModelResponseEvent.tool_call_completed.value
                    args_repr = json.dumps(pending_call["tool_args"]) if pending_call["tool_args"] else ""
                    log_info(f"Server-side tool call: {pending_call['tool_name']}({args_repr})")

        elif isinstance(stream_event, interaction_types.InteractionCompletedEvent):
            stream_state["completed"] = True
            # Flush any agent-path FunctionCallSteps that never got a matching
            # FunctionResultStep - those are client-declared tools the
            # autonomous loop is asking us to dispatch. Built-in step families
            # (code_execution, url_context, etc.) have no client equivalent,
            # so an unmatched one is dropped defensively.
            pending_agent_calls = stream_state.get("pending_agent_calls", {})
            for call_id, info in list(pending_agent_calls.items()):
                if not info.get("is_function_call"):
                    continue
                args_str = json.dumps(info["tool_args"]) if info["tool_args"] else "{}"
                tool_call = {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": info["tool_name"],
                        "arguments": args_str,
                    },
                }
                if info.get("signature"):
                    tool_call["thought_signature"] = info["signature"]
                model_response.tool_calls.append(tool_call)
            pending_agent_calls.clear()
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

    def _poll_until_terminal(self, interaction: Any) -> Any:
        """Poll interactions.get() until the background interaction is terminal.

        Used for the agent path (background=True), where create() returns an
        in_progress interaction. Returns the final interaction.
        """
        import time

        status = getattr(interaction, "status", None)
        if status is None or status in self._TERMINAL_STATUSES:
            return interaction

        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            return interaction

        deadline = time.monotonic() + self.agent_max_wait
        client = self.get_client()
        while True:
            if time.monotonic() > deadline:
                raise ModelProviderError(
                    message=f"Agent interaction did not complete within {self.agent_max_wait}s (last status: {status})",
                    model_name=self.name,
                    model_id=self.id,
                )
            time.sleep(self.agent_poll_interval)
            interaction = client.interactions.get(interaction_id)
            status = getattr(interaction, "status", None)
            log_debug(f"Agent interaction {interaction_id} status: {status}", log_level=2)
            if status is None or status in self._TERMINAL_STATUSES:
                return interaction

    async def _apoll_until_terminal(self, interaction: Any) -> Any:
        """Async variant of _poll_until_terminal."""
        import asyncio

        status = getattr(interaction, "status", None)
        if status is None or status in self._TERMINAL_STATUSES:
            return interaction

        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            return interaction

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.agent_max_wait
        client = self.get_client()
        while True:
            if loop.time() > deadline:
                raise ModelProviderError(
                    message=f"Agent interaction did not complete within {self.agent_max_wait}s (last status: {status})",
                    model_name=self.name,
                    model_id=self.id,
                )
            await asyncio.sleep(self.agent_poll_interval)
            interaction = await client.aio.interactions.get(interaction_id)
            status = getattr(interaction, "status", None)
            log_debug(f"Agent interaction {interaction_id} status: {status}", log_level=2)
            if status is None or status in self._TERMINAL_STATUSES:
                return interaction

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
            # Agent path runs in the background; poll until the result is ready.
            if request_kwargs.get("background"):
                interaction = self._poll_until_terminal(interaction)
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

        is_background = bool(request_kwargs.get("background"))

        try:
            import time

            assistant_message.metrics.start_timer()
            client = self.get_client()
            stream = client.interactions.create(**request_kwargs)
            stream_state: Dict[str, Any] = {"pending_calls": {}}

            for event in stream:
                model_response, stream_state = self._parse_provider_response_delta(
                    stream_event=event, assistant_message=assistant_message, stream_state=stream_state
                )
                yield model_response

            # Background interactions (Deep Research) end the initial SSE early
            # and continue server-side. Reconnect from last_event_id until the
            # interaction reaches a terminal state, per the API guidance.
            if is_background:
                deadline = time.monotonic() + self.agent_max_wait
                while not stream_state.get("completed"):
                    interaction_id = stream_state.get("interaction_id")
                    if not interaction_id:
                        break
                    if time.monotonic() > deadline:
                        raise ModelProviderError(
                            message=f"Streaming interaction did not complete within {self.agent_max_wait}s",
                            model_name=self.name,
                            model_id=self.id,
                        )
                    snapshot = client.interactions.get(interaction_id)
                    status = getattr(snapshot, "status", None)
                    if status != "in_progress":
                        # Doc guidance: any non-in_progress status ends the loop.
                        # Surface the final snapshot through the non-stream parser
                        # so content + errors (failed) are handled.
                        yield self._parse_provider_response(snapshot)
                        break
                    time.sleep(self.agent_poll_interval)
                    resumed = client.interactions.get(
                        id=interaction_id,
                        stream=True,
                        last_event_id=stream_state.get("last_event_id"),
                    )
                    for event in resumed:
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
            # Agent path runs in the background; poll until the result is ready.
            if request_kwargs.get("background"):
                interaction = await self._apoll_until_terminal(interaction)
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

        is_background = bool(request_kwargs.get("background"))

        try:
            import asyncio

            assistant_message.metrics.start_timer()
            client = self.get_client()
            stream = await client.aio.interactions.create(**request_kwargs)
            stream_state: Dict[str, Any] = {"pending_calls": {}}

            async for event in stream:
                model_response, stream_state = self._parse_provider_response_delta(
                    stream_event=event, assistant_message=assistant_message, stream_state=stream_state
                )
                yield model_response

            if is_background:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.agent_max_wait
                while not stream_state.get("completed"):
                    interaction_id = stream_state.get("interaction_id")
                    if not interaction_id:
                        break
                    if loop.time() > deadline:
                        raise ModelProviderError(
                            message=f"Streaming interaction did not complete within {self.agent_max_wait}s",
                            model_name=self.name,
                            model_id=self.id,
                        )
                    snapshot = await client.aio.interactions.get(interaction_id)
                    status = getattr(snapshot, "status", None)
                    if status != "in_progress":
                        yield self._parse_provider_response(snapshot)
                        break
                    await asyncio.sleep(self.agent_poll_interval)
                    resumed = await client.aio.interactions.get(
                        id=interaction_id,
                        stream=True,
                        last_event_id=stream_state.get("last_event_id"),
                    )
                    async for event in resumed:
                        model_response, stream_state = self._parse_provider_response_delta(
                            stream_event=event, assistant_message=assistant_message, stream_state=stream_state
                        )
                        yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error from Gemini Interactions API (async stream): {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
