"""Agent setup helpers extracted for readability without mixin abstraction."""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING, Literal, Optional, cast

from agno.compression.manager import CompressionManager
from agno.culture.manager import CultureManager
from agno.db.base import AsyncBaseDb
from agno.learn.machine import LearningMachine
from agno.memory import MemoryManager
from agno.models.utils import get_model
from agno.session import SessionSummaryManager
from agno.utils.log import (
    log_debug,
    log_error,
    log_exception,
    log_info,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)
from agno.utils.safe_formatter import SafeFormatter

if TYPE_CHECKING:
    from agno.agent.agent import Agent


def set_debug(agent: Agent, debug_mode: Optional[bool] = None) -> None:
    debug_level: Literal[1, 2] = (
        cast(Literal[1, 2], int(env)) if (env := getenv("AGNO_DEBUG_LEVEL")) in ("1", "2") else agent.debug_level
    )
    if agent.debug_mode or debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
        set_log_level_to_debug(level=debug_level)
    else:
        set_log_level_to_info()


def set_telemetry(agent: Agent) -> None:
    """Override telemetry settings based on environment variables."""
    telemetry_env = getenv("AGNO_TELEMETRY")
    if telemetry_env is not None:
        agent.telemetry = telemetry_env.lower() == "true"


def set_default_model(agent: Agent) -> None:
    if agent.model is None:
        try:
            from agno.models.openai import OpenAIChat
        except ModuleNotFoundError as e:
            log_exception(e)
            log_error(
                "Agno agents use `openai` as the default model provider. Please provide a `model` or install `openai`."
            )
            exit(1)

        log_info("Setting default model to OpenAI Chat")
        agent.model = OpenAIChat(id="gpt-4o")


def set_culture_manager(agent: Agent) -> None:
    if agent.db is None:
        log_warning("Database not provided. Cultural knowledge will not be stored.")

    if agent.culture_manager is None:
        agent.culture_manager = CultureManager(model=agent.model, db=agent.db)
    else:
        if agent.culture_manager.model is None:
            agent.culture_manager.model = agent.model
        if agent.culture_manager.db is None:
            agent.culture_manager.db = agent.db

    if agent.add_culture_to_context is None:
        agent.add_culture_to_context = (
            agent.enable_agentic_culture or agent.update_cultural_knowledge or agent.culture_manager is not None
        )


def set_memory_manager(agent: Agent) -> None:
    if agent.db is None:
        log_warning("Database not provided. Memories will not be stored.")

    if agent.memory_manager is None:
        agent.memory_manager = MemoryManager(model=agent.model, db=agent.db)
    else:
        if agent.memory_manager.model is None:
            agent.memory_manager.model = agent.model
        if agent.memory_manager.db is None:
            agent.memory_manager.db = agent.db

    if agent.add_memories_to_context is None:
        agent.add_memories_to_context = (
            agent.update_memory_on_run or agent.enable_agentic_memory or agent.memory_manager is not None
        )


def set_learning_machine(agent: Agent) -> None:
    """Initialize LearningMachine with agent's db and model.

    Sets the internal _learning field without modifying the public learning field.

    Handles:
    - learning=True: Create default LearningMachine
    - learning=False/None: Disabled
    - learning=LearningMachine(...): Use provided, inject db/model/knowledge
    """
    if agent.learning is None or agent.learning is False:
        agent._learning = None
        return

    if agent.db is None:
        log_warning("Database not provided. LearningMachine not initialized.")
        agent._learning = None
        return

    if agent.learning is True:
        agent._learning = LearningMachine(db=agent.db, model=agent.model, user_profile=True, user_memory=True)
        return

    if isinstance(agent.learning, LearningMachine):
        if agent.learning.db is None:
            agent.learning.db = agent.db
        if agent.learning.model is None:
            agent.learning.model = agent.model
        agent._learning = agent.learning


def set_session_summary_manager(agent: Agent) -> None:
    if agent.enable_session_summaries and agent.session_summary_manager is None:
        agent.session_summary_manager = SessionSummaryManager(model=agent.model)

    if agent.session_summary_manager is not None:
        if agent.session_summary_manager.model is None:
            agent.session_summary_manager.model = agent.model

    if agent.add_session_summary_to_context is None:
        agent.add_session_summary_to_context = (
            agent.enable_session_summaries or agent.session_summary_manager is not None
        )


def set_compression_manager(agent: Agent) -> None:
    if agent.compress_tool_results and agent.compression_manager is None:
        agent.compression_manager = CompressionManager(
            model=agent.model,
        )

    if agent.compression_manager is not None and agent.compression_manager.model is None:
        agent.compression_manager.model = agent.model

    if agent.compression_manager is not None and agent.compression_manager.compress_tool_results:
        agent.compress_tool_results = True


def has_async_db(agent: Agent) -> bool:
    """Return True if the db the agent is equipped with is an Async implementation."""
    return agent.db is not None and isinstance(agent.db, AsyncBaseDb)


def get_models(agent: Agent) -> None:
    if agent.model is not None:
        agent.model = get_model(agent.model)
    if agent.reasoning_model is not None:
        agent.reasoning_model = get_model(agent.reasoning_model)
    if agent.parser_model is not None:
        agent.parser_model = get_model(agent.parser_model)
    if agent.output_model is not None:
        agent.output_model = get_model(agent.output_model)

    if agent.compression_manager is not None and agent.compression_manager.model is None:
        agent.compression_manager.model = agent.model


def ensure_formatter(agent: Agent) -> None:
    if agent._formatter is None:
        agent._formatter = SafeFormatter()


def log_agent_id(agent: Agent) -> None:
    log_debug(f"Agent ID: {agent.id}", center=True)
