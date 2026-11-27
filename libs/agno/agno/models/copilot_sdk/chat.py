"""GitHub Copilot model provider for Agno."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug, log_error

try:
    from copilot import (  # type: ignore[import-not-found]
        CopilotClient,
        CopilotSession,
        SessionEvent,
        Tool,
        ToolInvocation,
        ToolResult,
    )
    from copilot.generated.session_events import SessionEventType  # type: ignore[import-not-found]
except (ImportError, ModuleNotFoundError):
    raise ImportError("GitHub Copilot SDK not installed. Install with: pip install github-copilot-sdk")


@dataclass
class CopilotChat(Model):
    """
    GitHub Copilot model provider.

    Integrates with GitHub Copilot via the github-copilot-sdk to provide
    AI-powered code assistance through Agno's agent framework.

    Prerequisites:
    1. Install SDK: pip install github-copilot-sdk
    2. Install CLI: Install GitHub Copilot CLI separately
    3. Authenticate: copilot auth login

    Example:
        from agno import Agent
        from agno.models.copilot import CopilotChat

        agent = Agent(
            model=CopilotChat(),
            description="Code assistance agent"
        )
        response = agent.run("Explain Python decorators")
    """

    # Model configuration
    # Note: SDK supports "gpt-5", "claude-sonnet-4", "claude-sonnet-4.5", "claude-haiku-4.5"
    # Using "gpt-4o" may require provider configuration (BYOK)
    id: str = "gpt-4o"  # Default Copilot model
    name: str = "CopilotChat"
    provider: str = "GitHub Copilot"

    # Client configuration
    cli_path: str = "copilot"  # Path to copilot CLI executable
    cli_url: Optional[str] = None  # Optional CLI URL
    use_stdio: bool = True  # Use stdio for communication
    log_level: str = "info"  # Logging level for SDK
    session_timeout: float = 60.0  # Session timeout in seconds

    # Session configuration (maps to SessionConfig in Copilot SDK)
    session_id: Optional[str] = None  # Optional custom session ID
    system_message: Optional[str] = None  # System message for the session
    mcp_servers: Optional[Dict[str, Any]] = None  # MCP server configurations for Copilot SDK's native MCP support
    provider_config: Optional[Dict[str, Any]] = None  # Custom provider configuration (BYOK)
    config_dir: Optional[str] = None  # Override default configuration directory

    # Cached client
    _client: Optional[CopilotClient] = field(default=None, init=False, repr=False)
    _client_started: bool = field(default=False, init=False, repr=False)
    _tool_registry: Dict[str, Dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    async def get_async_client(self) -> CopilotClient:
        """
        Get or create cached async client.

        Returns the cached client if available and started, otherwise creates
        a new client instance following the same pattern as OpenAI/Claude models.

        Returns:
            CopilotClient: The Copilot client instance.

        Raises:
            ModelProviderError: If client creation or startup fails.
        """
        # Return cached client if it exists and is started
        if self._client is not None and self._client_started:
            log_debug(f"Reusing existing GitHub Copilot client for model {self.id}")
            return self._client

        # Clean up any existing but not started client
        if self._client is not None and not self._client_started:
            log_debug("Cleaning up invalid client before creating new one")
            try:
                await self._cleanup_client()
            except Exception as e:
                log_error(f"Error cleaning up invalid client: {e}")

        try:
            log_debug(f"Creating new GitHub Copilot client for model {self.id}")

            # Create client configuration with only non-None values
            client_config: Dict[str, Any] = {
                "use_stdio": self.use_stdio,
                "log_level": self.log_level,
            }

            # Add optional parameters if provided
            if self.cli_path:
                client_config["cli_path"] = self.cli_path
            if self.cli_url:
                client_config["cli_url"] = self.cli_url

            log_debug(f"Copilot client config: {client_config}")

            # Create and start client
            self._client = CopilotClient(client_config)  # type: ignore[arg-type]
            await self._client.start()
            self._client_started = True

            log_debug("GitHub Copilot client started successfully")
            return self._client

        except FileNotFoundError as e:
            log_error(f"Copilot CLI not found at '{self.cli_path}'")
            raise ModelProviderError(
                message=f"Copilot CLI not found at '{self.cli_path}'. "
                "Ensure GitHub Copilot CLI is installed and available in PATH.",
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Failed to start Copilot client: {str(e)}")
            # Clean up failed client
            self._client = None
            self._client_started = False
            raise ModelProviderError(
                message=f"Failed to start Copilot client: {str(e)}",
                model_name=self.name,
                model_id=self.id,
            ) from e

    async def _cleanup_client(self):
        """Clean up client resources on shutdown."""
        if self._client and self._client_started:
            try:
                await self._client.stop()
                log_debug("Copilot client stopped successfully")
            except Exception as e:
                log_error(f"Error stopping Copilot client: {e}")
            finally:
                self._client_started = False
                self._client = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "cli_path": self.cli_path,
                "cli_url": self.cli_url,
                "use_stdio": self.use_stdio,
                "log_level": self.log_level,
                "session_timeout": self.session_timeout,
                "session_id": self.session_id,
                "system_message": self.system_message,
                "mcp_servers": self.mcp_servers,
                "provider_config": self.provider_config,
                "config_dir": self.config_dir,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CopilotChat":
        """
        Create a CopilotChat model from a dictionary.

        Args:
            data: Dictionary containing model configuration.

        Returns:
            CopilotChat: A new CopilotChat instance.
        """
        return cls(**data)

    def _build_session_config(
        self,
        streaming: bool,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Build Copilot SDK SessionConfig from model configuration and Agent parameters.

        Maps Agent's tool_choice parameter to Copilot SDK's available_tools/excluded_tools.

        Args:
            streaming: Whether to enable streaming.
            tools: Optional list of tool definitions from Agent.
            tool_choice: Optional tool choice strategy from Agent.
                - "none": Disables all tools (available_tools=[])
                - "auto": Lets model decide (no restrictions)
                - "required": Forces tool use (no restrictions, model will decide which tool)
                - {"type": "function", "function": {"name": "tool_name"}}: Restricts to specific tool

        Returns:
            Dict with SessionConfig parameters.
        """
        session_config: Dict[str, Any] = {
            "model": self.id,
            "streaming": streaming,
        }

        # Add optional session ID
        if self.session_id:
            session_config["session_id"] = self.session_id

        # Add system message if provided
        if self.system_message:
            session_config["system_message"] = {"content": self.system_message}

        # Add tools if provided
        tool_names = []
        if tools:
            copilot_tools = self._convert_tools(tools)
            if copilot_tools:
                session_config["tools"] = copilot_tools
                tool_names = [t.name for t in copilot_tools]
                log_debug(f"Added {len(copilot_tools)} tools to Copilot session config: {tool_names}")
            else:
                log_debug("No tools were converted from provided tools")
        else:
            log_debug("No tools provided to _build_session_config")

        # Map tool_choice to SDK's tool filtering
        # IMPORTANT: If tools are registered but available_tools is not set,
        # the SDK may not enable them by default. We need to explicitly enable them.
        if tool_choice:
            if tool_choice == "none":
                # Disable all tools
                session_config["available_tools"] = []
            elif isinstance(tool_choice, dict) and "function" in tool_choice:
                # Restrict to specific tool
                tool_name = tool_choice.get("function", {}).get("name")
                if tool_name:
                    session_config["available_tools"] = [tool_name]
            # For "auto" and "required": enable all registered tools
            elif tool_names:
                session_config["available_tools"] = tool_names
                log_debug(f"Enabled all {len(tool_names)} tools via available_tools")
        elif tool_names:
            # No tool_choice specified - enable all registered tools by default
            session_config["available_tools"] = tool_names
            log_debug(f"Enabled all {len(tool_names)} tools via available_tools (no tool_choice specified)")

        # Add provider configuration (BYOK)
        if self.provider_config:
            session_config["provider"] = self.provider_config

        # Add config directory
        if self.config_dir:
            session_config["config_dir"] = self.config_dir

        return session_config

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> str:
        """
        Format a single message into a string representation for Copilot.

        Handles multimodal content including images, audio, files, and tool results.

        Args:
            message: The message to format.
            compress_tool_results: Whether to use compressed content for tool results.

        Returns:
            str: Formatted message string.
        """
        role = message.role
        content = message.get_content(use_compressed_content=compress_tool_results)

        # Build content parts list
        content_parts: List[str] = []

        # Add text content
        if content:
            if isinstance(content, str):
                content_parts.append(content)
            elif isinstance(content, list):
                # Handle list content (convert to string)
                content_parts.append(str(content))

        # Handle images
        if message.images is not None and len(message.images) > 0:
            for idx, image in enumerate(message.images):
                if hasattr(image, "url") and image.url:
                    content_parts.append(f"[Image {idx + 1}: {image.url}]")
                elif hasattr(image, "data") and image.data:
                    content_parts.append(f"[Image {idx + 1}: base64 data]")
                else:
                    content_parts.append(f"[Image {idx + 1}]")

        # Handle audio
        if message.audio is not None and len(message.audio) > 0:
            for idx, audio in enumerate(message.audio):
                if hasattr(audio, "url") and audio.url:
                    content_parts.append(f"[Audio {idx + 1}: {audio.url}]")
                elif hasattr(audio, "data") and audio.data:
                    content_parts.append(f"[Audio {idx + 1}: base64 data]")
                else:
                    content_parts.append(f"[Audio {idx + 1}]")

        # Handle files
        if message.files is not None and len(message.files) > 0:
            for idx, file in enumerate(message.files):
                if hasattr(file, "name") and file.name:
                    content_parts.append(f"[File {idx + 1}: {file.name}]")
                else:
                    content_parts.append(f"[File {idx + 1}]")

        # Handle audio output
        if message.audio_output is not None:
            content_parts.append(f"[Audio output: {message.audio_output.id}]")

        # Handle tool calls
        if message.tool_calls is not None and len(message.tool_calls) > 0:
            for tool_call in message.tool_calls:
                tool_name = tool_call.get("function", {}).get("name", "unknown")
                content_parts.append(f"[Tool call: {tool_name}]")

        # Combine all parts
        formatted_content = " ".join(content_parts) if content_parts else ""

        # Format with role prefix
        if role == "system":
            return f"System: {formatted_content}"
        elif role == "user":
            return f"User: {formatted_content}"
        elif role == "assistant":
            return f"Assistant: {formatted_content}"
        elif role == "tool":
            # Include tool call ID for context if available
            if message.tool_call_id:
                return f"Tool result ({message.tool_call_id}): {formatted_content}"
            return f"Tool result: {formatted_content}"
        else:
            # Fallback for unknown roles
            return f"{role.capitalize()}: {formatted_content}"

    def _format_messages(self, messages: List[Message], compress_tool_results: bool = False) -> str:
        """
        Convert Agno Messages to Copilot prompt string.

        Args:
            messages: List of Agno Message objects.
            compress_tool_results: Whether to compress tool results.

        Returns:
            str: Formatted prompt string for Copilot.
        """
        parts = []
        for msg in messages:
            formatted = self._format_message(msg, compress_tool_results=compress_tool_results)
            if formatted:
                parts.append(formatted)

        return "\n\n".join(parts)

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Tool]:
        """
        Convert Agno Function objects to Copilot Tool format.

        Registers tools with Copilot SDK but doesn't execute them in the handler.
        Tool calls are extracted from events and executed by Agno's agentic loop.

        Args:
            tools: List of tool definitions in OpenAI format.

        Returns:
            List[Tool]: List of Copilot Tool objects.
        """
        log_debug(f"Converting {len(tools)} tools to Copilot format")
        copilot_tools = []

        # Clear registry for this request
        self._tool_registry = {}

        for tool_dict in tools:
            if tool_dict.get("type") != "function":
                log_debug(f"Skipping tool with type: {tool_dict.get('type')}")
                continue

            func_def = tool_dict.get("function", {})
            tool_name = func_def.get("name")

            if not tool_name:
                log_debug(f"Skipping tool without name: {tool_dict}")
                continue

            # Store original tool info for Agno's execution
            self._tool_registry[tool_name] = tool_dict

            # Create async handler that returns success without executing
            async def tool_handler(invocation: ToolInvocation) -> ToolResult:
                """
                Copilot tool handler placeholder.

                Returns success immediately. Actual tool execution happens
                in Agno's agentic loop when we extract tool calls from events.
                """
                return ToolResult(textResultForLlm="Tool execution handled by Agno", resultType="success")

            # Create Copilot Tool
            tool_description = func_def.get("description", "")
            tool_parameters = func_def.get("parameters", {})

            log_debug(f"Creating Copilot tool: name={tool_name}")
            log_debug(f"  description={tool_description}")
            log_debug(f"  parameters={tool_parameters}")

            copilot_tool = Tool(
                name=tool_name,
                description=tool_description,
                handler=tool_handler,
                parameters=tool_parameters,
            )
            copilot_tools.append(copilot_tool)
            log_debug(f"Converted tool: {tool_name}")

        log_debug(f"Converted {len(copilot_tools)} tools successfully")
        return copilot_tools

    async def _collect_response_from_events(
        self,
        session: CopilotSession,
        prompt: str,
    ) -> ModelResponse:
        """
        Collect complete response from session events.

        Subscribes to session events and collects:
        - Message content (complete and streaming)
        - Reasoning content
        - Tool calls
        - Token usage

        Args:
            session: Active Copilot session.
            prompt: The formatted prompt string.

        Returns:
            ModelResponse: Collected response data.

        Raises:
            ModelProviderError: If session error occurs or timeout is reached.
        """
        model_response = ModelResponse()
        done_event = asyncio.Event()

        content_parts = []
        reasoning_parts = []
        tool_calls: List[Dict[str, Any]] = []
        usage_data = None

        def on_event(event: SessionEvent):
            nonlocal usage_data

            event_type = event.type

            if event_type == SessionEventType.ASSISTANT_MESSAGE:
                # Complete message
                if hasattr(event.data, "content") and event.data.content:
                    content_parts.append(event.data.content)

            elif event_type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                # Streaming chunk
                if hasattr(event.data, "delta_content") and event.data.delta_content:
                    content_parts.append(event.data.delta_content)

            elif event_type == SessionEventType.ASSISTANT_REASONING:
                # Complete reasoning
                if hasattr(event.data, "content") and event.data.content:
                    reasoning_parts.append(event.data.content)

            elif event_type == SessionEventType.ASSISTANT_REASONING_DELTA:
                # Reasoning chunk
                if hasattr(event.data, "delta_content") and event.data.delta_content:
                    reasoning_parts.append(event.data.delta_content)

            elif event_type == SessionEventType.ASSISTANT_USAGE:
                # Token usage information
                if hasattr(event.data, "usage"):
                    usage_data = event.data.usage

            elif event_type == SessionEventType.TOOL_EXECUTION_START:
                # Tool is about to be called - extract details for Agno to execute
                if hasattr(event.data, "tool_call_id") and hasattr(event.data, "tool_name"):
                    tool_call = {
                        "id": event.data.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": event.data.tool_name,
                            "arguments": json.dumps(getattr(event.data, "arguments", {})),
                        },
                    }
                    tool_calls.append(tool_call)

            elif event_type == SessionEventType.TOOL_EXECUTION_COMPLETE:
                # Tool execution completed
                pass

            elif event_type == SessionEventType.SESSION_IDLE:
                # Session finished processing
                done_event.set()

            elif event_type == SessionEventType.SESSION_ERROR:
                # Error occurred
                error_msg = getattr(event.data, "message", "Unknown error")
                log_error(f"Copilot session error: {error_msg}")
                # Set done event to exit wait, exception will be raised below

        # Subscribe to events
        unsubscribe = session.on(on_event)

        try:
            # Send message
            await session.send({"prompt": prompt})

            # Wait for completion with timeout
            try:
                await asyncio.wait_for(done_event.wait(), timeout=self.session_timeout)
            except asyncio.TimeoutError as e:
                raise ModelProviderError(
                    message=f"Copilot session timeout after {self.session_timeout}s",
                    model_name=self.name,
                    model_id=self.id,
                ) from e

            # Assemble response
            model_response.content = "".join(content_parts) if content_parts else None
            model_response.reasoning_content = "".join(reasoning_parts) if reasoning_parts else None
            if tool_calls:
                model_response.tool_calls = tool_calls

            # Extract usage metrics if available
            if usage_data:
                model_response.response_usage = self._parse_usage(usage_data)

            return model_response

        finally:
            # Always unsubscribe
            unsubscribe()

    def _parse_usage(self, usage_data: Any) -> Metrics:
        """
        Parse token usage from Copilot usage data.

        Args:
            usage_data: Usage data from Copilot session event.

        Returns:
            Metrics: Parsed metrics object.
        """
        metrics = Metrics()

        if hasattr(usage_data, "input_tokens"):
            metrics.input_tokens = usage_data.input_tokens
        if hasattr(usage_data, "output_tokens"):
            metrics.output_tokens = usage_data.output_tokens
        if hasattr(usage_data, "cached_input_tokens"):
            metrics.cache_read_tokens = usage_data.cached_input_tokens

        metrics.total_tokens = (metrics.input_tokens or 0) + (metrics.output_tokens or 0)

        return metrics

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
        """
        Async invoke with complete response (non-streaming).

        Args:
            messages: List of conversation messages.
            assistant_message: Message object to track metrics.
            response_format: Optional structured output format (not supported by Copilot SDK).
            tools: Optional list of tool definitions from Agent.
            tool_choice: Optional tool choice strategy. Mapped to SDK's available_tools:
                - "none": Disables all tools
                - "auto": Lets model decide (no restrictions)
                - "required": Forces tool use (no restrictions)
                - {"type": "function", "function": {"name": "x"}}: Restricts to specific tool
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results.

        Returns:
            ModelResponse: Complete model response.

        Raises:
            ModelProviderError: If invocation fails.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            assistant_message.metrics.start_timer()

            client = await self.get_async_client()
            prompt = self._format_messages(messages, compress_tool_results=compress_tool_results)

            # Build session configuration
            session_config = self._build_session_config(streaming=False, tools=tools, tool_choice=tool_choice)

            # Create session
            session = await client.create_session(session_config)  # type: ignore[arg-type]

            try:
                # Collect response from events
                model_response = await self._collect_response_from_events(session, prompt)

                assistant_message.metrics.stop_timer()
                return model_response

            finally:
                await session.destroy()

        except ImportError as e:
            raise ModelProviderError(
                message="GitHub Copilot SDK not installed. Install with: pip install github-copilot-sdk",
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            if isinstance(e, ModelProviderError):
                raise
            raise ModelProviderError(
                message=f"Copilot error: {str(e)}",
                model_name=self.name,
                model_id=self.id,
            ) from e

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
        """
        Async streaming invoke.

        Yields response deltas as they arrive from the Copilot session.

        Args:
            messages: List of conversation messages.
            assistant_message: Message object to track metrics.
            response_format: Optional structured output format (not supported by Copilot SDK).
            tools: Optional list of tool definitions from Agent.
            tool_choice: Optional tool choice strategy. Mapped to SDK's available_tools:
                - "none": Disables all tools
                - "auto": Lets model decide (no restrictions)
                - "required": Forces tool use (no restrictions)
                - {"type": "function", "function": {"name": "x"}}: Restricts to specific tool
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results.

        Yields:
            ModelResponse: Streaming response deltas.

        Raises:
            ModelProviderError: If streaming fails.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        client = await self.get_async_client()
        prompt = self._format_messages(messages, compress_tool_results=compress_tool_results)

        # Build session configuration
        session_config = self._build_session_config(streaming=True, tools=tools, tool_choice=tool_choice)

        session = await client.create_session(session_config)  # type: ignore[arg-type]

        try:
            done_event = asyncio.Event()
            delta_queue: asyncio.Queue = asyncio.Queue()
            # Track tool executions to link start/complete events
            active_tool_executions: Dict[str, ToolExecution] = {}

            def on_event(event: SessionEvent):
                event_type = event.type

                # Yield deltas for streaming content
                if event_type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                    if hasattr(event.data, "delta_content") and event.data.delta_content:
                        delta_response = ModelResponse()
                        delta_response.content = event.data.delta_content
                        asyncio.create_task(delta_queue.put(delta_response))

                elif event_type == SessionEventType.ASSISTANT_REASONING_DELTA:
                    if hasattr(event.data, "delta_content") and event.data.delta_content:
                        delta_response = ModelResponse()
                        delta_response.reasoning_content = event.data.delta_content
                        asyncio.create_task(delta_queue.put(delta_response))

                elif event_type == SessionEventType.TOOL_EXECUTION_START:
                    # Emit tool_call_started event for agent to display
                    if hasattr(event.data, "tool_call_id") and hasattr(event.data, "tool_name"):
                        tool_call_id = event.data.tool_call_id
                        tool_name = event.data.tool_name
                        tool_args = getattr(event.data, "arguments", {})

                        # Type guard to ensure tool_call_id is str
                        if tool_call_id is None:
                            return

                        # Create ToolExecution object
                        tool_execution = ToolExecution(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            tool_args=tool_args,
                        )

                        # Store for later completion
                        active_tool_executions[tool_call_id] = tool_execution

                        # Emit tool_call_started event
                        delta_response = ModelResponse()
                        delta_response.event = ModelResponseEvent.tool_call_started.value
                        delta_response.tool_executions = [tool_execution]
                        asyncio.create_task(delta_queue.put(delta_response))

                elif event_type == SessionEventType.TOOL_EXECUTION_COMPLETE:
                    # Emit tool_call_completed event for agent to display
                    if hasattr(event.data, "tool_call_id"):
                        completed_tool_call_id = event.data.tool_call_id
                        completed_tool_name = getattr(event.data, "tool_name", "unknown")
                        completed_result = getattr(event.data, "result", None)

                        # Type guard to ensure tool_call_id is str
                        if completed_tool_call_id is None:
                            return

                        # Get or create ToolExecution object
                        completed_tool_execution: Optional[ToolExecution] = active_tool_executions.get(
                            completed_tool_call_id
                        )
                        if completed_tool_execution:
                            # Update with result
                            completed_tool_execution.result = str(completed_result) if completed_result else None
                        else:
                            # Create new one if we missed the start event
                            completed_tool_execution = ToolExecution(
                                tool_call_id=completed_tool_call_id,
                                tool_name=completed_tool_name,
                                result=str(completed_result) if completed_result else None,
                            )

                        # Emit tool_call_completed event
                        delta_response = ModelResponse()
                        delta_response.event = ModelResponseEvent.tool_call_completed.value
                        delta_response.tool_executions = [completed_tool_execution]
                        asyncio.create_task(delta_queue.put(delta_response))

                        # Clean up
                        if completed_tool_call_id in active_tool_executions:
                            del active_tool_executions[completed_tool_call_id]

                elif event_type == SessionEventType.SESSION_IDLE:
                    # Signal completion
                    asyncio.create_task(delta_queue.put(None))
                    done_event.set()

                elif event_type == SessionEventType.SESSION_ERROR:
                    error_msg = getattr(event.data, "message", "Unknown error")
                    asyncio.create_task(delta_queue.put(Exception(f"Copilot session error: {error_msg}")))
                    done_event.set()

            # Subscribe to events
            unsubscribe = session.on(on_event)

            try:
                # Send message
                await session.send({"prompt": prompt})

                # Yield deltas as they arrive
                while True:
                    delta = await delta_queue.get()

                    if delta is None:
                        # Completion signal
                        break
                    elif isinstance(delta, Exception):
                        raise ModelProviderError(
                            message=str(delta),
                            model_name=self.name,
                            model_id=self.id,
                        )
                    else:
                        yield delta

                # Wait for final idle confirmation
                try:
                    await asyncio.wait_for(done_event.wait(), timeout=self.session_timeout)
                except asyncio.TimeoutError as e:
                    raise ModelProviderError(
                        message=f"Copilot session timeout after {self.session_timeout}s",
                        model_name=self.name,
                        model_id=self.id,
                    ) from e

            finally:
                unsubscribe()

            assistant_message.metrics.stop_timer()

        finally:
            await session.destroy()

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
        """
        Synchronous invoke wrapper.

        Runs the async ainvoke method using an event loop that is not closed
        after execution, allowing the agent framework to continue processing.

        Args:
            messages: List of conversation messages.
            assistant_message: Message object to track metrics.
            response_format: Optional structured output format (not supported by Copilot SDK).
            tools: Optional list of tool definitions from Agent.
            tool_choice: Optional tool choice strategy. Mapped to SDK's available_tools:
                - "none": Disables all tools
                - "auto": Lets model decide (no restrictions)
                - "required": Forces tool use (no restrictions)
                - {"type": "function", "function": {"name": "x"}}: Restricts to specific tool
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results.

        Returns:
            ModelResponse: Complete model response.
        """
        # Get or create event loop without closing it
        # This allows the agent framework to continue async operations after invoke returns
        try:
            loop = asyncio.get_running_loop()
            # Already in async context - this shouldn't happen for sync invoke
            raise RuntimeError("invoke() called from async context, use ainvoke() instead")
        except RuntimeError:
            # Not in async context, get or create event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        # Run the async function but DON'T close the loop
        return loop.run_until_complete(
            self.ainvoke(
                messages=messages,
                assistant_message=assistant_message,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
            )
        )

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
        """
        Synchronous streaming invoke wrapper.

        Converts the async generator to a synchronous iterator without closing
        the event loop, allowing the agent framework to continue processing.

        Args:
            messages: List of conversation messages.
            assistant_message: Message object to track metrics.
            response_format: Optional structured output format (not supported by Copilot SDK).
            tools: Optional list of tool definitions from Agent.
            tool_choice: Optional tool choice strategy. Mapped to SDK's available_tools:
                - "none": Disables all tools
                - "auto": Lets model decide (no restrictions)
                - "required": Forces tool use (no restrictions)
                - {"type": "function", "function": {"name": "x"}}: Restricts to specific tool
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results.

        Yields:
            ModelResponse: Streaming response deltas.
        """

        async def _async_gen():
            async for response in self.ainvoke_stream(
                messages=messages,
                assistant_message=assistant_message,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
            ):
                yield response

        # Get or create event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Convert async generator to sync - DON'T close the loop
        gen = _async_gen()
        while True:
            try:
                yield loop.run_until_complete(gen.__anext__())
            except StopAsyncIteration:
                break

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        """
        Parse complete response (mostly pass-through for Copilot).

        Args:
            response: The response object to parse.
            **kwargs: Additional parameters.

        Returns:
            ModelResponse: Parsed response.
        """
        if isinstance(response, ModelResponse):
            return response

        # Fallback for direct response object
        model_response = ModelResponse()
        return model_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        """
        Parse streaming delta (mostly pass-through for Copilot).

        Args:
            response: The streaming delta to parse.

        Returns:
            ModelResponse: Parsed delta response.
        """
        if isinstance(response, ModelResponse):
            return response

        model_response = ModelResponse()
        return model_response
