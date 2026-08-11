"""Grouped configuration objects for Agent, Team and Workflow parameters.

Each config groups a cluster of related constructor parameters behind a single
object. The flat parameters remain fully supported: passing a config object is
equivalent to passing the corresponding flat parameters, and when both are
provided the config object wins (a warning is logged, mirroring the
fallback_config/fallback_models behavior).

Booleans on group parameters only flip the cluster's master switch and leave
the flat tuning parameters untouched, so `history=True, num_history_runs=5`
behaves the same as `add_history_to_context=True, num_history_runs=5`.

The resolve_* functions in this module are shared by Agent, Team and Workflow
so the precedence rules cannot drift between the three classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.compression.manager import CompressionManager
    from agno.culture.manager import CultureManager
    from agno.memory.manager import MemoryManager
    from agno.models.base import Model
    from agno.session.summary import SessionSummaryManager


@dataclass
class HistoryConfig:
    """Chat history configuration for Agent, Team and Workflow.

    Groups: add_history_to_context, num_history_runs, num_history_messages,
    max_tool_calls_from_history, store_history_messages, read_chat_history,
    search_past_sessions, num_past_sessions_to_search,
    num_past_session_runs_in_search.
    """

    # Add messages from the chat history to the messages sent to the Model
    add_to_context: bool = True
    # Number of historical runs to include in the messages
    num_runs: Optional[int] = None
    # Number of historical messages to include in the messages (mutually exclusive with num_runs)
    num_messages: Optional[int] = None
    # Maximum number of tool calls to include from history (None = no limit)
    max_tool_calls: Optional[int] = None
    # Store history messages in run output (quadratic storage growth when True)
    store_messages: bool = False
    # Add a tool that allows the Model to read the chat history
    read_chat_history: bool = False
    # Add a tool that allows searching through previous sessions
    search_past_sessions: Optional[bool] = False
    # Max past sessions to search (default 20 when None)
    num_past_sessions: Optional[int] = None
    # Max runs per session in search preview (default 3 when None)
    num_past_session_runs: Optional[int] = None


@dataclass
class ReasoningConfig:
    """Reasoning configuration for Agent and Team.

    Groups: reasoning_model, reasoning_agent, reasoning_min_steps,
    reasoning_max_steps. Passing a ReasoningConfig enables reasoning.
    """

    # Model used for reasoning (defaults to a copy of the main model)
    model: Optional[Union["Model", str]] = None
    # Agent used for reasoning (advanced: overrides the default reasoning flow)
    agent: Optional["Agent"] = None
    # Minimum number of reasoning steps
    min_steps: int = 1
    # Maximum number of reasoning steps
    max_steps: int = 10


@dataclass
class MemoryConfig:
    """User memory configuration for Agent and Team.

    Groups: memory_manager, update_memory_on_run, enable_agentic_memory,
    add_memories_to_context.

    Note: MemoryConfig(manager=...) alone does not enable automatic memory
    updates; set update_on_run=True or agentic=True to activate memories.
    """

    # Memory manager to use
    manager: Optional["MemoryManager"] = None
    # Create/update user memories at the end of runs
    update_on_run: bool = False
    # Give the model a tool to manage memories of the user
    agentic: bool = False
    # Add a reference to the user memories in the context
    add_to_context: Optional[bool] = None


@dataclass
class SessionSummaryConfig:
    """Session summary configuration for Agent and Team.

    Groups: enable_session_summaries, session_summary_manager,
    add_session_summary_to_context. Passing a SessionSummaryConfig enables
    session summaries.
    """

    # Session summary manager to use
    manager: Optional["SessionSummaryManager"] = None
    # Add session summaries to the context
    add_to_context: Optional[bool] = None


@dataclass
class CultureConfig:
    """Cultural knowledge configuration for Agent (experimental).

    Groups: culture_manager, update_cultural_knowledge,
    enable_agentic_culture, add_culture_to_context.
    """

    # Culture manager to use
    manager: Optional["CultureManager"] = None
    # Update cultural knowledge at the end of runs
    update_on_run: bool = False
    # Give the model a tool to manage cultural knowledge
    agentic: bool = False
    # Add cultural knowledge to the context
    add_to_context: Optional[bool] = None


@dataclass
class FollowupConfig:
    """Followup prompt configuration for Agent and Team.

    Groups: num_followups, followup_model. Passing a FollowupConfig enables
    followups.
    """

    # Number of followup prompts to generate
    num: int = 3
    # Model used for generating followups (defaults to the main model)
    model: Optional[Union["Model", str]] = None


@dataclass
class RetryConfig:
    """Retry configuration for Agent and Team.

    Groups: retries, delay_between_retries, exponential_backoff.
    """

    # Number of retries to attempt
    retries: int = 0
    # Delay between retries (in seconds)
    delay: int = 1
    # If True, the delay between retries is doubled each time
    exponential_backoff: bool = False


def _warn_overridden_flat_params(group_param: str, flat_values: Dict[str, Any], flat_defaults: Dict[str, Any]) -> None:
    """Warn when flat params were set alongside a config object that overrides them."""
    overridden = [name for name, value in flat_values.items() if value != flat_defaults[name]]
    if overridden:
        log_warning(f"Both `{group_param}` and `{'`, `'.join(overridden)}` provided. Using `{group_param}`.")


_HISTORY_FLAT_DEFAULTS: Dict[str, Any] = {
    "add_history_to_context": False,
    "num_history_runs": None,
    "num_history_messages": None,
    "max_tool_calls_from_history": None,
    "store_history_messages": False,
    "read_chat_history": False,
    "search_past_sessions": False,
    "num_past_sessions_to_search": None,
    "num_past_session_runs_in_search": None,
}


def resolve_history_settings(
    history: Optional[Union[bool, HistoryConfig]],
    *,
    add_history_to_context: bool,
    num_history_runs: Optional[int],
    num_history_messages: Optional[int],
    max_tool_calls_from_history: Optional[int],
    store_history_messages: bool,
    read_chat_history: bool,
    search_past_sessions: Optional[bool],
    num_past_sessions_to_search: Optional[int],
    num_past_session_runs_in_search: Optional[int],
) -> HistoryConfig:
    """Resolve the history parameter cluster into a fully-populated HistoryConfig."""
    flat = HistoryConfig(
        add_to_context=add_history_to_context,
        num_runs=num_history_runs,
        num_messages=num_history_messages,
        max_tool_calls=max_tool_calls_from_history,
        store_messages=store_history_messages,
        read_chat_history=read_chat_history,
        search_past_sessions=search_past_sessions,
        num_past_sessions=num_past_sessions_to_search,
        num_past_session_runs=num_past_session_runs_in_search,
    )
    if history is None:
        return flat
    if isinstance(history, bool):
        flat.add_to_context = history
        return flat
    _warn_overridden_flat_params(
        "history",
        {
            "add_history_to_context": add_history_to_context,
            "num_history_runs": num_history_runs,
            "num_history_messages": num_history_messages,
            "max_tool_calls_from_history": max_tool_calls_from_history,
            "store_history_messages": store_history_messages,
            "read_chat_history": read_chat_history,
            "search_past_sessions": search_past_sessions,
            "num_past_sessions_to_search": num_past_sessions_to_search,
            "num_past_session_runs_in_search": num_past_session_runs_in_search,
        },
        _HISTORY_FLAT_DEFAULTS,
    )
    return history


_REASONING_FLAT_DEFAULTS: Dict[str, Any] = {
    "reasoning_model": None,
    "reasoning_agent": None,
    "reasoning_min_steps": 1,
    "reasoning_max_steps": 10,
}


def resolve_reasoning_settings(
    reasoning: Union[bool, ReasoningConfig],
    *,
    reasoning_model: Optional[Union["Model", str]],
    reasoning_agent: Optional["Agent"],
    reasoning_min_steps: int,
    reasoning_max_steps: int,
) -> Tuple[bool, ReasoningConfig]:
    """Resolve the reasoning parameter cluster. Returns (enabled, config)."""
    if isinstance(reasoning, bool):
        return reasoning, ReasoningConfig(
            model=reasoning_model,
            agent=reasoning_agent,
            min_steps=reasoning_min_steps,
            max_steps=reasoning_max_steps,
        )
    _warn_overridden_flat_params(
        "reasoning",
        {
            "reasoning_model": reasoning_model,
            "reasoning_agent": reasoning_agent,
            "reasoning_min_steps": reasoning_min_steps,
            "reasoning_max_steps": reasoning_max_steps,
        },
        _REASONING_FLAT_DEFAULTS,
    )
    return True, reasoning


_MEMORY_FLAT_DEFAULTS: Dict[str, Any] = {
    "memory_manager": None,
    "enable_agentic_memory": False,
    "update_memory_on_run": False,
    "add_memories_to_context": None,
}


def resolve_memory_settings(
    memory: Optional[Union[bool, "MemoryManager", MemoryConfig]],
    *,
    memory_manager: Optional["MemoryManager"],
    enable_agentic_memory: bool,
    update_memory_on_run: bool,
    add_memories_to_context: Optional[bool],
) -> MemoryConfig:
    """Resolve the memory parameter cluster into a fully-populated MemoryConfig."""
    from agno.memory.manager import MemoryManager

    flat = MemoryConfig(
        manager=memory_manager,
        update_on_run=update_memory_on_run,
        agentic=enable_agentic_memory,
        add_to_context=add_memories_to_context,
    )
    if memory is None:
        return flat
    if isinstance(memory, bool):
        flat.update_on_run = memory
        return flat
    if isinstance(memory, MemoryManager):
        memory = MemoryConfig(manager=memory, update_on_run=True)
    _warn_overridden_flat_params(
        "memory",
        {
            "memory_manager": memory_manager,
            "enable_agentic_memory": enable_agentic_memory,
            "update_memory_on_run": update_memory_on_run,
            "add_memories_to_context": add_memories_to_context,
        },
        _MEMORY_FLAT_DEFAULTS,
    )
    return memory


_SESSION_SUMMARY_FLAT_DEFAULTS: Dict[str, Any] = {
    "enable_session_summaries": False,
    "session_summary_manager": None,
    "add_session_summary_to_context": None,
}


def resolve_session_summary_settings(
    session_summaries: Optional[Union[bool, "SessionSummaryManager", SessionSummaryConfig]],
    *,
    enable_session_summaries: bool,
    session_summary_manager: Optional["SessionSummaryManager"],
    add_session_summary_to_context: Optional[bool],
) -> Tuple[bool, SessionSummaryConfig]:
    """Resolve the session summary parameter cluster. Returns (enabled, config)."""
    from agno.session.summary import SessionSummaryManager

    flat = SessionSummaryConfig(
        manager=session_summary_manager,
        add_to_context=add_session_summary_to_context,
    )
    if session_summaries is None:
        # Passing a manager alone enables summaries (existing behavior)
        return enable_session_summaries or session_summary_manager is not None, flat
    if isinstance(session_summaries, bool):
        return session_summaries, flat
    if isinstance(session_summaries, SessionSummaryManager):
        session_summaries = SessionSummaryConfig(manager=session_summaries)
    _warn_overridden_flat_params(
        "session_summaries",
        {
            "enable_session_summaries": enable_session_summaries,
            "session_summary_manager": session_summary_manager,
            "add_session_summary_to_context": add_session_summary_to_context,
        },
        _SESSION_SUMMARY_FLAT_DEFAULTS,
    )
    return True, session_summaries


_CULTURE_FLAT_DEFAULTS: Dict[str, Any] = {
    "culture_manager": None,
    "enable_agentic_culture": False,
    "update_cultural_knowledge": False,
    "add_culture_to_context": None,
}


def resolve_culture_settings(
    culture: Optional[Union[bool, "CultureManager", CultureConfig]],
    *,
    culture_manager: Optional["CultureManager"],
    enable_agentic_culture: bool,
    update_cultural_knowledge: bool,
    add_culture_to_context: Optional[bool],
) -> CultureConfig:
    """Resolve the culture parameter cluster into a fully-populated CultureConfig."""
    from agno.culture.manager import CultureManager

    flat = CultureConfig(
        manager=culture_manager,
        update_on_run=update_cultural_knowledge,
        agentic=enable_agentic_culture,
        add_to_context=add_culture_to_context,
    )
    if culture is None:
        return flat
    if isinstance(culture, bool):
        flat.update_on_run = culture
        return flat
    if isinstance(culture, CultureManager):
        culture = CultureConfig(manager=culture, update_on_run=True)
    _warn_overridden_flat_params(
        "culture",
        {
            "culture_manager": culture_manager,
            "enable_agentic_culture": enable_agentic_culture,
            "update_cultural_knowledge": update_cultural_knowledge,
            "add_culture_to_context": add_culture_to_context,
        },
        _CULTURE_FLAT_DEFAULTS,
    )
    return culture


_FOLLOWUP_FLAT_DEFAULTS: Dict[str, Any] = {
    "num_followups": 3,
    "followup_model": None,
}


def resolve_followup_settings(
    followups: Union[bool, FollowupConfig],
    *,
    num_followups: int,
    followup_model: Optional[Union["Model", str]],
) -> Tuple[bool, FollowupConfig]:
    """Resolve the followup parameter cluster. Returns (enabled, config)."""
    if isinstance(followups, bool):
        return followups, FollowupConfig(num=num_followups, model=followup_model)
    _warn_overridden_flat_params(
        "followups",
        {"num_followups": num_followups, "followup_model": followup_model},
        _FOLLOWUP_FLAT_DEFAULTS,
    )
    return True, followups


_RETRY_FLAT_DEFAULTS: Dict[str, Any] = {
    "retries": 0,
    "delay_between_retries": 1,
    "exponential_backoff": False,
}


def resolve_retry_settings(
    retry: Optional[RetryConfig],
    *,
    retries: int,
    delay_between_retries: int,
    exponential_backoff: bool,
) -> RetryConfig:
    """Resolve the retry parameter cluster into a fully-populated RetryConfig."""
    if retry is None:
        return RetryConfig(retries=retries, delay=delay_between_retries, exponential_backoff=exponential_backoff)
    _warn_overridden_flat_params(
        "retry",
        {
            "retries": retries,
            "delay_between_retries": delay_between_retries,
            "exponential_backoff": exponential_backoff,
        },
        _RETRY_FLAT_DEFAULTS,
    )
    return retry


def resolve_compression_settings(
    compress_tool_results: Union[bool, "CompressionManager"],
    *,
    compression_manager: Optional["CompressionManager"],
) -> Tuple[bool, Optional["CompressionManager"]]:
    """Resolve the compression parameter cluster. Returns (enabled, manager)."""
    from agno.compression.manager import CompressionManager

    if isinstance(compress_tool_results, CompressionManager):
        if compression_manager is not None:
            log_warning(
                "Both `compress_tool_results` and `compression_manager` provided. Using `compress_tool_results`."
            )
        return True, compress_tool_results
    return compress_tool_results, compression_manager


_WORKFLOW_HISTORY_FLAT_DEFAULTS: Dict[str, Any] = {
    "add_workflow_history_to_steps": False,
    "num_history_runs": 3,
}


def resolve_workflow_history_settings(
    history: Optional[Union[bool, HistoryConfig]],
    *,
    add_workflow_history_to_steps: bool,
    num_history_runs: int,
) -> Tuple[bool, int]:
    """Resolve the workflow history cluster. Returns (add_to_steps, num_runs)."""
    if history is None:
        return add_workflow_history_to_steps, num_history_runs
    if isinstance(history, bool):
        return history, num_history_runs
    _warn_overridden_flat_params(
        "history",
        {
            "add_workflow_history_to_steps": add_workflow_history_to_steps,
            "num_history_runs": num_history_runs,
        },
        _WORKFLOW_HISTORY_FLAT_DEFAULTS,
    )
    return history.add_to_context, history.num_runs if history.num_runs is not None else 3
