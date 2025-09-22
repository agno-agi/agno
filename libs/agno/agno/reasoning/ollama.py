from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


def is_ollama_reasoning_model(reasoning_model: Model) -> bool:
    return reasoning_model.__class__.__name__ == "Ollama" and (
        "qwq" in reasoning_model.id
        or "deepseek-r1" in reasoning_model.id
        or "qwen2.5-coder" in reasoning_model.id
        or "openthinker" in reasoning_model.id
        or "gpt-oss" in reasoning_model.id
    )


def get_ollama_reasoning_agent(
    reasoning_model: Model,
    telemetry: bool = False,
    debug_mode: bool = False,
    debug_level: Literal[1, 2] = 1,
    session_state: Optional[Dict[str, Any]] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "Agent":  # type: ignore  # noqa: F821
    """
    Create a specialized reasoning agent for Ollama models that encourages natural reasoning.
    
    Unlike the default reasoning agent, this doesn't force structured JSON output
    and instead optimizes for the natural reasoning capabilities of models like GPT-OSS.
    """
    from agno.agent import Agent

    return Agent(
        model=reasoning_model,
        description="You are an expert reasoning assistant who thinks step-by-step through problems.",
        instructions=(
            "Think through problems carefully and systematically. "
            "Show your reasoning process clearly with numbered steps. "
            "Include multiple approaches when helpful. "
            "Use mathematical notation where appropriate. "
            "Validate your answers through different methods when possible."
        ),
        telemetry=telemetry,
        debug_mode=debug_mode,
        debug_level=debug_level,
        session_state=session_state,
        dependencies=dependencies,
        metadata=metadata,
        # Critically: NO output_schema to allow natural reasoning
    )


def get_ollama_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """
    Get reasoning from Ollama models like GPT-OSS that have native reasoning capabilities.
    
    These models reason naturally without structured JSON constraints and produce
    high-quality step-by-step reasoning when given simple, direct prompts.
    """
    from agno.run.agent import RunOutput

    try:
        # Use the reasoning agent without structured output constraints
        # The agent should be created without output_schema to allow natural reasoning
        reasoning_agent_response: RunOutput = reasoning_agent.run(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    if reasoning_agent_response.content is None:
        logger.warning("No reasoning content received from Ollama model")
        return None

    # GPT-OSS and similar models produce natural reasoning without special tags
    # They don't use <think> tags - they reason directly in their response
    reasoning_content = str(reasoning_agent_response.content).strip()
    
    # Log the reasoning quality for debugging
    logger.debug(f"Ollama reasoning content length: {len(reasoning_content)} characters")
    
    if not reasoning_content:
        logger.warning("Empty reasoning content from Ollama model")
        return None

    return Message(
        role="assistant", 
        content=f"<thinking>\n{reasoning_content}\n</thinking>", 
        reasoning_content=reasoning_content
    )


async def aget_ollama_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """
    Async version of get_ollama_reasoning.
    
    Get reasoning from Ollama models like GPT-OSS that have native reasoning capabilities.
    """
    from agno.run.agent import RunOutput

    try:
        # Use the reasoning agent without structured output constraints
        reasoning_agent_response: RunOutput = await reasoning_agent.arun(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    if reasoning_agent_response.content is None:
        logger.warning("No reasoning content received from Ollama model")
        return None

    # GPT-OSS and similar models produce natural reasoning without special tags
    reasoning_content = str(reasoning_agent_response.content).strip()
    
    # Log the reasoning quality for debugging
    logger.debug(f"Ollama reasoning content length: {len(reasoning_content)} characters")
    
    if not reasoning_content:
        logger.warning("Empty reasoning content from Ollama model")
        return None

    return Message(
        role="assistant", 
        content=f"<thinking>\n{reasoning_content}\n</thinking>", 
        reasoning_content=reasoning_content
    )