"""Initialization and configuration trait for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.mode import TeamMode
    from agno.team.team import Team

from os import getenv
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.base import AsyncBaseDb, BaseDb
from agno.eval.base import BaseEval
from agno.filters import FilterExpr
from agno.guardrails import BaseGuardrail
from agno.knowledge.protocol import KnowledgeProtocol
from agno.learn.machine import LearningMachine
from agno.memory import MemoryManager
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.run.agent import RunEvent
from agno.run.team import (
    TeamRunEvent,
)
from agno.session import SessionSummaryManager, TeamSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import (
    log_debug,
    log_error,
    log_exception,
    log_info,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
    use_team_logger,
)
from agno.utils.safe_formatter import SafeFormatter
from agno.utils.string import generate_id_from_name


def __init__(
    team: "Team",
    members: Union[List[Union[Agent, "Team"]], Callable[..., List]],
    id: Optional[str] = None,
    model: Optional[Union[Model, str]] = None,
    name: Optional[str] = None,
    role: Optional[str] = None,
    mode: Optional["TeamMode"] = None,
    respond_directly: bool = False,
    determine_input_for_members: bool = True,
    delegate_to_all_members: bool = False,
    max_iterations: int = 10,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    add_session_state_to_context: bool = False,
    enable_agentic_state: bool = False,
    overwrite_db_session_state: bool = False,
    resolve_in_context: bool = True,
    cache_session: bool = False,
    add_team_history_to_members: bool = False,
    num_team_history_runs: int = 3,
    search_session_history: Optional[bool] = False,
    num_history_sessions: Optional[int] = None,
    description: Optional[str] = None,
    instructions: Optional[Union[str, List[str], Callable]] = None,
    use_instruction_tags: bool = False,
    expected_output: Optional[str] = None,
    additional_context: Optional[str] = None,
    markdown: bool = False,
    add_datetime_to_context: bool = False,
    add_location_to_context: bool = False,
    timezone_identifier: Optional[str] = None,
    add_name_to_context: bool = False,
    add_member_tools_to_context: bool = False,
    system_message: Optional[Union[str, Callable, Message]] = None,
    system_message_role: str = "system",
    introduction: Optional[str] = None,
    additional_input: Optional[List[Union[str, Dict, BaseModel, Message]]] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: bool = False,
    knowledge: Optional[Union[KnowledgeProtocol, Callable[..., KnowledgeProtocol]]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_knowledge_to_context: bool = False,
    enable_agentic_knowledge_filters: Optional[bool] = False,
    update_knowledge: bool = False,
    knowledge_retriever: Optional[Callable[..., Optional[List[Union[Dict, str]]]]] = None,
    references_format: Literal["json", "yaml"] = "json",
    share_member_interactions: bool = False,
    include_tool_results_in_member_response: bool = True,
    get_member_information_tool: bool = False,
    search_knowledge: bool = True,
    add_search_knowledge_instructions: bool = True,
    read_chat_history: bool = False,
    store_media: bool = True,
    store_tool_messages: bool = True,
    store_history_messages: bool = False,
    send_media_to_model: bool = True,
    add_history_to_context: bool = False,
    num_history_runs: Optional[int] = None,
    num_history_messages: Optional[int] = None,
    max_tool_calls_from_history: Optional[int] = None,
    tools: Optional[Union[List[Union[Toolkit, Callable, Function, Dict]], Callable[..., List]]] = None,
    tool_call_limit: Optional[int] = None,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    tool_hooks: Optional[List[Callable]] = None,
    pre_hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]] = None,
    post_hooks: Optional[List[Union[Callable[..., Any], BaseGuardrail, BaseEval]]] = None,
    input_schema: Optional[Type[BaseModel]] = None,
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
    parser_model: Optional[Union[Model, str]] = None,
    parser_model_prompt: Optional[str] = None,
    output_model: Optional[Union[Model, str]] = None,
    output_model_prompt: Optional[str] = None,
    use_json_mode: bool = False,
    parse_response: bool = True,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    enable_agentic_memory: bool = False,
    update_memory_on_run: bool = False,
    enable_user_memories: Optional[bool] = None,  # Soon to be deprecated. Use update_memory_on_run
    add_memories_to_context: Optional[bool] = None,
    memory_manager: Optional[MemoryManager] = None,
    enable_session_summaries: bool = False,
    session_summary_manager: Optional[SessionSummaryManager] = None,
    add_session_summary_to_context: Optional[bool] = None,
    learning: Optional[Union[bool, LearningMachine]] = None,
    add_learnings_to_context: bool = True,
    compress_tool_results: bool = False,
    compression_manager: Optional["CompressionManager"] = None,
    metadata: Optional[Dict[str, Any]] = None,
    reasoning: bool = False,
    reasoning_model: Optional[Union[Model, str]] = None,
    reasoning_agent: Optional[Agent] = None,
    reasoning_min_steps: int = 1,
    reasoning_max_steps: int = 10,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    store_events: bool = False,
    events_to_skip: Optional[List[Union[RunEvent, TeamRunEvent]]] = None,
    store_member_responses: bool = False,
    stream_member_events: bool = True,
    debug_mode: bool = False,
    debug_level: Literal[1, 2] = 1,
    show_members_responses: bool = False,
    retries: int = 0,
    delay_between_retries: int = 1,
    exponential_backoff: bool = False,
    telemetry: bool = True,
    cache_callables: bool = True,
    callable_tools_cache_key: Optional[Callable[..., Optional[str]]] = None,
    callable_knowledge_cache_key: Optional[Callable[..., Optional[str]]] = None,
    callable_members_cache_key: Optional[Callable[..., Optional[str]]] = None,
):
    from agno.utils.callables import is_callable_factory

    team.members = members

    team.model = model  # type: ignore[assignment]

    team.name = name
    team.id = id
    team.role = role

    team.respond_directly = respond_directly
    team.determine_input_for_members = determine_input_for_members
    team.delegate_to_all_members = delegate_to_all_members
    team.max_iterations = max_iterations

    # Resolve TeamMode: explicit mode wins, otherwise infer from booleans
    from agno.team.mode import TeamMode

    if mode is not None:
        team.mode = mode
        # Normalize booleans deterministically so conflicting flags can't leak through
        if mode == TeamMode.route:
            team.respond_directly = True
            team.delegate_to_all_members = False
        elif mode == TeamMode.broadcast:
            team.delegate_to_all_members = True
            team.respond_directly = False
        elif mode in (TeamMode.coordinate, TeamMode.tasks):
            team.respond_directly = False
            team.delegate_to_all_members = False
    else:
        if team.respond_directly:
            team.mode = TeamMode.route
        elif team.delegate_to_all_members:
            team.mode = TeamMode.broadcast
        else:
            team.mode = TeamMode.coordinate

    team.user_id = user_id
    team.session_id = session_id
    team.session_state = session_state
    team.add_session_state_to_context = add_session_state_to_context
    team.enable_agentic_state = enable_agentic_state
    team.overwrite_db_session_state = overwrite_db_session_state
    team.resolve_in_context = resolve_in_context
    team.cache_session = cache_session

    team.add_history_to_context = add_history_to_context
    team.num_history_runs = num_history_runs
    team.num_history_messages = num_history_messages
    if team.num_history_messages is not None and team.num_history_runs is not None:
        log_warning("num_history_messages and num_history_runs cannot be set at the same time. Using num_history_runs.")
        team.num_history_messages = None
    if team.num_history_messages is None and team.num_history_runs is None:
        team.num_history_runs = 3

    team.max_tool_calls_from_history = max_tool_calls_from_history

    team.add_team_history_to_members = add_team_history_to_members
    team.num_team_history_runs = num_team_history_runs
    team.search_session_history = search_session_history
    team.num_history_sessions = num_history_sessions

    team.description = description
    team.instructions = instructions
    team.use_instruction_tags = use_instruction_tags
    team.expected_output = expected_output
    team.additional_context = additional_context
    team.markdown = markdown
    team.add_datetime_to_context = add_datetime_to_context
    team.add_location_to_context = add_location_to_context
    team.add_name_to_context = add_name_to_context
    team.timezone_identifier = timezone_identifier
    team.add_member_tools_to_context = add_member_tools_to_context
    team.system_message = system_message
    team.system_message_role = system_message_role
    team.introduction = introduction
    team.additional_input = additional_input

    team.dependencies = dependencies
    team.add_dependencies_to_context = add_dependencies_to_context

    team.knowledge = knowledge
    team.knowledge_filters = knowledge_filters
    team.enable_agentic_knowledge_filters = enable_agentic_knowledge_filters
    team.update_knowledge = update_knowledge
    team.add_knowledge_to_context = add_knowledge_to_context
    team.knowledge_retriever = knowledge_retriever
    team.references_format = references_format

    team.share_member_interactions = share_member_interactions
    team.include_tool_results_in_member_response = include_tool_results_in_member_response
    team.get_member_information_tool = get_member_information_tool
    team.search_knowledge = search_knowledge
    team.add_search_knowledge_instructions = add_search_knowledge_instructions
    team.read_chat_history = read_chat_history

    team.store_media = store_media
    team.store_tool_messages = store_tool_messages
    team.store_history_messages = store_history_messages
    team.send_media_to_model = send_media_to_model

    if tools is None:
        team.tools = None
    elif is_callable_factory(tools, excluded_types=(Toolkit, Function)):
        team.tools = tools  # type: ignore[assignment]
    else:
        team.tools = list(tools) if tools else []  # type: ignore[arg-type]
    team.tool_choice = tool_choice
    team.tool_call_limit = tool_call_limit
    team.tool_hooks = tool_hooks

    # Initialize hooks
    team.pre_hooks = pre_hooks
    team.post_hooks = post_hooks

    team.input_schema = input_schema
    team.output_schema = output_schema
    team.parser_model = parser_model  # type: ignore[assignment]
    team.parser_model_prompt = parser_model_prompt
    team.output_model = output_model  # type: ignore[assignment]
    team.output_model_prompt = output_model_prompt
    team.use_json_mode = use_json_mode
    team.parse_response = parse_response

    team.db = db

    team.enable_agentic_memory = enable_agentic_memory

    if enable_user_memories is not None:
        team.update_memory_on_run = enable_user_memories
    else:
        team.update_memory_on_run = update_memory_on_run
    team.enable_user_memories = team.update_memory_on_run  # Soon to be deprecated. Use update_memory_on_run

    team.add_memories_to_context = add_memories_to_context
    team.memory_manager = memory_manager
    team.enable_session_summaries = enable_session_summaries
    team.session_summary_manager = session_summary_manager
    team.add_session_summary_to_context = add_session_summary_to_context

    team.learning = learning
    team.add_learnings_to_context = add_learnings_to_context

    # Context compression settings
    team.compress_tool_results = compress_tool_results
    team.compression_manager = compression_manager

    team.metadata = metadata

    team.reasoning = reasoning
    team.reasoning_model = reasoning_model  # type: ignore[assignment]
    team.reasoning_agent = reasoning_agent
    team.reasoning_min_steps = reasoning_min_steps
    team.reasoning_max_steps = reasoning_max_steps

    team.stream = stream
    team.stream_events = stream_events
    team.store_events = store_events
    team.store_member_responses = store_member_responses

    team.events_to_skip = events_to_skip
    if team.events_to_skip is None:
        team.events_to_skip = [
            RunEvent.run_content,
            TeamRunEvent.run_content,
        ]
    team.stream_member_events = stream_member_events

    team.debug_mode = debug_mode
    if debug_level not in [1, 2]:
        log_warning(f"Invalid debug level: {debug_level}. Setting to 1.")
        debug_level = 1
    team.debug_level = debug_level
    team.show_members_responses = show_members_responses

    team.retries = retries
    team.delay_between_retries = delay_between_retries
    team.exponential_backoff = exponential_backoff

    team.telemetry = telemetry

    # TODO: Remove these
    # Images generated during this session
    team.images = None
    # Audio generated during this session
    team.audio = None
    # Videos generated during this session
    team.videos = None

    # Team session
    team._cached_session = None

    team._tool_instructions = None

    # True if we should parse a member response model
    team._member_response_model = None

    team._formatter = None

    team._hooks_normalised = False

    # List of MCP tools that were initialized on the last run
    team._mcp_tools_initialized_on_run = []
    # List of connectable tools that were initialized on the last run
    team._connectable_tools_initialized_on_run = []

    # Internal resolved LearningMachine instance
    team._learning = None

    # Lazy-initialized shared thread pool executor for background tasks (memory, cultural knowledge, etc.)
    team._background_executor = None

    # Callable factory settings
    team.cache_callables = cache_callables
    team.callable_tools_cache_key = callable_tools_cache_key
    team.callable_knowledge_cache_key = callable_knowledge_cache_key
    team.callable_members_cache_key = callable_members_cache_key
    team._callable_tools_cache = {}
    team._callable_knowledge_cache = {}
    team._callable_members_cache = {}

    _resolve_models(
        team,
    )


def background_executor(team: "Team") -> Any:
    """Lazy initialization of shared thread pool executor for background tasks.

    Handles both memory creation and cultural knowledge updates concurrently.
    Initialized only on first use (runtime, not instantiation) and reused across runs.
    """
    if team._background_executor is None:
        from concurrent.futures import ThreadPoolExecutor

        team._background_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="agno-bg")
    return team._background_executor


def cached_session(team: "Team") -> Optional[TeamSession]:
    return team._cached_session


def set_id(team: "Team") -> None:
    """Set the ID of the team if not set yet.

    If the ID is not provided, generate a deterministic UUID from the name.
    If the name is not provided, generate a random UUID.
    """
    if team.id is None:
        team.id = generate_id_from_name(team.name)


def _set_debug(team: "Team", debug_mode: Optional[bool] = None) -> None:
    # Get the debug level from the environment variable or the default debug level
    debug_level: Literal[1, 2] = (
        cast(Literal[1, 2], int(env)) if (env := getenv("AGNO_DEBUG_LEVEL")) in ("1", "2") else team.debug_level
    )
    # If the default debug mode is set, or passed on run, or via environment variable, set the debug mode to True
    if team.debug_mode or debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
        set_log_level_to_debug(source_type="team", level=debug_level)
    else:
        set_log_level_to_info(source_type="team")


def _set_telemetry(team: "Team") -> None:
    """Override telemetry settings based on environment variables."""

    telemetry_env = getenv("AGNO_TELEMETRY")
    if telemetry_env is not None:
        team.telemetry = telemetry_env.lower() == "true"


def _initialize_member(team: "Team", member: Union["Team", Agent], debug_mode: Optional[bool] = None) -> None:
    from agno.team.team import Team

    # Set debug mode for all members
    if debug_mode:
        member.debug_mode = True
        member.debug_level = team.debug_level

    if isinstance(member, Agent):
        member.team_id = team.id
        member.set_id()

        # Inherit team primary model if agent has no explicit model
        if member.model is None and team.model is not None:
            member.model = team.model
            log_info(f"Agent '{member.name or member.id}' inheriting model from Team: {team.model.id}")

    elif isinstance(member, Team):
        member.parent_team_id = team.id
        member.set_id()
        # Initialize the sub-team's model first so it has its model set
        member._set_default_model()
        # Then let the sub-team initialize its own members so they inherit from the sub-team
        # Only iterate if members is a static list (not a callable factory)
        if isinstance(member.members, list):
            for sub_member in member.members:
                member._initialize_member(sub_member, debug_mode=debug_mode)


def propagate_run_hooks_in_background(team: "Team", run_in_background: bool = True) -> None:
    """
    Propagate _run_hooks_in_background setting to this team and all nested members recursively.

    This method sets _run_hooks_in_background on the team and all its members (agents and nested teams).
    For nested teams, it recursively propagates the setting to their members as well.

    Args:
        run_in_background: Whether hooks should run in background. Defaults to True.
    """
    from agno.team.team import Team

    team._run_hooks_in_background = run_in_background

    # Only iterate if members is a static list (not a callable factory)
    if not isinstance(team.members, list):
        return

    for member in team.members:
        if hasattr(member, "_run_hooks_in_background"):
            member._run_hooks_in_background = run_in_background

        # If it's a nested team, recursively propagate to its members
        if isinstance(member, Team):
            member.propagate_run_hooks_in_background(run_in_background)


def _set_default_model(team: "Team") -> None:
    # Set the default model
    if team.model is None:
        try:
            from agno.models.openai import OpenAIChat
        except ModuleNotFoundError as e:
            log_exception(e)
            log_error(
                "Agno agents use `openai` as the default model provider. Please provide a `model` or install `openai`."
            )
            exit(1)

        log_info("Setting default model to OpenAI Chat")
        team.model = OpenAIChat(id="gpt-4o")


def _set_memory_manager(team: "Team") -> None:
    if team.db is None:
        log_warning("Database not provided. Memories will not be stored.")

    if team.memory_manager is None:
        team.memory_manager = MemoryManager(model=team.model, db=team.db)
    else:
        if team.memory_manager.model is None:
            team.memory_manager.model = team.model
        if team.memory_manager.db is None:
            team.memory_manager.db = team.db

    if team.add_memories_to_context is None:
        team.add_memories_to_context = (
            team.update_memory_on_run or team.enable_agentic_memory or team.memory_manager is not None
        )


def _set_session_summary_manager(team: "Team") -> None:
    if team.enable_session_summaries and team.session_summary_manager is None:
        team.session_summary_manager = SessionSummaryManager(model=team.model)

    if team.session_summary_manager is not None:
        if team.session_summary_manager.model is None:
            team.session_summary_manager.model = team.model

    if team.add_session_summary_to_context is None:
        team.add_session_summary_to_context = team.enable_session_summaries or team.session_summary_manager is not None


def _set_compression_manager(team: "Team") -> None:
    if team.compress_tool_results and team.compression_manager is None:
        team.compression_manager = CompressionManager(
            model=team.model,
        )
    elif team.compression_manager is not None and team.compression_manager.model is None:
        # If compression manager exists but has no model, use the team's model
        team.compression_manager.model = team.model

    if team.compression_manager is not None:
        if team.compression_manager.model is None:
            team.compression_manager.model = team.model
        if team.compression_manager.compress_tool_results:
            team.compress_tool_results = True


def _set_learning_machine(team: "Team") -> None:
    """Initialize LearningMachine with team's db and model.

    Sets the internal _learning field without modifying the public learning field.

    Handles:
    - learning=True: Create default LearningMachine
    - learning=False/None: Disabled
    - learning=LearningMachine(...): Use provided, inject db/model
    """
    team._learning_init_attempted = True

    if team.learning is None or team.learning is False:
        team._learning = None
        return

    if team.db is None:
        log_warning("Database not provided. LearningMachine not initialized.")
        team._learning = None
        return

    if team.learning is True:
        team._learning = LearningMachine(db=team.db, model=team.model, user_profile=True, user_memory=True)
        return

    if isinstance(team.learning, LearningMachine):
        if team.learning.db is None:
            team.learning.db = team.db
        if team.learning.model is None:
            team.learning.model = team.model
        team._learning = team.learning


def _initialize_session(
    team: "Team",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Initialize the session for the team."""

    if session_id is None:
        if team.session_id:
            session_id = team.session_id
        else:
            session_id = str(uuid4())
            # We make the session_id sticky to the agent instance if no session_id is provided
            team.session_id = session_id

    log_debug(f"Session ID: {session_id}", center=True)

    # Use the default user_id when necessary
    if user_id is None or user_id == "":
        user_id = team.user_id

    return session_id, user_id


def _initialize_session_state(
    team: "Team",
    session_state: Dict[str, Any],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Initialize the session state for the team."""
    if user_id:
        session_state["current_user_id"] = user_id
    if session_id is not None:
        session_state["current_session_id"] = session_id
    if run_id is not None:
        session_state["current_run_id"] = run_id
    return session_state


def _has_async_db(team: "Team") -> bool:
    """Return True if the db the team is equipped with is an Async implementation"""
    return team.db is not None and isinstance(team.db, AsyncBaseDb)


def _resolve_models(team: "Team") -> None:
    """Resolve model strings to Model instances."""
    if team.model is not None:
        team.model = get_model(team.model)
    if team.reasoning_model is not None:
        team.reasoning_model = get_model(team.reasoning_model)
    if team.parser_model is not None:
        team.parser_model = get_model(team.parser_model)
    if team.output_model is not None:
        team.output_model = get_model(team.output_model)


def initialize_team(team: "Team", debug_mode: Optional[bool] = None) -> None:
    # Make sure for the team, we are using the team logger
    use_team_logger()

    if team.delegate_to_all_members and team.respond_directly:
        log_warning(
            "`delegate_to_all_members` and `respond_directly` are both enabled. The task will be delegated to all members, but `respond_directly` will be disabled."
        )
        team.respond_directly = False

    _set_default_model(team)

    # Set debug mode
    _set_debug(team, debug_mode=debug_mode)

    # Set the team ID if not set
    team.set_id()

    # Set the memory manager and session summary manager
    if team.update_memory_on_run or team.enable_agentic_memory or team.memory_manager is not None:
        _set_memory_manager(team)
    if team.enable_session_summaries or team.session_summary_manager is not None:
        _set_session_summary_manager(team)
    if team.compress_tool_results or team.compression_manager is not None:
        _set_compression_manager(team)
    if team.learning is not None and team.learning is not False:
        _set_learning_machine(team)

    log_debug(f"Team ID: {team.id}", center=True)

    # Initialize formatter
    if team._formatter is None:
        team._formatter = SafeFormatter()

    # Only initialize members if they are a static list (not a callable factory)
    if isinstance(team.members, list):
        for member in team.members:
            _initialize_member(team, member, debug_mode=team.debug_mode)


def add_tool(team: "Team", tool: Union[Toolkit, Callable, Function, Dict]) -> None:
    from agno.utils.callables import is_callable_factory

    if is_callable_factory(team.tools, excluded_types=(Toolkit, Function)):
        raise RuntimeError(
            "Cannot add_tool() when tools is a callable factory. Use set_tools() to replace the factory."
        )
    if not team.tools:
        team.tools = []
    team.tools.append(tool)  # type: ignore[union-attr]


def set_tools(team: "Team", tools: Union[List[Union[Toolkit, Callable, Function, Dict]], Callable[..., List]]) -> None:
    from agno.utils.callables import is_callable_factory

    if is_callable_factory(tools, excluded_types=(Toolkit, Function)):
        team.tools = tools  # type: ignore[assignment]
        team._callable_tools_cache.clear()
    else:
        team.tools = list(tools) if tools else []  # type: ignore[arg-type]


async def _connect_mcp_tools(team: "Team") -> None:
    """Connect the MCP tools to the agent."""
    if team.tools is not None and isinstance(team.tools, list):
        for tool in team.tools:
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if (
                hasattr(type(tool), "__mro__")
                and any(c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__)
                and not tool.initialized  # type: ignore
            ):
                try:
                    # Connect the MCP server
                    await tool.connect()  # type: ignore
                    team._mcp_tools_initialized_on_run.append(tool)  # type: ignore[union-attr]
                except Exception as e:
                    log_warning(f"Error connecting tool: {str(e)}")


async def _disconnect_mcp_tools(team: "Team") -> None:
    """Disconnect the MCP tools from the agent."""
    for tool in team._mcp_tools_initialized_on_run:  # type: ignore[union-attr]
        try:
            await tool.close()
        except Exception as e:
            log_warning(f"Error disconnecting tool: {str(e)}")
    team._mcp_tools_initialized_on_run = []


def _connect_connectable_tools(team: "Team") -> None:
    """Connect tools that require connection management (e.g., database connections)."""
    if team.tools and isinstance(team.tools, list):
        for tool in team.tools:
            if (
                hasattr(tool, "requires_connect")
                and tool.requires_connect  # type: ignore
                and hasattr(tool, "connect")
                and tool not in team._connectable_tools_initialized_on_run  # type: ignore[operator]
            ):
                try:
                    tool.connect()  # type: ignore
                    team._connectable_tools_initialized_on_run.append(tool)  # type: ignore[union-attr]
                except Exception as e:
                    log_warning(f"Error connecting tool: {str(e)}")


def _disconnect_connectable_tools(team: "Team") -> None:
    """Disconnect tools that require connection management."""
    for tool in team._connectable_tools_initialized_on_run:  # type: ignore[union-attr]
        if hasattr(tool, "close"):
            try:
                tool.close()  # type: ignore
            except Exception as e:
                log_warning(f"Error disconnecting tool: {str(e)}")
    team._connectable_tools_initialized_on_run = []
