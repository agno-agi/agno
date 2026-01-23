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
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug, log_error

try:
    from copilot import CopilotClient, CopilotSession, SessionEvent, Tool, ToolInvocation, ToolResult
    from copilot.generated.session_events import SessionEventType
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
    id: str = "gpt-4o"  # Default Copilot model
    name: str = "CopilotChat"
    provider: str = "GitHub Copilot"

    # Client configuration
    cli_path: str = "copilot"  # Path to copilot CLI executable
    cli_url: Optional[str] = None  # Optional CLI URL
    use_stdio: bool = True  # Use stdio for communication
    log_level: str = "info"  # Logging level for SDK
    session_timeout: float = 60.0  # Session timeout in seconds

    # Cached client
    _client: Optional[CopilotClient] = field(default=None, init=False, repr=False)
    _client_started: bool = field(default=False, init=False, repr=False)
    _tool_registry: Dict[str, Dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    async def get_async_client(self) -> CopilotClient:
        """
        Get or create cached async client.

        Returns:
            CopilotClient: The Copilot client instance.

        Raises:
            ModelProviderError: If client creation or startup fails.
        """
        if self._client is not None and self._client_started:
            return self._client

        try:
            log_debug(f"Creating new GitHub Copilot client for model {self.id}")

            # Create client configuration
            client_config = {
                "use_stdio": self.use_stdio,
                "log_level": self.log_level,
            }

            # Add optional parameters
            if self.cli_path:
                client_config["cli_path"] = self.cli_path
            if self.cli_url:
                client_config["cli_url"] = self.cli_url

            # Create and start client
            self._client = CopilotClient(client_config)
            await self._client.start()
            self._client_started = True

            return self._client

        except FileNotFoundError as e:
            raise ModelProviderError(
                message=f"Copilot CLI not found at '{self.cli_path}'. "
                "Ensure GitHub Copilot CLI is installed and available in PATH.",
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
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

    def _format_messages(self, messages: List[Message]) -> str:
        """
        Convert Agno Messages to Copilot prompt string.

        Args:
            messages: List of Agno Message objects.

        Returns:
            str: Formatted prompt string for Copilot.
        """
        parts = []
        for msg in messages:
            role = msg.role
            content = msg.content or ""

            if role == "system":
                parts.append(f"System: {content}")
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                parts.append(f"Tool result: {content}")

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
        copilot_tools = []

        # Clear registry for this request
        self._tool_registry = {}

        for tool_dict in tools:
            if tool_dict.get("type") != "function":
                continue

            func_def = tool_dict.get("function", {})
            tool_name = func_def.get("name")

            if not tool_name:
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
            copilot_tool = Tool(
                name=tool_name,
                description=func_def.get("description", ""),
                handler=tool_handler,
                parameters=func_def.get("parameters", {}),
            )
            copilot_tools.append(copilot_tool)

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
        tool_calls = []
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
                    tool_calls.append(
                        {
                            "id": event.data.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": event.data.tool_name,
                                "arguments": json.dumps(getattr(event.data, "arguments", {})),
                            },
                        }
                    )

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
            model_response.tool_calls = tool_calls if tool_calls else None

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
            response_format: Optional structured output format (not fully supported).
            tools: Optional list of tool definitions.
            tool_choice: Optional tool choice strategy (not fully supported).
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results (not used).

        Returns:
            ModelResponse: Complete model response.

        Raises:
            ModelProviderError: If invocation fails.
        """
        try:
            assistant_message.metrics.start_timer()

            client = await self.get_async_client()
            prompt = self._format_messages(messages)

            # Create session config
            session_config = {
                "model": self.id,
                "streaming": False,  # Non-streaming for ainvoke
            }

            # Add tools if provided
            if tools:
                copilot_tools = self._convert_tools(tools)
                if copilot_tools:
                    session_config["tools"] = copilot_tools

            # Create session
            session = await client.create_session(session_config)

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
            response_format: Optional structured output format (not fully supported).
            tools: Optional list of tool definitions.
            tool_choice: Optional tool choice strategy (not fully supported).
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results (not used).

        Yields:
            ModelResponse: Streaming response deltas.

        Raises:
            ModelProviderError: If streaming fails.
        """
        client = await self.get_async_client()
        prompt = self._format_messages(messages)

        session_config = {
            "model": self.id,
            "streaming": True,  # Enable streaming
        }

        if tools:
            copilot_tools = self._convert_tools(tools)
            if copilot_tools:
                session_config["tools"] = copilot_tools

        session = await client.create_session(session_config)

        try:
            done_event = asyncio.Event()
            delta_queue: asyncio.Queue = asyncio.Queue()

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
            response_format: Optional structured output format (not fully supported).
            tools: Optional list of tool definitions.
            tool_choice: Optional tool choice strategy (not fully supported).
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results (not used).

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
            response_format: Optional structured output format (not fully supported).
            tools: Optional list of tool definitions.
            tool_choice: Optional tool choice strategy (not fully supported).
            run_response: Optional run output for context.
            compress_tool_results: Whether to compress tool results (not used).

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
