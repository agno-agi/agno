from __future__ import annotations

from typing import TYPE_CHECKING, Any


class AgentTraitBase:
    """Type-only base class for Agent traits.

    The Agent implementation is split across multiple trait modules. This base
    defines the shared attributes as `Any` so mypy can type-check the traits
    without inferring incompatible instance-variable types.
    """

    # Public Agent config fields
    model: Any
    name: Any
    id: Any
    user_id: Any
    session_id: Any
    session_state: Any
    add_session_state_to_context: Any
    enable_agentic_state: Any
    overwrite_db_session_state: Any
    cache_session: Any
    search_session_history: Any
    num_history_sessions: Any
    enable_session_summaries: Any
    add_session_summary_to_context: Any
    session_summary_manager: Any
    dependencies: Any
    add_dependencies_to_context: Any
    memory_manager: Any
    enable_agentic_memory: Any
    update_memory_on_run: Any
    enable_user_memories: Any
    add_memories_to_context: Any
    db: Any
    add_history_to_context: Any
    num_history_runs: Any
    num_history_messages: Any
    max_tool_calls_from_history: Any
    knowledge: Any
    knowledge_filters: Any
    enable_agentic_knowledge_filters: Any
    add_knowledge_to_context: Any
    knowledge_retriever: Any
    references_format: Any
    skills: Any
    tools: Any
    tool_call_limit: Any
    tool_choice: Any
    tool_hooks: Any
    pre_hooks: Any
    post_hooks: Any
    _run_hooks_in_background: Any
    reasoning: Any
    reasoning_model: Any
    reasoning_agent: Any
    reasoning_min_steps: Any
    reasoning_max_steps: Any
    read_chat_history: Any
    search_knowledge: Any
    add_search_knowledge_instructions: Any
    update_knowledge: Any
    read_tool_call_history: Any
    send_media_to_model: Any
    store_media: Any
    store_tool_messages: Any
    store_history_messages: Any
    system_message: Any
    system_message_role: Any
    introduction: Any
    build_context: Any
    description: Any
    instructions: Any
    use_instruction_tags: Any
    expected_output: Any
    additional_context: Any
    markdown: Any
    add_name_to_context: Any
    add_datetime_to_context: Any
    add_location_to_context: Any
    timezone_identifier: Any
    resolve_in_context: Any
    learning: Any
    add_learnings_to_context: Any
    additional_input: Any
    user_message_role: Any
    build_user_context: Any
    retries: Any
    delay_between_retries: Any
    exponential_backoff: Any
    input_schema: Any
    output_schema: Any
    parser_model: Any
    parser_model_prompt: Any
    output_model: Any
    output_model_prompt: Any
    parse_response: Any
    structured_outputs: Any
    use_json_mode: Any
    save_response_to_file: Any
    stream: Any
    stream_events: Any
    store_events: Any
    events_to_skip: Any
    role: Any
    team_id: Any
    workflow_id: Any
    metadata: Any
    culture_manager: Any
    enable_agentic_culture: Any
    update_cultural_knowledge: Any
    add_culture_to_context: Any
    compress_tool_results: Any
    compression_manager: Any
    debug_mode: Any
    debug_level: Any
    telemetry: Any

    # Internal runtime attributes set in __init__
    _learning: Any
    _cached_session: Any
    _tool_instructions: Any
    _formatter: Any
    _hooks_normalised: Any
    _mcp_tools_initialized_on_run: Any
    _connectable_tools_initialized_on_run: Any
    _run_options_by_run_id: Any
    _run_engines_by_run_id: Any
    _background_executor: Any

    if TYPE_CHECKING:

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        def __getattr__(self, name: str) -> Any: ...
