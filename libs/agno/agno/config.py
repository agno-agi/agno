"""Grouped configuration objects for Agent, Team and Workflow parameters.

Each config groups a cluster of related constructor parameters behind a single
object. The flat parameters remain fully supported: passing a config object is
equivalent to passing the corresponding flat parameters.

Merge semantics are field-level: a config field left as None means "not set"
and the flat parameter (or its default) wins for that field alone. A config
field that is set wins over the flat parameter, with a warning only when the
flat parameter was explicitly set to a different value. Booleans passed
directly on a group parameter (e.g. history=True) only flip the cluster's
master switch and leave the flat tuning parameters untouched.

The resolve_* functions in this module are shared by Agent, Team and Workflow
so the precedence rules cannot drift between the three classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Tuple, Union

from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.compression.manager import CompressionManager
    from agno.culture.manager import CultureManager
    from agno.filters import FilterExpr
    from agno.memory.manager import MemoryManager
    from agno.models.base import Model
    from agno.session.summary import SessionSummaryManager
    from agno.team.mode import TeamMode


@dataclass
class HistoryConfig:
    """Chat history configuration for Agent, Team and Workflow.

    Groups: add_history_to_context, num_history_runs, num_history_messages,
    max_tool_calls_from_history, read_chat_history, read_tool_call_history,
    search_past_sessions, num_past_sessions_to_search,
    num_past_session_runs_in_search. On Workflow, add_to_context and num_runs
    map to add_workflow_history_to_steps and num_history_runs.

    Passing a HistoryConfig enables history unless add_to_context=False.
    """

    # Add messages from the chat history to the messages sent to the Model
    add_to_context: bool = True
    # Number of historical runs to include in the messages
    num_runs: Optional[int] = None
    # Number of historical messages to include in the messages (mutually exclusive with num_runs)
    num_messages: Optional[int] = None
    # Maximum number of tool calls to include from history (None = no limit)
    max_tool_calls: Optional[int] = None
    # Add a tool that allows the Model to read the chat history
    read_chat_history: Optional[bool] = None
    # Add a tool that allows the Model to read the tool call history (Agent only)
    read_tool_call_history: Optional[bool] = None
    # Add a tool that allows searching through previous sessions
    search_past_sessions: Optional[bool] = None
    # Max past sessions to search (default 20 when None)
    num_past_sessions: Optional[int] = None
    # Max runs per session in search preview (default 3 when None)
    num_past_session_runs: Optional[int] = None


@dataclass
class SessionConfig:
    """Session configuration for Agent, Team and Workflow.

    Groups: session_id, session_state, add_session_state_to_context,
    enable_agentic_state, overwrite_db_session_state, cache_session,
    enable_session_summaries, session_summary_manager,
    add_session_summary_to_context. Workflow supports id, state,
    add_state_to_context, overwrite_db_state and cache only.
    """

    # Session ID (session_id)
    id: Optional[str] = None
    # Session state stored in the database to persist across runs (session_state)
    state: Optional[Dict[str, Any]] = None
    # Add the session state to the context (add_session_state_to_context)
    add_state_to_context: Optional[bool] = None
    # Give the model tools to update the session state dynamically (enable_agentic_state)
    agentic_state: Optional[bool] = None
    # Overwrite the stored session state with the one provided in the run (overwrite_db_session_state)
    overwrite_db_state: Optional[bool] = None
    # Cache the current session in memory for faster access (cache_session)
    cache: Optional[bool] = None
    # Enable session summaries: True/False, or a SessionSummaryManager to use
    # (enable_session_summaries / session_summary_manager)
    summaries: Optional[Union[bool, "SessionSummaryManager"]] = None
    # Add session summaries to the context (add_session_summary_to_context)
    add_summaries_to_context: Optional[bool] = None


@dataclass
class MemoryConfig:
    """User memory configuration for Agent and Team.

    Groups: memory_manager, update_memory_on_run, enable_agentic_memory,
    add_memories_to_context.

    Note: MemoryConfig(manager=...) alone does not enable automatic memory
    updates; set update_on_run=True or agentic=True to activate memories.
    """

    # Memory manager to use (memory_manager)
    manager: Optional["MemoryManager"] = None
    # Create/update user memories at the end of runs (update_memory_on_run)
    update_on_run: Optional[bool] = None
    # Give the model a tool to manage memories of the user (enable_agentic_memory)
    agentic: Optional[bool] = None
    # Add a reference to the user memories in the context (add_memories_to_context)
    add_to_context: Optional[bool] = None


@dataclass
class CultureConfig:
    """Cultural knowledge configuration for Agent (experimental).

    Groups: culture_manager, update_cultural_knowledge,
    enable_agentic_culture, add_culture_to_context.
    """

    # Culture manager to use (culture_manager)
    manager: Optional["CultureManager"] = None
    # Update cultural knowledge at the end of runs (update_cultural_knowledge)
    update_on_run: Optional[bool] = None
    # Give the model a tool to manage cultural knowledge (enable_agentic_culture)
    agentic: Optional[bool] = None
    # Add cultural knowledge to the context (add_culture_to_context)
    add_to_context: Optional[bool] = None


@dataclass
class KnowledgeConfig:
    """Knowledge retrieval configuration for Agent and Team.

    Groups: knowledge_filters, enable_agentic_knowledge_filters,
    add_knowledge_to_context, knowledge_retriever, references_format,
    search_knowledge, add_search_knowledge_instructions, update_knowledge.
    The knowledge source itself stays on the flat `knowledge` parameter.
    """

    # Filters applied to knowledge searches (knowledge_filters)
    filters: Optional[Union[Dict[str, Any], List["FilterExpr"]]] = None
    # Let the model choose the knowledge filters (enable_agentic_knowledge_filters)
    agentic_filters: Optional[bool] = None
    # Add references from knowledge to the context (add_knowledge_to_context)
    add_to_context: Optional[bool] = None
    # Custom retrieval function used instead of the default search (knowledge_retriever)
    retriever: Optional[Callable[..., Optional[List[Union[Dict, str]]]]] = None
    # Format of the references added to context (references_format)
    references_format: Optional[Literal["json", "yaml"]] = None
    # Add a tool to search the knowledge base (search_knowledge)
    search_knowledge: Optional[bool] = None
    # Add search_knowledge instructions to the system prompt (add_search_knowledge_instructions)
    add_search_instructions: Optional[bool] = None
    # Add a tool to update the knowledge base (update_knowledge)
    update_knowledge: Optional[bool] = None


@dataclass
class DelegationConfig:
    """Member delegation configuration for Team.

    Groups: mode, respond_directly, determine_input_for_members,
    delegate_to_all_members, max_iterations, add_team_history_to_members,
    num_team_history_runs, share_member_interactions,
    add_member_tools_to_context, get_member_information_tool,
    store_member_responses, stream_member_events, show_members_responses.
    """

    # Team execution mode; when set, overrides the boolean flags below
    mode: Optional["TeamMode"] = None
    # Return member responses directly without leader processing
    respond_directly: Optional[bool] = None
    # Let the leader determine the input for members (False sends run input directly)
    determine_input_for_members: Optional[bool] = None
    # Delegate the task to all members instead of a chosen subset
    delegate_to_all_members: Optional[bool] = None
    # Maximum iterations for the autonomous task loop (mode=tasks)
    max_iterations: Optional[int] = None
    # Send team-level history to members
    add_team_history_to_members: Optional[bool] = None
    # Number of team history runs to send to members
    num_team_history_runs: Optional[int] = None
    # Share member interactions from the current run with subsequently delegated members
    share_member_interactions: Optional[bool] = None
    # Add the tools available to members to the context
    add_member_tools_to_context: Optional[bool] = None
    # Add a tool to get information about the team members
    get_member_information_tool: Optional[bool] = None
    # Store member runs inside the team's RunOutput
    store_member_responses: Optional[bool] = None
    # Stream the member events from the Team
    stream_member_events: Optional[bool] = None
    # Set debug_mode for members and show member responses
    show_members_responses: Optional[bool] = None


@dataclass
class StorageConfig:
    """Run persistence configuration for Agent, Team and Workflow.

    Groups: store_media, store_tool_messages, store_history_messages,
    store_events, events_to_skip, store_executor_outputs. Controls what parts
    of a run get persisted to the database.
    """

    # Store media (images, videos, audio, files) in run output (store_media)
    media: Optional[bool] = None
    # Store tool results in run output (store_tool_messages)
    tool_messages: Optional[bool] = None
    # Store history messages in run output; quadratic storage growth when True (store_history_messages)
    history_messages: Optional[bool] = None
    # Persist events on the run response (store_events)
    events: Optional[bool] = None
    # Events to skip when persisting events (events_to_skip)
    events_to_skip: Optional[List[Any]] = None
    # Store executor (agent/team) responses in flattened runs; Workflow only (store_executor_outputs)
    executor_outputs: Optional[bool] = None


@dataclass
class ParsingConfig:
    """Response parsing configuration for Agent and Team.

    Groups: parser_model, parser_model_prompt, output_model,
    output_model_prompt, parse_response, structured_outputs, use_json_mode.
    Controls how the raw model response becomes the final structured output.
    The schemas themselves stay on the flat input_schema/output_schema params.

    parser_model parses the primary model's response into the output schema;
    output_model generates the final structured response from the primary
    model's output.
    """

    # Secondary model that parses the primary model's response (parser_model)
    parser_model: Optional[Union["Model", str]] = None
    # Prompt for the parser model (parser_model_prompt)
    parser_prompt: Optional[str] = None
    # Model that structures the response from the main model (output_model)
    output_model: Optional[Union["Model", str]] = None
    # Prompt for the output model (output_model_prompt)
    output_prompt: Optional[str] = None
    # Convert the response into the output_schema instead of returning a JSON string (parse_response)
    parse_response: Optional[bool] = None
    # Use model-enforced structured outputs if supported; Agent only (structured_outputs)
    structured_outputs: Optional[bool] = None
    # Describe the output schema in the system message instead of using native schemas (use_json_mode)
    use_json_mode: Optional[bool] = None


@dataclass
class ReasoningConfig:
    """Reasoning configuration for Agent and Team.

    Groups: reasoning_model, reasoning_agent, reasoning_min_steps,
    reasoning_max_steps. Passing a ReasoningConfig enables reasoning.
    """

    # Model used for reasoning; defaults to a copy of the main model (reasoning_model)
    model: Optional[Union["Model", str]] = None
    # Agent used for reasoning; overrides the default reasoning flow (reasoning_agent)
    agent: Optional["Agent"] = None
    # Minimum number of reasoning steps (reasoning_min_steps)
    min_steps: Optional[int] = None
    # Maximum number of reasoning steps (reasoning_max_steps)
    max_steps: Optional[int] = None


@dataclass
class FollowupConfig:
    """Followup prompt configuration for Agent and Team.

    Groups: num_followups, followup_model. Passing a FollowupConfig enables
    followups.
    """

    # Number of followup prompts to generate (num_followups)
    num: Optional[int] = None
    # Model used for generating followups; defaults to the main model (followup_model)
    model: Optional[Union["Model", str]] = None


@dataclass
class RetryConfig:
    """Retry configuration for Agent and Team.

    Groups: retries, delay_between_retries, exponential_backoff.
    """

    # Number of retries to attempt (retries)
    retries: Optional[int] = None
    # Delay between retries in seconds (delay_between_retries)
    delay: Optional[int] = None
    # Double the delay between retries each time (exponential_backoff)
    exponential_backoff: Optional[bool] = None


@dataclass
class CallableCacheConfig:
    """Callable factory cache configuration for Agent and Team.

    Groups: callable_tools_cache_key, callable_knowledge_cache_key,
    callable_members_cache_key. Passing a CallableCacheConfig enables
    callable caching (cache_callables=True).
    """

    # Custom cache key function for the tools callable factory (callable_tools_cache_key)
    tools_cache_key: Optional[Callable[..., Optional[str]]] = None
    # Custom cache key function for the knowledge callable factory (callable_knowledge_cache_key)
    knowledge_cache_key: Optional[Callable[..., Optional[str]]] = None
    # Custom cache key function for the members callable factory; Team only (callable_members_cache_key)
    members_cache_key: Optional[Callable[..., Optional[str]]] = None


# ---------------------------------------------------------------------------
# Resolution machinery
# ---------------------------------------------------------------------------

# One row per field: (config_field, flat_name, flat_value, flat_default)
_FieldMapping = List[Tuple[str, str, Any, Any]]


def _resolve_fields(group_param: str, config: Optional[Any], mapping: _FieldMapping) -> Dict[str, Any]:
    """Merge a config object onto flat parameter values, field by field.

    A config field left as None is "not set": the flat value (explicit or
    default) wins. A set config field wins over the flat value, warning once
    per group for flat params that were explicitly set to a different value.
    Returns resolved values keyed by flat parameter name.
    """
    resolved: Dict[str, Any] = {}
    overridden: List[str] = []
    for config_field, flat_name, flat_value, flat_default in mapping:
        config_value = getattr(config, config_field) if config is not None else None
        if config_value is None:
            resolved[flat_name] = flat_value
        else:
            if flat_value != flat_default and flat_value != config_value:
                overridden.append(flat_name)
            resolved[flat_name] = config_value
    if overridden:
        log_warning(f"Both `{group_param}` and `{'`, `'.join(overridden)}` provided. Using `{group_param}`.")
    return resolved


def warn_unsupported_config_fields(group_param: str, owner: str, config: Optional[Any], fields: List[str]) -> None:
    """Warn when config fields not supported by the owning class are set."""
    if config is None or isinstance(config, bool):
        return
    set_fields = [name for name in fields if getattr(config, name, None) is not None]
    if set_fields:
        names = ", ".join(f"`{group_param}.{name}`" for name in set_fields)
        log_warning(f"{names} not supported on {owner}. Ignoring.")


def resolve_history_settings(
    history: Optional[Union[bool, HistoryConfig]],
    *,
    add_history_to_context: bool,
    num_history_runs: Optional[int],
    num_history_messages: Optional[int],
    max_tool_calls_from_history: Optional[int],
    read_chat_history: bool,
    search_past_sessions: Optional[bool],
    num_past_sessions_to_search: Optional[int],
    num_past_session_runs_in_search: Optional[int],
    read_tool_call_history: bool = False,
) -> Dict[str, Any]:
    """Resolve the history parameter cluster to flat values."""
    config: Optional[HistoryConfig] = None
    if isinstance(history, bool):
        add_history_to_context = history
    elif history is not None:
        config = history
    return _resolve_fields(
        "history",
        config,
        [
            ("add_to_context", "add_history_to_context", add_history_to_context, False),
            ("num_runs", "num_history_runs", num_history_runs, None),
            ("num_messages", "num_history_messages", num_history_messages, None),
            ("max_tool_calls", "max_tool_calls_from_history", max_tool_calls_from_history, None),
            ("read_chat_history", "read_chat_history", read_chat_history, False),
            ("read_tool_call_history", "read_tool_call_history", read_tool_call_history, False),
            ("search_past_sessions", "search_past_sessions", search_past_sessions, False),
            ("num_past_sessions", "num_past_sessions_to_search", num_past_sessions_to_search, None),
            ("num_past_session_runs", "num_past_session_runs_in_search", num_past_session_runs_in_search, None),
        ],
    )


def resolve_session_settings(
    session: Optional[SessionConfig],
    *,
    session_id: Optional[str],
    session_state: Optional[Dict[str, Any]],
    add_session_state_to_context: Optional[bool],
    enable_agentic_state: bool,
    overwrite_db_session_state: bool,
    cache_session: bool,
    enable_session_summaries: bool = False,
    session_summary_manager: Optional["SessionSummaryManager"] = None,
    add_session_summary_to_context: Optional[bool] = None,
    add_session_state_to_context_default: Optional[bool] = False,
) -> Dict[str, Any]:
    """Resolve the session parameter cluster to flat values.

    add_session_state_to_context_default exists because Workflow declares that
    flat parameter with a None default while Agent and Team use False.
    """
    resolved = _resolve_fields(
        "session",
        session,
        [
            ("id", "session_id", session_id, None),
            ("state", "session_state", session_state, None),
            (
                "add_state_to_context",
                "add_session_state_to_context",
                add_session_state_to_context,
                add_session_state_to_context_default,
            ),
            ("agentic_state", "enable_agentic_state", enable_agentic_state, False),
            ("overwrite_db_state", "overwrite_db_session_state", overwrite_db_session_state, False),
            ("cache", "cache_session", cache_session, False),
            ("add_summaries_to_context", "add_session_summary_to_context", add_session_summary_to_context, None),
        ],
    )
    # summaries: bool enables/disables; a manager configures and enables
    summaries = session.summaries if session is not None else None
    if summaries is None:
        # Passing a manager alone enables summaries (existing behavior)
        resolved["enable_session_summaries"] = enable_session_summaries or session_summary_manager is not None
        resolved["session_summary_manager"] = session_summary_manager
    elif isinstance(summaries, bool):
        resolved["enable_session_summaries"] = summaries
        resolved["session_summary_manager"] = session_summary_manager
    else:
        if session_summary_manager is not None and session_summary_manager is not summaries:
            log_warning("Both `session.summaries` and `session_summary_manager` provided. Using `session.summaries`.")
        resolved["enable_session_summaries"] = True
        resolved["session_summary_manager"] = summaries
    return resolved


def resolve_memory_settings(
    memory: Optional[Union[bool, "MemoryManager", MemoryConfig]],
    *,
    memory_manager: Optional["MemoryManager"],
    enable_agentic_memory: bool,
    update_memory_on_run: bool,
    add_memories_to_context: Optional[bool],
) -> Dict[str, Any]:
    """Resolve the memory parameter cluster to flat values."""
    from agno.memory.manager import MemoryManager

    config: Optional[MemoryConfig] = None
    if isinstance(memory, bool):
        update_memory_on_run = memory
    elif isinstance(memory, MemoryManager):
        config = MemoryConfig(manager=memory, update_on_run=True)
    elif memory is not None:
        config = memory
    return _resolve_fields(
        "memory",
        config,
        [
            ("manager", "memory_manager", memory_manager, None),
            ("agentic", "enable_agentic_memory", enable_agentic_memory, False),
            ("update_on_run", "update_memory_on_run", update_memory_on_run, False),
            ("add_to_context", "add_memories_to_context", add_memories_to_context, None),
        ],
    )


def resolve_culture_settings(
    culture: Optional[Union[bool, "CultureManager", CultureConfig]],
    *,
    culture_manager: Optional["CultureManager"],
    enable_agentic_culture: bool,
    update_cultural_knowledge: bool,
    add_culture_to_context: Optional[bool],
) -> Dict[str, Any]:
    """Resolve the culture parameter cluster to flat values."""
    from agno.culture.manager import CultureManager

    config: Optional[CultureConfig] = None
    if isinstance(culture, bool):
        update_cultural_knowledge = culture
    elif isinstance(culture, CultureManager):
        config = CultureConfig(manager=culture, update_on_run=True)
    elif culture is not None:
        config = culture
    return _resolve_fields(
        "culture",
        config,
        [
            ("manager", "culture_manager", culture_manager, None),
            ("agentic", "enable_agentic_culture", enable_agentic_culture, False),
            ("update_on_run", "update_cultural_knowledge", update_cultural_knowledge, False),
            ("add_to_context", "add_culture_to_context", add_culture_to_context, None),
        ],
    )


def resolve_knowledge_settings(
    knowledge_config: Optional[KnowledgeConfig],
    *,
    knowledge_filters: Optional[Union[Dict[str, Any], List["FilterExpr"]]],
    enable_agentic_knowledge_filters: Optional[bool],
    add_knowledge_to_context: bool,
    knowledge_retriever: Optional[Callable[..., Optional[List[Union[Dict, str]]]]],
    references_format: Literal["json", "yaml"],
    search_knowledge: bool,
    add_search_knowledge_instructions: bool,
    update_knowledge: bool,
) -> Dict[str, Any]:
    """Resolve the knowledge retrieval parameter cluster to flat values."""
    return _resolve_fields(
        "knowledge_config",
        knowledge_config,
        [
            ("filters", "knowledge_filters", knowledge_filters, None),
            ("agentic_filters", "enable_agentic_knowledge_filters", enable_agentic_knowledge_filters, False),
            ("add_to_context", "add_knowledge_to_context", add_knowledge_to_context, False),
            ("retriever", "knowledge_retriever", knowledge_retriever, None),
            ("references_format", "references_format", references_format, "json"),
            ("search_knowledge", "search_knowledge", search_knowledge, True),
            ("add_search_instructions", "add_search_knowledge_instructions", add_search_knowledge_instructions, True),
            ("update_knowledge", "update_knowledge", update_knowledge, False),
        ],
    )


def resolve_delegation_settings(
    delegation: Optional[DelegationConfig],
    *,
    mode: Optional["TeamMode"],
    respond_directly: bool,
    determine_input_for_members: bool,
    delegate_to_all_members: bool,
    max_iterations: int,
    add_team_history_to_members: bool,
    num_team_history_runs: int,
    share_member_interactions: bool,
    add_member_tools_to_context: bool,
    get_member_information_tool: bool,
    store_member_responses: bool,
    stream_member_events: bool,
    show_members_responses: bool,
) -> Dict[str, Any]:
    """Resolve the Team delegation parameter cluster to flat values."""
    return _resolve_fields(
        "delegation",
        delegation,
        [
            ("mode", "mode", mode, None),
            ("respond_directly", "respond_directly", respond_directly, False),
            ("determine_input_for_members", "determine_input_for_members", determine_input_for_members, True),
            ("delegate_to_all_members", "delegate_to_all_members", delegate_to_all_members, False),
            ("max_iterations", "max_iterations", max_iterations, 10),
            ("add_team_history_to_members", "add_team_history_to_members", add_team_history_to_members, False),
            ("num_team_history_runs", "num_team_history_runs", num_team_history_runs, 3),
            ("share_member_interactions", "share_member_interactions", share_member_interactions, False),
            ("add_member_tools_to_context", "add_member_tools_to_context", add_member_tools_to_context, False),
            ("get_member_information_tool", "get_member_information_tool", get_member_information_tool, False),
            ("store_member_responses", "store_member_responses", store_member_responses, False),
            ("stream_member_events", "stream_member_events", stream_member_events, True),
            ("show_members_responses", "show_members_responses", show_members_responses, False),
        ],
    )


def resolve_storage_settings(
    storage: Optional[StorageConfig],
    *,
    store_media: bool = True,
    store_tool_messages: bool = True,
    store_history_messages: bool = False,
    store_events: bool = False,
    events_to_skip: Optional[List[Any]] = None,
    store_executor_outputs: bool = True,
) -> Dict[str, Any]:
    """Resolve the run storage parameter cluster to flat values."""
    return _resolve_fields(
        "storage",
        storage,
        [
            ("media", "store_media", store_media, True),
            ("tool_messages", "store_tool_messages", store_tool_messages, True),
            ("history_messages", "store_history_messages", store_history_messages, False),
            ("events", "store_events", store_events, False),
            ("events_to_skip", "events_to_skip", events_to_skip, None),
            ("executor_outputs", "store_executor_outputs", store_executor_outputs, True),
        ],
    )


def resolve_parsing_settings(
    parsing: Optional[ParsingConfig],
    *,
    parser_model: Optional[Union["Model", str]],
    parser_model_prompt: Optional[str],
    output_model: Optional[Union["Model", str]],
    output_model_prompt: Optional[str],
    parse_response: bool,
    use_json_mode: bool,
    structured_outputs: Optional[bool] = None,
) -> Dict[str, Any]:
    """Resolve the response parsing parameter cluster to flat values."""
    return _resolve_fields(
        "parsing",
        parsing,
        [
            ("parser_model", "parser_model", parser_model, None),
            ("parser_prompt", "parser_model_prompt", parser_model_prompt, None),
            ("output_model", "output_model", output_model, None),
            ("output_prompt", "output_model_prompt", output_model_prompt, None),
            ("parse_response", "parse_response", parse_response, True),
            ("structured_outputs", "structured_outputs", structured_outputs, None),
            ("use_json_mode", "use_json_mode", use_json_mode, False),
        ],
    )


def resolve_reasoning_settings(
    reasoning: Union[bool, ReasoningConfig],
    *,
    reasoning_model: Optional[Union["Model", str]],
    reasoning_agent: Optional["Agent"],
    reasoning_min_steps: int,
    reasoning_max_steps: int,
) -> Tuple[bool, Dict[str, Any]]:
    """Resolve the reasoning parameter cluster. Returns (enabled, flat values)."""
    config: Optional[ReasoningConfig] = None
    if isinstance(reasoning, bool):
        enabled = reasoning
    else:
        enabled = True
        config = reasoning
    resolved = _resolve_fields(
        "reasoning",
        config,
        [
            ("model", "reasoning_model", reasoning_model, None),
            ("agent", "reasoning_agent", reasoning_agent, None),
            ("min_steps", "reasoning_min_steps", reasoning_min_steps, 1),
            ("max_steps", "reasoning_max_steps", reasoning_max_steps, 10),
        ],
    )
    return enabled, resolved


def resolve_followup_settings(
    followups: Union[bool, FollowupConfig],
    *,
    num_followups: int,
    followup_model: Optional[Union["Model", str]],
) -> Tuple[bool, Dict[str, Any]]:
    """Resolve the followup parameter cluster. Returns (enabled, flat values)."""
    config: Optional[FollowupConfig] = None
    if isinstance(followups, bool):
        enabled = followups
    else:
        enabled = True
        config = followups
    resolved = _resolve_fields(
        "followups",
        config,
        [
            ("num", "num_followups", num_followups, 3),
            ("model", "followup_model", followup_model, None),
        ],
    )
    return enabled, resolved


def resolve_retry_settings(
    retry: Optional[RetryConfig],
    *,
    retries: int,
    delay_between_retries: int,
    exponential_backoff: bool,
) -> Dict[str, Any]:
    """Resolve the retry parameter cluster to flat values."""
    return _resolve_fields(
        "retry",
        retry,
        [
            ("retries", "retries", retries, 0),
            ("delay", "delay_between_retries", delay_between_retries, 1),
            ("exponential_backoff", "exponential_backoff", exponential_backoff, False),
        ],
    )


def resolve_compression_settings(
    compress_tool_results: Union[bool, "CompressionManager"],
    *,
    compression_manager: Optional["CompressionManager"],
) -> Tuple[bool, Optional["CompressionManager"]]:
    """Resolve the compression parameter cluster. Returns (enabled, manager)."""
    from agno.compression.manager import CompressionManager

    if isinstance(compress_tool_results, CompressionManager):
        if compression_manager is not None and compression_manager is not compress_tool_results:
            log_warning(
                "Both `compress_tool_results` and `compression_manager` provided. Using `compress_tool_results`."
            )
        return True, compress_tool_results
    return compress_tool_results, compression_manager


def resolve_callable_cache_settings(
    cache_callables: Union[bool, CallableCacheConfig],
    *,
    callable_tools_cache_key: Optional[Callable[..., Optional[str]]],
    callable_knowledge_cache_key: Optional[Callable[..., Optional[str]]],
    callable_members_cache_key: Optional[Callable[..., Optional[str]]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Resolve the callable cache parameter cluster. Returns (enabled, flat values)."""
    config: Optional[CallableCacheConfig] = None
    if isinstance(cache_callables, bool):
        enabled = cache_callables
    else:
        enabled = True
        config = cache_callables
    resolved = _resolve_fields(
        "cache_callables",
        config,
        [
            ("tools_cache_key", "callable_tools_cache_key", callable_tools_cache_key, None),
            ("knowledge_cache_key", "callable_knowledge_cache_key", callable_knowledge_cache_key, None),
            ("members_cache_key", "callable_members_cache_key", callable_members_cache_key, None),
        ],
    )
    return enabled, resolved


def resolve_workflow_history_settings(
    history: Optional[Union[bool, HistoryConfig]],
    *,
    add_workflow_history_to_steps: bool,
    num_history_runs: int,
) -> Dict[str, Any]:
    """Resolve the workflow history cluster to flat values."""
    config: Optional[HistoryConfig] = None
    if isinstance(history, bool):
        add_workflow_history_to_steps = history
    elif history is not None:
        config = history
        warn_unsupported_config_fields(
            "history",
            "Workflow",
            config,
            [
                "num_messages",
                "max_tool_calls",
                "read_chat_history",
                "read_tool_call_history",
                "search_past_sessions",
                "num_past_sessions",
                "num_past_session_runs",
            ],
        )
    return _resolve_fields(
        "history",
        config,
        [
            ("add_to_context", "add_workflow_history_to_steps", add_workflow_history_to_steps, False),
            ("num_runs", "num_history_runs", num_history_runs, 3),
        ],
    )
