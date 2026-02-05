from __future__ import annotations

from os import getenv
from typing import (
    Any,
    Callable,
    Dict,
    Literal,
    Optional,
    Sequence,
    Union,
    cast,
)

from agno.agent._agent_facet_base import AgentFacetBase
from agno.compression.manager import CompressionManager
from agno.culture.manager import CultureManager
from agno.db.base import AsyncBaseDb
from agno.learn.machine import LearningMachine
from agno.memory import MemoryManager
from agno.models.utils import get_model
from agno.session import AgentSession, SessionSummaryManager
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
)
from agno.utils.safe_formatter import SafeFormatter
from agno.utils.string import generate_id_from_name


class AgentInitFacet(AgentFacetBase):
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
    def cached_session(self) -> Optional[AgentSession]:
        return self._cached_session

    def set_id(self) -> None:
        if self.id is None:
            self.id = generate_id_from_name(self.name)

    def _set_debug(self, debug_mode: Optional[bool] = None) -> None:
        # Get the debug level from the environment variable or the default debug level
        debug_level: Literal[1, 2] = (
            cast(Literal[1, 2], int(env)) if (env := getenv("AGNO_DEBUG_LEVEL")) in ("1", "2") else self.debug_level
        )
        # If the default debug mode is set, or passed on run, or via environment variable, set the debug mode to True
        if self.debug_mode or debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            set_log_level_to_debug(level=debug_level)
        else:
            set_log_level_to_info()

    def _set_telemetry(self) -> None:
        """Override telemetry settings based on environment variables."""

        telemetry_env = getenv("AGNO_TELEMETRY")
        if telemetry_env is not None:
            self.telemetry = telemetry_env.lower() == "true"

    def _set_default_model(self) -> None:
        # Use the default Model (OpenAIChat) if no model is provided
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

    def _set_culture_manager(self) -> None:
        if self.db is None:
            log_warning("Database not provided. Cultural knowledge will not be stored.")

        if self.culture_manager is None:
            self.culture_manager = CultureManager(model=self.model, db=self.db)
        else:
            if self.culture_manager.model is None:
                self.culture_manager.model = self.model
            if self.culture_manager.db is None:
                self.culture_manager.db = self.db

        if self.add_culture_to_context is None:
            self.add_culture_to_context = (
                self.enable_agentic_culture or self.update_cultural_knowledge or self.culture_manager is not None
            )

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

    def _set_learning_machine(self) -> None:
        """Initialize LearningMachine with agent's db and model.

        Sets the internal _learning field without modifying the public learning field.

        Handles:
        - learning=True: Create default LearningMachine
        - learning=False/None: Disabled
        - learning=LearningMachine(...): Use provided, inject db/model/knowledge
        """
        # Handle learning=False or learning=None
        if self.learning is None or self.learning is False:
            self._learning = None
            return

        # Check db requirement
        if self.db is None:
            log_warning("Database not provided. LearningMachine not initialized.")
            self._learning = None
            return

        # Handle learning=True: create default LearningMachine
        # Enables user_profile (structured fields) and user_memory (unstructured observations)
        if self.learning is True:
            self._learning = LearningMachine(db=self.db, model=self.model, user_profile=True, user_memory=True)
            return

        # Handle learning=LearningMachine(...): inject dependencies
        if isinstance(self.learning, LearningMachine):
            if self.learning.db is None:
                self.learning.db = self.db
            if self.learning.model is None:
                self.learning.model = self.model
            self._learning = self.learning

    def get_learning_machine(self) -> Optional[LearningMachine]:
        """Get the resolved LearningMachine instance.

        Returns:
            The LearningMachine instance if learning is enabled and initialized,
            None otherwise.
        """
        return self._learning

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

        if self.compression_manager is not None and self.compression_manager.model is None:
            self.compression_manager.model = self.model

        # Check compression flag on the compression manager
        if self.compression_manager is not None and self.compression_manager.compress_tool_results:
            self.compress_tool_results = True

    def _has_async_db(self) -> bool:
        """Return True if the db the agent is equipped with is an Async implementation"""
        return self.db is not None and isinstance(self.db, AsyncBaseDb)

    def _get_models(self) -> None:
        if self.model is not None:
            self.model = get_model(self.model)
        if self.reasoning_model is not None:
            self.reasoning_model = get_model(self.reasoning_model)
        if self.parser_model is not None:
            self.parser_model = get_model(self.parser_model)
        if self.output_model is not None:
            self.output_model = get_model(self.output_model)

        if self.compression_manager is not None and self.compression_manager.model is None:
            self.compression_manager.model = self.model

    def initialize_agent(self, debug_mode: Optional[bool] = None) -> None:
        self._set_default_model()
        self._set_debug(debug_mode=debug_mode)
        self.set_id()
        if self.update_memory_on_run or self.enable_agentic_memory or self.memory_manager is not None:
            self._set_memory_manager()
        if (
            self.add_culture_to_context
            or self.update_cultural_knowledge
            or self.enable_agentic_culture
            or self.culture_manager is not None
        ):
            self._set_culture_manager()
        if self.enable_session_summaries or self.session_summary_manager is not None:
            self._set_session_summary_manager()
        if self.compress_tool_results or self.compression_manager is not None:
            self._set_compression_manager()
        if self.learning is not None and self.learning is not False:
            self._set_learning_machine()

        log_debug(f"Agent ID: {self.id}", center=True)

        if self._formatter is None:
            self._formatter = SafeFormatter()

    def add_tool(self, tool: Union[Toolkit, Callable, Function, Dict]):
        if not self.tools:
            self.tools = []
        self.tools.append(tool)

    def set_tools(self, tools: Sequence[Union[Toolkit, Callable, Function, Dict]]):
        self.tools = list(tools) if tools else []

    async def _connect_mcp_tools(self) -> None:
        """Connect the MCP tools to the agent."""
        if self.tools:
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
                        self._mcp_tools_initialized_on_run.append(tool)  # type: ignore
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
