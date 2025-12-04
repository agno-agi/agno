from __future__ import annotations

from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.openai.like import OpenAILike
from agno.utils.log import logger


def is_openai_reasoning_model(reasoning_model: Model) -> bool:
    return (
        (
            reasoning_model.__class__.__name__ == "OpenAIChat"
            or reasoning_model.__class__.__name__ == "OpenAIResponses"
            or reasoning_model.__class__.__name__ == "AzureOpenAI"
        )
        and (
            ("o4" in reasoning_model.id)
            or ("o3" in reasoning_model.id)
            or ("o1" in reasoning_model.id)
            or ("4.1" in reasoning_model.id)
            or ("4.5" in reasoning_model.id)
        )
    ) or (isinstance(reasoning_model, OpenAILike) and "deepseek-r1" in reasoning_model.id.lower())


def get_openai_reasoning(reasoning_agent: "Agent", messages: List[Message], main_run_metrics: Optional[Any] = None) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.agent import RunOutput

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

    # Capture elapsed time from main run right before calling reasoning agent
    reasoning_start_elapsed_time = None
    if main_run_metrics is not None and main_run_metrics.timer is not None:
        reasoning_start_elapsed_time = main_run_metrics.timer.elapsed

    try:
        reasoning_agent_response: RunOutput = reasoning_agent.run(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    # We use the normal content as no reasoning content is returned
    if reasoning_agent_response.content is not None:
        # Extract content between <think> tags if present
        content = reasoning_agent_response.content
        if "<think>" in content and "</think>" in content:
            start_idx = content.find("<think>") + len("<think>")
            end_idx = content.find("</think>")
            reasoning_content = content[start_idx:end_idx].strip()
        else:
            reasoning_content = content

    # Extract metrics from reasoning agent's assistant messages
    reasoning_metrics = None
    if reasoning_agent_response.messages is not None:
        for msg in reversed(reasoning_agent_response.messages):
            if msg.role == "assistant" and msg.metrics is not None:
                reasoning_metrics = msg.metrics
                break

    reasoning_message = Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )
    if reasoning_metrics is not None:
        # Adjust time_to_first_token to be relative to main run start
        adjusted_time_to_first_token = reasoning_metrics.time_to_first_token
        if reasoning_metrics.time_to_first_token is not None and reasoning_start_elapsed_time is not None:
            adjusted_time_to_first_token = reasoning_start_elapsed_time + reasoning_metrics.time_to_first_token
        
        # Create a copy of the metrics to avoid sharing the same object reference
        # This ensures the reasoning message has its own metrics instance
        reasoning_message.metrics = MessageMetrics(
            input_tokens=reasoning_metrics.input_tokens,
            output_tokens=reasoning_metrics.output_tokens,
            total_tokens=reasoning_metrics.total_tokens,
            audio_input_tokens=reasoning_metrics.audio_input_tokens,
            audio_output_tokens=reasoning_metrics.audio_output_tokens,
            audio_total_tokens=reasoning_metrics.audio_total_tokens,
            cache_read_tokens=reasoning_metrics.cache_read_tokens,
            cache_write_tokens=reasoning_metrics.cache_write_tokens,
            reasoning_tokens=reasoning_metrics.reasoning_tokens,
            time_to_first_token=adjusted_time_to_first_token,
            duration=reasoning_metrics.duration,
            # Don't copy the timer - it's specific to the original message context
        )
    
    return reasoning_message


async def aget_openai_reasoning(reasoning_agent: "Agent", messages: List[Message], main_run_metrics: Optional[Any] = None) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.agent import RunOutput

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

    # Capture elapsed time from main run right before calling reasoning agent
    reasoning_start_elapsed_time = None
    if main_run_metrics is not None and main_run_metrics.timer is not None:
        reasoning_start_elapsed_time = main_run_metrics.timer.elapsed

    try:
        reasoning_agent_response: RunOutput = await reasoning_agent.arun(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    if reasoning_agent_response.content is not None:
        # Extract content between <think> tags if present
        content = reasoning_agent_response.content
        if "<think>" in content and "</think>" in content:
            start_idx = content.find("<think>") + len("<think>")
            end_idx = content.find("</think>")
            reasoning_content = content[start_idx:end_idx].strip()
        else:
            reasoning_content = content

    # Extract metrics from reasoning agent's assistant messages
    reasoning_metrics = None
    if reasoning_agent_response.messages is not None:
        for msg in reversed(reasoning_agent_response.messages):
            if msg.role == "assistant" and msg.metrics is not None:
                reasoning_metrics = msg.metrics
                break

    reasoning_message = Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )
    if reasoning_metrics is not None:
        # Adjust time_to_first_token to be relative to main run start
        adjusted_time_to_first_token = reasoning_metrics.time_to_first_token
        if reasoning_metrics.time_to_first_token is not None and reasoning_start_elapsed_time is not None:
            adjusted_time_to_first_token = reasoning_start_elapsed_time + reasoning_metrics.time_to_first_token
        
        # Create a copy of the metrics to avoid sharing the same object reference
        # This ensures the reasoning message has its own metrics instance
        reasoning_message.metrics = MessageMetrics(
            input_tokens=reasoning_metrics.input_tokens,
            output_tokens=reasoning_metrics.output_tokens,
            total_tokens=reasoning_metrics.total_tokens,
            audio_input_tokens=reasoning_metrics.audio_input_tokens,
            audio_output_tokens=reasoning_metrics.audio_output_tokens,
            audio_total_tokens=reasoning_metrics.audio_total_tokens,
            cache_read_tokens=reasoning_metrics.cache_read_tokens,
            cache_write_tokens=reasoning_metrics.cache_write_tokens,
            reasoning_tokens=reasoning_metrics.reasoning_tokens,
            time_to_first_token=adjusted_time_to_first_token,
            duration=reasoning_metrics.duration,
            # Don't copy the timer - it's specific to the original message context
        )
    
    return reasoning_message
