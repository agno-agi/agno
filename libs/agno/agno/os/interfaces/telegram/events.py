import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional, Union

from agno.os.interfaces.telegram.helpers import (
    TG_MAX_MESSAGE_LENGTH,
    edit_html,
    send_chunked,
    send_html,
)
from agno.run.agent import ReasoningStartedEvent as AgentReasoningStartedEvent
from agno.run.agent import RunCompletedEvent as AgentRunCompletedEvent
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.agent import RunErrorEvent as AgentRunErrorEvent
from agno.run.agent import RunOutput
from agno.run.agent import ToolCallCompletedEvent as AgentToolCallCompletedEvent
from agno.run.agent import ToolCallStartedEvent as AgentToolCallStartedEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import TeamRunOutput
from agno.run.team import ToolCallCompletedEvent as TeamToolCallCompletedEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent
from agno.run.workflow import (
    LoopIterationStartedEvent,
    ParallelExecutionStartedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
)
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

TG_STREAM_EDIT_INTERVAL = 1.0  # Minimum seconds between message edits to avoid rate limits


async def stream_to_telegram(
    bot: "AsyncTeleBot",
    event_stream: AsyncIterator[Any],
    chat_id: int,
    reply_to: Optional[int],
    message_thread_id: Optional[int] = None,
    is_team: bool = False,
    error_message: str = "",
) -> Optional[Union[RunOutput, TeamRunOutput]]:
    sent_message_id: Optional[int] = None
    accumulated_content = ""
    status_lines: list[str] = []
    last_edit_time = 0.0
    final_run_output: Optional[Union[RunOutput, TeamRunOutput]] = None

    def _build_display_text() -> str:
        parts: list[str] = []
        if status_lines:
            parts.append("\n".join(status_lines))
        if accumulated_content:
            parts.append(accumulated_content)
        return "\n\n".join(parts)

    async def _send_or_edit(text: str) -> None:
        nonlocal sent_message_id, last_edit_time
        display = text[:TG_MAX_MESSAGE_LENGTH]
        if sent_message_id is None:
            msg = await send_html(
                bot, chat_id, display, reply_to_message_id=reply_to, message_thread_id=message_thread_id
            )
            sent_message_id = msg.message_id
        else:
            await edit_html(bot, display, chat_id, sent_message_id)
        last_edit_time = time.monotonic()

    async def _flush_display() -> None:
        try:
            await _send_or_edit(_build_display_text())
        except Exception as e:
            log_warning(f"Stream display update failed: {e}")

    async for event in event_stream:
        # Agent/Team final output
        if isinstance(event, (RunOutput, TeamRunOutput)):
            final_run_output = event
            continue

        # Workflow step events
        if isinstance(event, StepStartedEvent):
            step_name = event.step_name or "unknown"
            status_lines.append(f"> Running step: {step_name}...")
            await _flush_display()
            continue

        if isinstance(event, StepCompletedEvent):
            step_name = event.step_name or "unknown"
            for i, line in enumerate(status_lines):
                if f"Running step: {step_name}..." in line:
                    status_lines[i] = f"> Completed step: {step_name}"
                    break
            if event.content:
                accumulated_content = str(event.content)
            await _flush_display()
            continue

        if isinstance(event, ParallelExecutionStartedEvent):
            count = event.parallel_step_count or 0
            status_lines.append(f"> Running {count} steps in parallel...")
            await _flush_display()
            continue

        if isinstance(event, LoopIterationStartedEvent):
            step_name = event.step_name or "loop"
            iteration = event.iteration
            max_iter = event.max_iterations
            if max_iter:
                status_lines.append(f"> {step_name}: iteration {iteration}/{max_iter}...")
            else:
                status_lines.append(f"> {step_name}: iteration {iteration}...")
            await _flush_display()
            continue

        if isinstance(event, WorkflowCompletedEvent):
            if event.content:
                accumulated_content = str(event.content)
            continue

        if isinstance(event, WorkflowErrorEvent):
            accumulated_content = f"Error: {event.error or 'Unknown error'}"
            continue

        # Agent/Team run error — model failures, invalid input, etc.
        if isinstance(event, (AgentRunErrorEvent, TeamRunErrorEvent)):
            log_error(f"Run error during stream: {event.content or 'Unknown error'}")
            accumulated_content = error_message
            break

        # Tool call started
        if isinstance(event, (AgentToolCallStartedEvent, TeamToolCallStartedEvent)):
            tool_name = event.tool.tool_name if event.tool else None
            if tool_name:
                agent_label = ""
                if is_team and isinstance(event, AgentToolCallStartedEvent) and event.agent_name:
                    agent_label = f"[{event.agent_name}] "
                status_lines.append(f"> {agent_label}Using {tool_name}...")
                await _flush_display()
            else:
                try:
                    await bot.send_chat_action(chat_id, "typing", message_thread_id=message_thread_id)
                except Exception:
                    pass
            continue

        if isinstance(event, (AgentReasoningStartedEvent, TeamReasoningStartedEvent)):
            status_lines.append("> Reasoning...")
            await _flush_display()
            continue

        # Tool call completed
        if isinstance(event, (AgentToolCallCompletedEvent, TeamToolCallCompletedEvent)):
            tool_name = event.tool.tool_name if event.tool else None
            if tool_name:
                for i, line in enumerate(status_lines):
                    if f"Using {tool_name}..." in line:
                        status_lines[i] = line.replace(f"Using {tool_name}...", f"Used {tool_name}")
                        break
                await _flush_display()
            continue

        # Content deltas
        if isinstance(event, (AgentRunContentEvent, TeamRunContentEvent)) and event.content:
            accumulated_content += str(event.content)

            now = time.monotonic()
            if now - last_edit_time < TG_STREAM_EDIT_INTERVAL:
                continue

            try:
                await _send_or_edit(_build_display_text())
            except Exception as e:
                log_warning(f"Stream edit failed (will retry on next chunk): {e}")

        # RunCompleted carries the final content — replace accumulated
        elif isinstance(event, (AgentRunCompletedEvent, TeamRunCompletedEvent)):
            if event.content:
                accumulated_content = str(event.content)

    if accumulated_content and sent_message_id:
        try:
            if len(accumulated_content) <= TG_MAX_MESSAGE_LENGTH:
                await edit_html(bot, accumulated_content, chat_id, sent_message_id)
            else:
                try:
                    await bot.delete_message(chat_id, sent_message_id)
                except Exception:
                    pass
                await send_chunked(
                    bot, chat_id, accumulated_content, reply_to_message_id=reply_to, message_thread_id=message_thread_id
                )
        except Exception as e:
            log_warning(f"Final stream edit failed: {e}")
    elif accumulated_content and not sent_message_id:
        await send_chunked(
            bot, chat_id, accumulated_content, reply_to_message_id=reply_to, message_thread_id=message_thread_id
        )

    return final_run_output
