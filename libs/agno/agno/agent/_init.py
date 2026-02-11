"""Initialization helpers for Agent."""

from __future__ import annotations

from os import getenv
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Literal,
    Optional,
    Sequence,
    Union,
    cast,
)

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.compression.manager import CompressionManager
from agno.culture.manager import CultureManager
from agno.db.base import AsyncBaseDb
from agno.learn.machine import LearningMachine
from agno.memory import MemoryManager
from agno.models.utils import get_model
from agno.session import SessionSummaryManager
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import (
    log_debug,
    log_exception,
    log_info,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)
from agno.utils.safe_formatter import SafeFormatter
from agno.utils.string import generate_id_from_name


def set_id(agent: Agent) -> None:
    if agent.id is None:
        agent.id = generate_id_from_name(agent.name)


def set_debug(agent: Agent, debug_mode: Optional[bool] = None) -> None:
    # Get the debug level from the environment variable or the default debug level
    debug_level: Literal[1, 2] = (
        cast(Literal[1, 2], int(env)) if (env := getenv("AGNO_DEBUG_LEVEL")) in ("1", "2") else agent.debug_level
    )
    # If the default debug mode is set, or passed on run, or via environment variable, set the debug mode to True
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
    # Use the default Model (OpenAIChat) if no model is provided
    if agent.model is None:
        try:
            from agno.models.openai import OpenAIChat
        except ModuleNotFoundError as e:
            log_exception(e)
            raise ImportError(
                "Agno agents use `openai` as the default model provider. Please provide a `model` or install `openai`."
            ) from e

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
    agent._learning_init_attempted = True

    # Handle learning=False or learning=None
    if agent.learning is None or agent.learning is False:
        agent._learning = None
        return

    # Check db requirement
    if agent.db is None:
        log_warning("Database not provided. LearningMachine not initialized.")
        agent._learning = None
        return

    # Handle learning=True: create default LearningMachine
    # Enables user_profile (structured fields) and user_memory (unstructured observations)
    if agent.learning is True:
        agent._learning = LearningMachine(db=agent.db, model=agent.model, user_profile=True, user_memory=True)
        return

    # Handle learning=LearningMachine(...): inject dependencies
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

    # Check compression flag on the compression manager
    if agent.compression_manager is not None and agent.compression_manager.compress_tool_results:
        agent.compress_tool_results = True


def _initialize_session_state(
    session_state: Dict[str, Any],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Inject current_user_id, current_session_id, and current_run_id into session_state.

    These transient values are stripped before persisting to the database (see _session.py)
    but must be available at runtime so that tool functions and instruction templates can
    reference them.  Teams and Workflows already do this; this brings Agents to parity.
    """
    if user_id:
        session_state["current_user_id"] = user_id
    if session_id is not None:
        session_state["current_session_id"] = session_id
    if run_id is not None:
        session_state["current_run_id"] = run_id
    return session_state


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


def initialize_agent(agent: Agent, debug_mode: Optional[bool] = None) -> None:
    set_default_model(agent)
    set_debug(agent, debug_mode=debug_mode)
    set_id(agent)
    set_telemetry(agent)
    if agent.update_memory_on_run or agent.enable_agentic_memory or agent.memory_manager is not None:
        set_memory_manager(agent)
    if (
        agent.add_culture_to_context
        or agent.update_cultural_knowledge
        or agent.enable_agentic_culture
        or agent.culture_manager is not None
    ):
        set_culture_manager(agent)
    if agent.enable_session_summaries or agent.session_summary_manager is not None:
        set_session_summary_manager(agent)
    if agent.compress_tool_results or agent.compression_manager is not None:
        set_compression_manager(agent)
    if agent.learning is not None and agent.learning is not False:
        set_learning_machine(agent)

    log_debug(f"Agent ID: {agent.id}", center=True)

    if agent._formatter is None:
        agent._formatter = SafeFormatter()


def add_tool(agent: Agent, tool: Union[Toolkit, Callable, Function, Dict]) -> None:
    from agno.utils.callables import is_callable_factory

    if is_callable_factory(agent.tools, excluded_types=(Toolkit, Function)):
        raise RuntimeError(
            "Cannot add_tool() when tools is a callable factory. Use set_tools() to replace the factory."
        )
    if not agent.tools:
        agent.tools = []
    agent.tools.append(tool)  # type: ignore[union-attr]


def set_tools(agent: Agent, tools: Union[Sequence[Union[Toolkit, Callable, Function, Dict]], Callable]) -> None:
    from agno.utils.callables import is_callable_factory

    if is_callable_factory(tools, excluded_types=(Toolkit, Function)):
        agent.tools = tools  # type: ignore[assignment]
        agent._callable_tools_cache.clear()
    else:
        agent.tools = list(tools) if tools else []  # type: ignore[arg-type]


async def connect_mcp_tools(agent: Agent) -> None:
    """Connect the MCP tools to the agent."""
    if agent.tools and isinstance(agent.tools, list):
        for tool in agent.tools:
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if (
                hasattr(type(tool), "__mro__")
                and any(c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__)
                and not tool.initialized  # type: ignore
            ):
                try:
                    # Connect the MCP server
                    await tool.connect()  # type: ignore
                    agent._mcp_tools_initialized_on_run.append(tool)  # type: ignore
                except Exception as e:
                    log_warning(f"Error connecting tool: {str(e)}")


async def disconnect_mcp_tools(agent: Agent) -> None:
    """Disconnect the MCP tools from the agent."""
    for tool in agent._mcp_tools_initialized_on_run:
        try:
            await tool.close()
        except Exception as e:
            log_warning(f"Error disconnecting tool: {str(e)}")
    agent._mcp_tools_initialized_on_run = []


def connect_connectable_tools(agent: Agent) -> None:
    """Connect tools that require connection management (e.g., database connections)."""
    if agent.tools and isinstance(agent.tools, list):
        for tool in agent.tools:
            if (
                hasattr(tool, "requires_connect")
                and tool.requires_connect  # type: ignore
                and hasattr(tool, "connect")
                and tool not in agent._connectable_tools_initialized_on_run
            ):
                try:
                    tool.connect()  # type: ignore
                    agent._connectable_tools_initialized_on_run.append(tool)
                except Exception as e:
                    log_warning(f"Error connecting tool: {str(e)}")


def disconnect_connectable_tools(agent: Agent) -> None:
    """Disconnect tools that require connection management."""
    for tool in agent._connectable_tools_initialized_on_run:
        if hasattr(tool, "close"):
            try:
                tool.close()  # type: ignore
            except Exception as e:
                log_warning(f"Error disconnecting tool: {str(e)}")
    agent._connectable_tools_initialized_on_run = []
