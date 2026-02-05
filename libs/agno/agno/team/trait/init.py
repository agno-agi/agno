"""Initialization and configuration trait for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
from agno.media import Audio, Image, Video
from agno.memory import MemoryManager
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.run.agent import RunEvent
from agno.run.team import (
    TeamRunEvent,
)
from agno.session import SessionSummaryManager, TeamSession
from agno.team.trait.base import TeamTraitBase
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


def _team_type() -> type["Team"]:
    from agno.team.team import Team

    return Team


class TeamInitTrait(TeamTraitBase):
    def __init__(
        self,
        members: List[Union[Agent, "Team"]],
        id: Optional[str] = None,
        model: Optional[Union[Model, str]] = None,
        name: Optional[str] = None,
        role: Optional[str] = None,
        respond_directly: bool = False,
        determine_input_for_members: bool = True,
        delegate_to_all_members: bool = False,
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
        knowledge: Optional[KnowledgeProtocol] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_knowledge_to_context: bool = False,
        enable_agentic_knowledge_filters: Optional[bool] = False,
        update_knowledge: bool = False,
        knowledge_retriever: Optional[Callable[..., Optional[List[Union[Dict, str]]]]] = None,
        references_format: Literal["json", "yaml"] = "json",
        share_member_interactions: bool = False,
        get_member_information_tool: bool = False,
        search_knowledge: bool = True,
        add_search_knowledge_instructions: bool = True,
        read_chat_history: bool = False,
        store_media: bool = True,
        store_tool_messages: bool = True,
        store_history_messages: bool = True,
        send_media_to_model: bool = True,
        add_history_to_context: bool = False,
        num_history_runs: Optional[int] = None,
        num_history_messages: Optional[int] = None,
        max_tool_calls_from_history: Optional[int] = None,
        tools: Optional[List[Union[Toolkit, Callable, Function, Dict]]] = None,
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
    ):
        self.members = members

        self.model = model  # type: ignore[assignment]

        self.name = name
        self.id = id
        self.role = role

        self.respond_directly = respond_directly
        self.determine_input_for_members = determine_input_for_members
        self.delegate_to_all_members = delegate_to_all_members

        self.user_id = user_id
        self.session_id = session_id
        self.session_state = session_state
        self.add_session_state_to_context = add_session_state_to_context
        self.enable_agentic_state = enable_agentic_state
        self.overwrite_db_session_state = overwrite_db_session_state
        self.resolve_in_context = resolve_in_context
        self.cache_session = cache_session

        self.add_history_to_context = add_history_to_context
        self.num_history_runs = num_history_runs
        self.num_history_messages = num_history_messages
        if self.num_history_messages is not None and self.num_history_runs is not None:
            log_warning(
                "num_history_messages and num_history_runs cannot be set at the same time. Using num_history_runs."
            )
            self.num_history_messages = None
        if self.num_history_messages is None and self.num_history_runs is None:
            self.num_history_runs = 3

        self.max_tool_calls_from_history = max_tool_calls_from_history

        self.add_team_history_to_members = add_team_history_to_members
        self.num_team_history_runs = num_team_history_runs
        self.search_session_history = search_session_history
        self.num_history_sessions = num_history_sessions

        self.description = description
        self.instructions = instructions
        self.use_instruction_tags = use_instruction_tags
        self.expected_output = expected_output
        self.additional_context = additional_context
        self.markdown = markdown
        self.add_datetime_to_context = add_datetime_to_context
        self.add_location_to_context = add_location_to_context
        self.add_name_to_context = add_name_to_context
        self.timezone_identifier = timezone_identifier
        self.add_member_tools_to_context = add_member_tools_to_context
        self.system_message = system_message
        self.system_message_role = system_message_role
        self.introduction = introduction
        self.additional_input = additional_input

        self.dependencies = dependencies
        self.add_dependencies_to_context = add_dependencies_to_context

        self.knowledge = knowledge
        self.knowledge_filters = knowledge_filters
        self.enable_agentic_knowledge_filters = enable_agentic_knowledge_filters
        self.update_knowledge = update_knowledge
        self.add_knowledge_to_context = add_knowledge_to_context
        self.knowledge_retriever = knowledge_retriever
        self.references_format = references_format

        self.share_member_interactions = share_member_interactions
        self.get_member_information_tool = get_member_information_tool
        self.search_knowledge = search_knowledge
        self.add_search_knowledge_instructions = add_search_knowledge_instructions
        self.read_chat_history = read_chat_history

        self.store_media = store_media
        self.store_tool_messages = store_tool_messages
        self.store_history_messages = store_history_messages
        self.send_media_to_model = send_media_to_model

        self.tools = tools
        self.tool_choice = tool_choice
        self.tool_call_limit = tool_call_limit
        self.tool_hooks = tool_hooks

        # Initialize hooks
        self.pre_hooks = pre_hooks
        self.post_hooks = post_hooks

        self.input_schema = input_schema
        self.output_schema = output_schema
        self.parser_model = parser_model  # type: ignore[assignment]
        self.parser_model_prompt = parser_model_prompt
        self.output_model = output_model  # type: ignore[assignment]
        self.output_model_prompt = output_model_prompt
        self.use_json_mode = use_json_mode
        self.parse_response = parse_response

        self.db = db

        self.enable_agentic_memory = enable_agentic_memory

        if enable_user_memories is not None:
            self.update_memory_on_run = enable_user_memories
        else:
            self.update_memory_on_run = update_memory_on_run
        self.enable_user_memories = self.update_memory_on_run  # Soon to be deprecated. Use update_memory_on_run

        self.add_memories_to_context = add_memories_to_context
        self.memory_manager = memory_manager
        self.enable_session_summaries = enable_session_summaries
        self.session_summary_manager = session_summary_manager
        self.add_session_summary_to_context = add_session_summary_to_context

        # Context compression settings
        self.compress_tool_results = compress_tool_results
        self.compression_manager = compression_manager

        self.metadata = metadata

        self.reasoning = reasoning
        self.reasoning_model = reasoning_model  # type: ignore[assignment]
        self.reasoning_agent = reasoning_agent
        self.reasoning_min_steps = reasoning_min_steps
        self.reasoning_max_steps = reasoning_max_steps

        self.stream = stream
        self.stream_events = stream_events
        self.store_events = store_events
        self.store_member_responses = store_member_responses

        self.events_to_skip = events_to_skip
        if self.events_to_skip is None:
            self.events_to_skip = [
                RunEvent.run_content,
                TeamRunEvent.run_content,
            ]
        self.stream_member_events = stream_member_events

        self.debug_mode = debug_mode
        if debug_level not in [1, 2]:
            log_warning(f"Invalid debug level: {debug_level}. Setting to 1.")
            debug_level = 1
        self.debug_level = debug_level
        self.show_members_responses = show_members_responses

        self.retries = retries
        self.delay_between_retries = delay_between_retries
        self.exponential_backoff = exponential_backoff

        self.telemetry = telemetry

        # TODO: Remove these
        # Images generated during this session
        self.images: Optional[List[Image]] = None
        # Audio generated during this session
        self.audio: Optional[List[Audio]] = None
        # Videos generated during this session
        self.videos: Optional[List[Video]] = None

        # Team session
        self._cached_session: Optional[TeamSession] = None

        self._tool_instructions: Optional[List[str]] = None

        # True if we should parse a member response model
        self._member_response_model: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None

        self._formatter: Optional[SafeFormatter] = None

        self._hooks_normalised = False

        # List of MCP tools that were initialized on the last run
        self._mcp_tools_initialized_on_run: List[Any] = []
        # List of connectable tools that were initialized on the last run
        self._connectable_tools_initialized_on_run: List[Any] = []

        # Lazy-initialized shared thread pool executor for background tasks (memory, cultural knowledge, etc.)
        self._background_executor: Optional[Any] = None

        self._resolve_models()

    @property
    def background_executor(self) -> Any:
        """Lazy initialization of shared thread pool executor for background tasks.

        Handles both memory creation and cultural knowledge updates concurrently.
        Initialized only on first use (runtime, not instantiation) and reused across runs.
        """
        if self._background_executor is None:
            from concurrent.futures import ThreadPoolExecutor

            self._background_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="agno-bg")
        return self._background_executor

    @property
    def cached_session(self) -> Optional[TeamSession]:
        return self._cached_session

    def set_id(self) -> None:
        """Set the ID of the team if not set yet.

        If the ID is not provided, generate a deterministic UUID from the name.
        If the name is not provided, generate a random UUID.
        """
        if self.id is None:
            self.id = generate_id_from_name(self.name)

    def _set_debug(self, debug_mode: Optional[bool] = None) -> None:
        # Get the debug level from the environment variable or the default debug level
        debug_level: Literal[1, 2] = (
            cast(Literal[1, 2], int(env)) if (env := getenv("AGNO_DEBUG_LEVEL")) in ("1", "2") else self.debug_level
        )
        # If the default debug mode is set, or passed on run, or via environment variable, set the debug mode to True
        if self.debug_mode or debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            set_log_level_to_debug(source_type="team", level=debug_level)
        else:
            set_log_level_to_info(source_type="team")

    def _set_telemetry(self) -> None:
        """Override telemetry settings based on environment variables."""

        telemetry_env = getenv("AGNO_TELEMETRY")
        if telemetry_env is not None:
            self.telemetry = telemetry_env.lower() == "true"

    def _initialize_member(self, member: Union["Team", Agent], debug_mode: Optional[bool] = None) -> None:
        # Set debug mode for all members
        if debug_mode:
            member.debug_mode = True
            member.debug_level = self.debug_level

        if isinstance(member, Agent):
            member.team_id = self.id
            member.set_id()

            # Inherit team primary model if agent has no explicit model
            if member.model is None and self.model is not None:
                member.model = self.model
                log_info(f"Agent '{member.name or member.id}' inheriting model from Team: {self.model.id}")

        elif isinstance(member, _team_type()):
            member.parent_team_id = self.id
            # Initialize the sub-team's model first so it has its model set
            member._set_default_model()
            # Then let the sub-team initialize its own members so they inherit from the sub-team
            for sub_member in member.members:
                member._initialize_member(sub_member, debug_mode=debug_mode)

    def propagate_run_hooks_in_background(self, run_in_background: bool = True) -> None:
        """
        Propagate _run_hooks_in_background setting to this team and all nested members recursively.

        This method sets _run_hooks_in_background on the team and all its members (agents and nested teams).
        For nested teams, it recursively propagates the setting to their members as well.

        Args:
            run_in_background: Whether hooks should run in background. Defaults to True.
        """
        self._run_hooks_in_background = run_in_background

        for member in self.members:
            if hasattr(member, "_run_hooks_in_background"):
                member._run_hooks_in_background = run_in_background

            # If it's a nested team, recursively propagate to its members
            if isinstance(member, _team_type()):
                member.propagate_run_hooks_in_background(run_in_background)

    def _set_default_model(self) -> None:
        # Set the default model
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                log_exception(e)
                log_error(
                    "Agno agents use `openai` as the default model provider. "
                    "Please provide a `model` or install `openai`."
                )
                exit(1)

            log_info("Setting default model to OpenAI Chat")
            self.model = OpenAIChat(id="gpt-4o")

    def _set_memory_manager(self) -> None:
        if self.db is None:
            log_warning("Database not provided. Memories will not be stored.")

        if self.memory_manager is None:
            self.memory_manager = MemoryManager(model=self.model, db=self.db)
        else:
            if self.memory_manager.model is None:
                self.memory_manager.model = self.model
            if self.memory_manager.db is None:
                self.memory_manager.db = self.db

        if self.add_memories_to_context is None:
            self.add_memories_to_context = (
                self.update_memory_on_run or self.enable_agentic_memory or self.memory_manager is not None
            )

    def _set_session_summary_manager(self) -> None:
        if self.enable_session_summaries and self.session_summary_manager is None:
            self.session_summary_manager = SessionSummaryManager(model=self.model)

        if self.session_summary_manager is not None:
            if self.session_summary_manager.model is None:
                self.session_summary_manager.model = self.model

        if self.add_session_summary_to_context is None:
            self.add_session_summary_to_context = (
                self.enable_session_summaries or self.session_summary_manager is not None
            )

    def _set_compression_manager(self) -> None:
        if self.compress_tool_results and self.compression_manager is None:
            self.compression_manager = CompressionManager(
                model=self.model,
            )
        elif self.compression_manager is not None and self.compression_manager.model is None:
            # If compression manager exists but has no model, use the team's model
            self.compression_manager.model = self.model

        if self.compression_manager is not None:
            if self.compression_manager.model is None:
                self.compression_manager.model = self.model
            if self.compression_manager.compress_tool_results:
                self.compress_tool_results = True

    def _initialize_session(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """Initialize the session for the team."""

        if session_id is None:
            if self.session_id:
                session_id = self.session_id
            else:
                session_id = str(uuid4())
                # We make the session_id sticky to the agent instance if no session_id is provided
                self.session_id = session_id

        log_debug(f"Session ID: {session_id}", center=True)

        # Use the default user_id when necessary
        if user_id is None or user_id == "":
            user_id = self.user_id

        return session_id, user_id

    def _initialize_session_state(
        self,
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

    def _has_async_db(self) -> bool:
        """Return True if the db the team is equipped with is an Async implementation"""
        return self.db is not None and isinstance(self.db, AsyncBaseDb)

    def _resolve_models(self) -> None:
        """Resolve model strings to Model instances."""
        if self.model is not None:
            self.model = get_model(self.model)
        if self.reasoning_model is not None:
            self.reasoning_model = get_model(self.reasoning_model)
        if self.parser_model is not None:
            self.parser_model = get_model(self.parser_model)
        if self.output_model is not None:
            self.output_model = get_model(self.output_model)

    def initialize_team(self, debug_mode: Optional[bool] = None) -> None:
        # Make sure for the team, we are using the team logger
        use_team_logger()

        if self.delegate_to_all_members and self.respond_directly:
            log_warning(
                "`delegate_to_all_members` and `respond_directly` are both enabled. The task will be delegated to all members, but `respond_directly` will be disabled."
            )
            self.respond_directly = False

        self._set_default_model()

        # Set debug mode
        self._set_debug(debug_mode=debug_mode)

        # Set the team ID if not set
        self.set_id()

        # Set the memory manager and session summary manager
        if self.update_memory_on_run or self.enable_agentic_memory or self.memory_manager is not None:
            self._set_memory_manager()
        if self.enable_session_summaries or self.session_summary_manager is not None:
            self._set_session_summary_manager()
        if self.compress_tool_results or self.compression_manager is not None:
            self._set_compression_manager()

        log_debug(f"Team ID: {self.id}", center=True)

        # Initialize formatter
        if self._formatter is None:
            self._formatter = SafeFormatter()

        for member in self.members:
            self._initialize_member(member, debug_mode=self.debug_mode)

    def add_tool(self, tool: Union[Toolkit, Callable, Function, Dict]):
        if not self.tools:
            self.tools = []
        self.tools.append(tool)

    def set_tools(self, tools: List[Union[Toolkit, Callable, Function, Dict]]):
        self.tools = tools

    async def _connect_mcp_tools(self) -> None:
        """Connect the MCP tools to the agent."""
        if self.tools is not None:
            for tool in self.tools:
                # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
                if (
                    hasattr(type(tool), "__mro__")
                    and any(c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__)
                    and not tool.initialized  # type: ignore
                ):
                    try:
                        # Connect the MCP server
                        await tool.connect()  # type: ignore
                        self._mcp_tools_initialized_on_run.append(tool)
                    except Exception as e:
                        log_warning(f"Error connecting tool: {str(e)}")

    async def _disconnect_mcp_tools(self) -> None:
        """Disconnect the MCP tools from the agent."""
        for tool in self._mcp_tools_initialized_on_run:
            try:
                await tool.close()
            except Exception as e:
                log_warning(f"Error disconnecting tool: {str(e)}")
        self._mcp_tools_initialized_on_run = []

    def _connect_connectable_tools(self) -> None:
        """Connect tools that require connection management (e.g., database connections)."""
        if self.tools:
            for tool in self.tools:
                if (
                    hasattr(tool, "requires_connect")
                    and tool.requires_connect  # type: ignore
                    and hasattr(tool, "connect")
                    and tool not in self._connectable_tools_initialized_on_run
                ):
                    try:
                        tool.connect()  # type: ignore
                        self._connectable_tools_initialized_on_run.append(tool)
                    except Exception as e:
                        log_warning(f"Error connecting tool: {str(e)}")

    def _disconnect_connectable_tools(self) -> None:
        """Disconnect tools that require connection management."""
        for tool in self._connectable_tools_initialized_on_run:
            if hasattr(tool, "close"):
                try:
                    tool.close()  # type: ignore
                except Exception as e:
                    log_warning(f"Error disconnecting tool: {str(e)}")
        self._connectable_tools_initialized_on_run = []
