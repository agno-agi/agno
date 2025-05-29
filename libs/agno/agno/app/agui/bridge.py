"""
AG-UI Protocol Bridge for Agno Agents

This module provides the bridge between AG-UI protocol and Agno agents,
enabling frontend tool execution and proper event streaming.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from ag_ui.core import (
    AssistantMessage,
    BaseEvent,
    EventType,
    Message,
    MessagesSnapshotEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    SystemMessage,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    Tool,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    UserMessage,
)
from ag_ui.encoder import EventEncoder

from agno.agent.agent import Agent
from agno.run.response import RunResponse


class AGUIBridge:
    """Bridge between AG-UI protocol and Agno agents"""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.frontend_tools: Dict[str, Tool] = {}
        self.pending_tool_calls: Dict[str, asyncio.Future] = {}
        self.run_id: Optional[str] = None
        self.thread_id: Optional[str] = None
        self.logger = logging.getLogger(__name__)

    async def run_agent(self, input: RunAgentInput) -> AsyncGenerator[BaseEvent, None]:
        """
        Run the agent with AG-UI protocol support.

        This method handles the full lifecycle of an agent run, including:
        - Starting the run
        - Streaming text responses
        - Handling tool calls (including frontend tools)
        - Managing state
        - Finishing the run
        """
        self.run_id = input.run_id or str(uuid.uuid4())
        self.thread_id = input.thread_id or str(uuid.uuid4())

        self.logger.debug(f"Starting AG-UI run - run_id: {self.run_id}, thread_id: {self.thread_id}")

        # Store frontend tools if provided
        if input.tools:
            for tool in input.tools:
                self.frontend_tools[tool.name] = tool

        # Emit run started event
        self.logger.debug("Emitting RunStartedEvent")
        yield RunStartedEvent(
            type=EventType.RUN_STARTED,
            runId=self.run_id,
            threadId=self.thread_id,
        )

        try:
            # Convert AG-UI messages to Agno format
            agno_messages = self._convert_messages(input.messages) if input.messages else []

            # Extract user message if present
            user_message = None
            if agno_messages and agno_messages[-1]["role"] == "user":
                user_message = agno_messages[-1]["content"]
                agno_messages = agno_messages[:-1]  # Remove the last user message

            self.logger.debug(f"User message: {user_message}")
            self.logger.debug(f"Previous messages: {agno_messages}")

            # Run the agent
            async for event in self._run_agent_stream(
                user_message=user_message,
                previous_messages=agno_messages,
                run_id=self.run_id,
            ):
                yield event

            # Emit run finished event
            self.logger.debug("Emitting RunFinishedEvent")
            yield RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                runId=self.run_id,
                threadId=self.thread_id,
            )

        except Exception as e:
            self.logger.error(f"Error in run_agent: {e}", exc_info=True)
            # Emit error event
            yield self.create_error_event(str(e))

    def create_error_event(self, error_message: str) -> RunErrorEvent:
        """Create an error event"""
        return RunErrorEvent(
            type=EventType.RUN_ERROR,
            message=error_message,
        )

    async def _run_agent_stream(
        self,
        user_message: str,
        previous_messages: List[Dict[str, Any]],
        run_id: str,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Run the agent and stream responses as AG-UI events."""
        # Debug logging
        self.logger.debug(f"_run_agent_stream called with user_message: {user_message}")

        # Handle None or empty user_message - don't run the agent for empty messages
        if not user_message or user_message.strip() == "":
            self.logger.warning("User message is None or empty, skipping agent execution")
            return

        try:
            # Create AG-UI compatible messages
            messages = []

            # Add previous messages
            for msg in previous_messages:
                if msg["role"] == "user":
                    messages.append(UserMessage(id=str(uuid.uuid4()), role="user", content=msg["content"] or ""))
                elif msg["role"] == "assistant":
                    messages.append(
                        AssistantMessage(id=str(uuid.uuid4()), role="assistant", content=msg["content"] or "")
                    )
                elif msg["role"] == "system":
                    messages.append(SystemMessage(id=str(uuid.uuid4()), role="system", content=msg["content"] or ""))

            # Add the current user message if not empty
            if user_message:
                messages.append(UserMessage(id=str(uuid.uuid4()), role="user", content=user_message))

            # Run the agent
            self.logger.debug(f"Running agent with message: {user_message}")
            message_id = str(uuid.uuid4())

            # Emit message start event
            self.logger.debug(f"Emitting TextMessageStartEvent - message_id: {message_id}")
            yield TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, messageId=message_id, role="assistant")

            # Start the agent stream
            self.logger.debug("Starting agent.arun stream")

            try:
                # Check if streaming is supported
                if hasattr(self.agent, "arun_stream"):
                    # Use streaming method if available
                    response_stream = self.agent.arun_stream(user_message, run_id=run_id)

                    full_content = ""
                    async for chunk in response_stream:
                        self.logger.debug(f"Got chunk from agent: {chunk}")

                        if hasattr(chunk, "content") and chunk.content:
                            # Stream content character by character for true streaming effect
                            content_to_stream = chunk.content

                            # If we've already sent this part of the content, skip it
                            if content_to_stream.startswith(full_content):
                                new_content = content_to_stream[len(full_content) :]
                            else:
                                new_content = content_to_stream

                            # Stream each character
                            for char in new_content:
                                yield TextMessageContentEvent(
                                    type=EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=char
                                )
                                # Small delay between characters for visible streaming effect
                                await asyncio.sleep(0.01)

                            full_content += new_content
                        elif isinstance(chunk, str):
                            # Stream string content character by character
                            for char in chunk:
                                yield TextMessageContentEvent(
                                    type=EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=char
                                )
                                await asyncio.sleep(0.01)
                            full_content += chunk
                else:
                    # Use non-streaming method
                    self.logger.debug("Agent doesn't support streaming, using non-streaming response")
                    response = await self.agent.arun(user_message, run_id=run_id)
                    self.logger.debug(f"Got response: {response}")

                    if hasattr(response, "content") and response.content:
                        # Stream the content character by character
                        for char in response.content:
                            yield TextMessageContentEvent(
                                type=EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=char
                            )
                            # Small delay between characters for visible streaming effect
                            await asyncio.sleep(0.01)
                    elif isinstance(response, str):
                        # Handle string response
                        for char in response:
                            yield TextMessageContentEvent(
                                type=EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=char
                            )
                            await asyncio.sleep(0.01)

            except Exception as e:
                self.logger.error(f"Error running agent: {e}", exc_info=True)
                # Try without streaming if stream fails
                try:
                    response = await self.agent.arun(user_message, run_id=run_id)
                    if hasattr(response, "content") and response.content:
                        for char in response.content:
                            yield TextMessageContentEvent(
                                type=EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=char
                            )
                            await asyncio.sleep(0.01)
                    elif isinstance(response, str):
                        for char in response:
                            yield TextMessageContentEvent(
                                type=EventType.TEXT_MESSAGE_CONTENT, messageId=message_id, delta=char
                            )
                            await asyncio.sleep(0.01)
                except Exception as inner_e:
                    self.logger.error(f"Error in fallback non-streaming: {inner_e}", exc_info=True)
                    raise inner_e

            # Emit message end event
            yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, messageId=message_id)

        except Exception as e:
            self.logger.error(f"Error in _run_agent_stream: {e}", exc_info=True)
            yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert AG-UI messages to Agno format"""
        converted = []
        for msg in messages:
            # Skip CopilotKit's default system messages - let the agent use its own instructions
            if msg.role == "system" and msg.content and "efficient, competent, conscientious" in msg.content:
                self.logger.debug("Filtering out CopilotKit system message")
                continue

            converted.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                }
            )
        return converted

    async def handle_tool_result(self, tool_call_id: str, result: Any) -> None:
        """Handle a tool result from the frontend"""
        if tool_call_id in self.pending_tool_calls:
            future = self.pending_tool_calls[tool_call_id]
            future.set_result(result)
            del self.pending_tool_calls[tool_call_id]
        else:
            raise ValueError(f"Unknown tool call ID: {tool_call_id}")
