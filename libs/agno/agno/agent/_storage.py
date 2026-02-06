"""Session persistence, serialization, and post-run cleanup helpers for Agent."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Type,
    Union,
    cast,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.db.base import BaseDb, ComponentType, SessionType, UserMemory
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.utils import db_from_dict
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.registry.registry import Registry
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.session.summary import SessionSummary
from agno.tools.function import Function
from agno.utils.agent import (
    aget_last_run_output_util,
    aget_run_output_util,
    aget_session_metrics_util,
    aget_session_name_util,
    aget_session_state_util,
    aset_session_name_util,
    aupdate_session_state_util,
    get_last_run_output_util,
    get_run_output_util,
    get_session_metrics_util,
    get_session_name_util,
    get_session_state_util,
    scrub_history_messages_from_run_output,
    scrub_media_from_run_output,
    scrub_tool_results_from_run_output,
    set_session_name_util,
    update_session_state_util,
)
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.string import generate_id_from_name

# ---------------------------------------------------------------------------
# Session I/O
# ---------------------------------------------------------------------------


def read_session(
    agent: Agent, session_id: str, session_type: SessionType = SessionType.AGENT
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Get a Session from the database."""
    try:
        if not agent.db:
            raise ValueError("Db not initialized")
        return agent.db.get_session(session_id=session_id, session_type=session_type)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error getting session from db: {e}")
        return None


async def aread_session(
    agent: Agent, session_id: str, session_type: SessionType = SessionType.AGENT
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Get a Session from the database."""
    try:
        if not agent.db:
            raise ValueError("Db not initialized")
        return await agent.db.get_session(session_id=session_id, session_type=session_type)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error getting session from db: {e}")
        return None


def upsert_session(
    agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Upsert a Session into the database."""

    try:
        if not agent.db:
            raise ValueError("Db not initialized")
        return agent.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting session into db: {e}")
        return None


async def aupsert_session(
    agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Upsert a Session into the database."""
    try:
        if not agent.db:
            raise ValueError("Db not initialized")
        return await agent.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting session into db: {e}")
        return None


def load_session_state(agent: Agent, session: AgentSession, session_state: Dict[str, Any]):
    """Load and return the stored session_state from the database, optionally merging it with the given one"""

    # Get the session_state from the database and merge with proper precedence
    # At this point session_state contains: agent_defaults + run_params
    if session.session_data is not None and "session_state" in session.session_data:
        session_state_from_db = session.session_data.get("session_state")

        if (
            session_state_from_db is not None
            and isinstance(session_state_from_db, dict)
            and len(session_state_from_db) > 0
            and not agent.overwrite_db_session_state
        ):
            # This preserves precedence: run_params > db_state > agent_defaults
            merged_state = session_state_from_db.copy()
            merge_dictionaries(merged_state, session_state)
            session_state.clear()
            session_state.update(merged_state)

    # Update the session_state in the session
    if session.session_data is not None:
        session.session_data["session_state"] = session_state

    return session_state


def update_metadata(agent: Agent, session: AgentSession):
    """Update the extra_data in the session"""
    # Read metadata from the database
    if session.metadata is not None:
        # If metadata is set in the agent, update the database metadata with the agent's metadata
        if agent.metadata is not None:
            # Updates agent's session metadata in place
            merge_dictionaries(session.metadata, agent.metadata)
        # Update the current metadata with the metadata from the database which is updated in place
        agent.metadata = session.metadata


def get_session_metrics_internal(agent: Agent, session: AgentSession):
    # Get the session_metrics from the database
    if session.session_data is not None and "session_metrics" in session.session_data:
        session_metrics_from_db = session.session_data.get("session_metrics")
        if session_metrics_from_db is not None:
            if isinstance(session_metrics_from_db, dict):
                return Metrics(**session_metrics_from_db)
            elif isinstance(session_metrics_from_db, Metrics):
                return session_metrics_from_db
    else:
        return Metrics()


def read_or_create_session(
    agent: Agent,
    session_id: str,
    user_id: Optional[str] = None,
) -> AgentSession:
    from time import time
    from uuid import uuid4

    # Returning cached session if we have one
    if agent._cached_session is not None and agent._cached_session.session_id == session_id:
        return agent._cached_session

    # Try to load from database
    agent_session = None
    if agent.db is not None and agent.team_id is None and agent.workflow_id is None:
        log_debug(f"Reading AgentSession: {session_id}")

        agent_session = cast(AgentSession, read_session(agent, session_id=session_id))

    if agent_session is None:
        # Creating new session if none found
        log_debug(f"Creating new AgentSession: {session_id}")
        session_data = {}
        if agent.session_state is not None:
            from copy import deepcopy

            session_data["session_state"] = deepcopy(agent.session_state)
        agent_session = AgentSession(
            session_id=session_id,
            agent_id=agent.id,
            user_id=user_id,
            agent_data=agent._get_agent_data(),
            session_data=session_data,
            metadata=agent.metadata,
            created_at=int(time()),
        )
        if agent.introduction is not None:
            agent_session.upsert_run(
                RunOutput(
                    run_id=str(uuid4()),
                    session_id=session_id,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    user_id=user_id,
                    content=agent.introduction,
                    messages=[
                        Message(role=agent.model.assistant_message_role, content=agent.introduction)  # type: ignore
                    ],
                )
            )

    if agent.cache_session:
        agent._cached_session = agent_session

    return agent_session


async def aread_or_create_session(
    agent: Agent,
    session_id: str,
    user_id: Optional[str] = None,
) -> AgentSession:
    from time import time
    from uuid import uuid4

    from agno.agent import _init

    # Returning cached session if we have one
    if agent._cached_session is not None and agent._cached_session.session_id == session_id:
        return agent._cached_session

    # Try to load from database
    agent_session = None
    if agent.db is not None and agent.team_id is None and agent.workflow_id is None:
        log_debug(f"Reading AgentSession: {session_id}")
        if _init.has_async_db(agent):
            agent_session = cast(AgentSession, await aread_session(agent, session_id=session_id))
        else:
            agent_session = cast(AgentSession, read_session(agent, session_id=session_id))

    if agent_session is None:
        # Creating new session if none found
        log_debug(f"Creating new AgentSession: {session_id}")
        session_data = {}
        if agent.session_state is not None:
            from copy import deepcopy

            session_data["session_state"] = deepcopy(agent.session_state)
        agent_session = AgentSession(
            session_id=session_id,
            agent_id=agent.id,
            user_id=user_id,
            agent_data=agent._get_agent_data(),
            session_data=session_data,
            metadata=agent.metadata,
            created_at=int(time()),
        )
        if agent.introduction is not None:
            agent_session.upsert_run(
                RunOutput(
                    run_id=str(uuid4()),
                    session_id=session_id,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    user_id=user_id,
                    content=agent.introduction,
                    messages=[
                        Message(role=agent.model.assistant_message_role, content=agent.introduction)  # type: ignore
                    ],
                )
            )

    if agent.cache_session:
        agent._cached_session = agent_session

    return agent_session


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def to_dict(agent: Agent) -> Dict[str, Any]:
    """
    Convert the Agent to a dictionary.

    Returns:
        Dict[str, Any]: Dictionary representation of the agent configuration
    """
    config: Dict[str, Any] = {}

    # --- Agent Settings ---
    if agent.model is not None:
        if isinstance(agent.model, Model):
            config["model"] = agent.model.to_dict()
        else:
            config["model"] = str(agent.model)
    if agent.name is not None:
        config["name"] = agent.name
    if agent.id is not None:
        config["id"] = agent.id

    # --- User settings ---
    if agent.user_id is not None:
        config["user_id"] = agent.user_id

    # --- Session settings ---
    if agent.session_id is not None:
        config["session_id"] = agent.session_id
    if agent.session_state is not None:
        config["session_state"] = agent.session_state
    if agent.add_session_state_to_context:
        config["add_session_state_to_context"] = agent.add_session_state_to_context
    if agent.enable_agentic_state:
        config["enable_agentic_state"] = agent.enable_agentic_state
    if agent.overwrite_db_session_state:
        config["overwrite_db_session_state"] = agent.overwrite_db_session_state
    if agent.cache_session:
        config["cache_session"] = agent.cache_session
    if agent.search_session_history:
        config["search_session_history"] = agent.search_session_history
    if agent.num_history_sessions is not None:
        config["num_history_sessions"] = agent.num_history_sessions
    if agent.enable_session_summaries:
        config["enable_session_summaries"] = agent.enable_session_summaries
    if agent.add_session_summary_to_context is not None:
        config["add_session_summary_to_context"] = agent.add_session_summary_to_context
    # TODO: implement session summary manager serialization
    # if agent.session_summary_manager is not None:
    #     config["session_summary_manager"] = agent.session_summary_manager.to_dict()

    # --- Dependencies ---
    if agent.dependencies is not None:
        config["dependencies"] = agent.dependencies
    if agent.add_dependencies_to_context:
        config["add_dependencies_to_context"] = agent.add_dependencies_to_context

    # --- Agentic Memory settings ---
    # TODO: implement agentic memory serialization
    # if agent.memory_manager is not None:
    # config["memory_manager"] = agent.memory_manager.to_dict()
    if agent.enable_agentic_memory:
        config["enable_agentic_memory"] = agent.enable_agentic_memory
    if agent.enable_user_memories:
        config["enable_user_memories"] = agent.enable_user_memories
    if agent.add_memories_to_context is not None:
        config["add_memories_to_context"] = agent.add_memories_to_context

    # --- Database settings ---
    if agent.db is not None and hasattr(agent.db, "to_dict"):
        config["db"] = agent.db.to_dict()

    # --- History settings ---
    if agent.add_history_to_context:
        config["add_history_to_context"] = agent.add_history_to_context
    if agent.num_history_runs is not None:
        config["num_history_runs"] = agent.num_history_runs
    if agent.num_history_messages is not None:
        config["num_history_messages"] = agent.num_history_messages
    if agent.max_tool_calls_from_history is not None:
        config["max_tool_calls_from_history"] = agent.max_tool_calls_from_history

    # --- Knowledge settings ---
    # TODO: implement knowledge serialization
    # if agent.knowledge is not None:
    # config["knowledge"] = agent.knowledge.to_dict()
    if agent.knowledge_filters is not None:
        config["knowledge_filters"] = agent.knowledge_filters
    if agent.enable_agentic_knowledge_filters:
        config["enable_agentic_knowledge_filters"] = agent.enable_agentic_knowledge_filters
    if agent.add_knowledge_to_context:
        config["add_knowledge_to_context"] = agent.add_knowledge_to_context
    if not agent.search_knowledge:
        config["search_knowledge"] = agent.search_knowledge
    if agent.add_search_knowledge_instructions:
        config["add_search_knowledge_instructions"] = agent.add_search_knowledge_instructions
    # Skip knowledge_retriever as it's a callable
    if agent.references_format != "json":
        config["references_format"] = agent.references_format

    # --- Tools ---
    # Serialize tools to their dictionary representations
    _tools: List[Union[Function, dict]] = []
    if agent.model is not None:
        _tools = agent._parse_tools(
            model=agent.model,
            tools=agent.tools or [],
        )
    if _tools:
        serialized_tools = []
        for tool in _tools:
            try:
                if isinstance(tool, Function):
                    serialized_tools.append(tool.to_dict())
                else:
                    serialized_tools.append(tool)
            except Exception as e:
                # Skip tools that can't be serialized
                log_warning(f"Could not serialize tool {tool}: {e}")
        if serialized_tools:
            config["tools"] = serialized_tools

    if agent.tool_call_limit is not None:
        config["tool_call_limit"] = agent.tool_call_limit
    if agent.tool_choice is not None:
        config["tool_choice"] = agent.tool_choice

    # --- Reasoning settings ---
    if agent.reasoning:
        config["reasoning"] = agent.reasoning
    if agent.reasoning_model is not None:
        if isinstance(agent.reasoning_model, Model):
            config["reasoning_model"] = agent.reasoning_model.to_dict()
        else:
            config["reasoning_model"] = str(agent.reasoning_model)
    # Skip reasoning_agent to avoid circular serialization
    if agent.reasoning_min_steps != 1:
        config["reasoning_min_steps"] = agent.reasoning_min_steps
    if agent.reasoning_max_steps != 10:
        config["reasoning_max_steps"] = agent.reasoning_max_steps

    # --- Default tools settings ---
    if agent.read_chat_history:
        config["read_chat_history"] = agent.read_chat_history
    if agent.update_knowledge:
        config["update_knowledge"] = agent.update_knowledge
    if agent.read_tool_call_history:
        config["read_tool_call_history"] = agent.read_tool_call_history
    if not agent.send_media_to_model:
        config["send_media_to_model"] = agent.send_media_to_model
    if not agent.store_media:
        config["store_media"] = agent.store_media
    if not agent.store_tool_messages:
        config["store_tool_messages"] = agent.store_tool_messages
    if not agent.store_history_messages:
        config["store_history_messages"] = agent.store_history_messages

    # --- System message settings ---
    # Skip system_message if it's a callable or Message object
    # TODO: Support Message objects
    if agent.system_message is not None and isinstance(agent.system_message, str):
        config["system_message"] = agent.system_message
    if agent.system_message_role != "system":
        config["system_message_role"] = agent.system_message_role
    if not agent.build_context:
        config["build_context"] = agent.build_context

    # --- Context building settings ---
    if agent.description is not None:
        config["description"] = agent.description
    # Handle instructions (can be str, list, or callable)
    if agent.instructions is not None:
        if isinstance(agent.instructions, str):
            config["instructions"] = agent.instructions
        elif isinstance(agent.instructions, list):
            config["instructions"] = agent.instructions
        # Skip if callable
    if agent.expected_output is not None:
        config["expected_output"] = agent.expected_output
    if agent.additional_context is not None:
        config["additional_context"] = agent.additional_context
    if agent.markdown:
        config["markdown"] = agent.markdown
    if agent.add_name_to_context:
        config["add_name_to_context"] = agent.add_name_to_context
    if agent.add_datetime_to_context:
        config["add_datetime_to_context"] = agent.add_datetime_to_context
    if agent.add_location_to_context:
        config["add_location_to_context"] = agent.add_location_to_context
    if agent.timezone_identifier is not None:
        config["timezone_identifier"] = agent.timezone_identifier
    if not agent.resolve_in_context:
        config["resolve_in_context"] = agent.resolve_in_context

    # --- Additional input ---
    # Skip additional_input as it may contain complex Message objects
    # TODO: Support Message objects

    # --- User message settings ---
    if agent.user_message_role != "user":
        config["user_message_role"] = agent.user_message_role
    if not agent.build_user_context:
        config["build_user_context"] = agent.build_user_context

    # --- Response settings ---
    if agent.retries > 0:
        config["retries"] = agent.retries
    if agent.delay_between_retries != 1:
        config["delay_between_retries"] = agent.delay_between_retries
    if agent.exponential_backoff:
        config["exponential_backoff"] = agent.exponential_backoff

    # --- Schema settings ---
    if agent.input_schema is not None:
        if isinstance(agent.input_schema, type) and issubclass(agent.input_schema, BaseModel):
            config["input_schema"] = agent.input_schema.__name__
        elif isinstance(agent.input_schema, dict):
            config["input_schema"] = agent.input_schema
    if agent.output_schema is not None:
        if isinstance(agent.output_schema, type) and issubclass(agent.output_schema, BaseModel):
            config["output_schema"] = agent.output_schema.__name__
        elif isinstance(agent.output_schema, dict):
            config["output_schema"] = agent.output_schema

    # --- Parser and output settings ---
    if agent.parser_model is not None:
        if isinstance(agent.parser_model, Model):
            config["parser_model"] = agent.parser_model.to_dict()
        else:
            config["parser_model"] = str(agent.parser_model)
    if agent.parser_model_prompt is not None:
        config["parser_model_prompt"] = agent.parser_model_prompt
    if agent.output_model is not None:
        if isinstance(agent.output_model, Model):
            config["output_model"] = agent.output_model.to_dict()
        else:
            config["output_model"] = str(agent.output_model)
    if agent.output_model_prompt is not None:
        config["output_model_prompt"] = agent.output_model_prompt
    if not agent.parse_response:
        config["parse_response"] = agent.parse_response
    if agent.structured_outputs is not None:
        config["structured_outputs"] = agent.structured_outputs
    if agent.use_json_mode:
        config["use_json_mode"] = agent.use_json_mode
    if agent.save_response_to_file is not None:
        config["save_response_to_file"] = agent.save_response_to_file

    # --- Streaming settings ---
    if agent.stream is not None:
        config["stream"] = agent.stream
    if agent.stream_events is not None:
        config["stream_events"] = agent.stream_events
    if agent.store_events:
        config["store_events"] = agent.store_events
    # Skip events_to_skip as it contains RunEvent enums

    # --- Role and culture settings ---
    if agent.role is not None:
        config["role"] = agent.role
    # --- Team and workflow settings ---
    if agent.team_id is not None:
        config["team_id"] = agent.team_id
    if agent.workflow_id is not None:
        config["workflow_id"] = agent.workflow_id

    # --- Metadata ---
    if agent.metadata is not None:
        config["metadata"] = agent.metadata

    # --- Context compression settings ---
    if agent.compress_tool_results:
        config["compress_tool_results"] = agent.compress_tool_results
    # TODO: implement compression manager serialization
    # if agent.compression_manager is not None:
    #     config["compression_manager"] = agent.compression_manager.to_dict()

    # --- Debug and telemetry settings ---
    if agent.debug_mode:
        config["debug_mode"] = agent.debug_mode
    if agent.debug_level != 1:
        config["debug_level"] = agent.debug_level
    if not agent.telemetry:
        config["telemetry"] = agent.telemetry

    return config


def from_dict(cls: Type[Agent], data: Dict[str, Any], registry: Optional[Registry] = None) -> Agent:
    """
    Create an agent from a dictionary.

    Args:
        cls: The Agent class (or subclass) to instantiate.
        data: Dictionary containing agent configuration
        registry: Optional registry for rehydrating tools and schemas

    Returns:
        Agent: Reconstructed agent instance
    """
    from agno.models.utils import get_model

    config = data.copy()

    # --- Handle Model reconstruction ---
    if "model" in config:
        model_data = config["model"]
        if isinstance(model_data, dict) and "id" in model_data:
            config["model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
        elif isinstance(model_data, str):
            config["model"] = get_model(model_data)

    # --- Handle reasoning_model reconstruction ---
    # TODO: implement reasoning model deserialization
    # if "reasoning_model" in config:
    #     model_data = config["reasoning_model"]
    #     if isinstance(model_data, dict) and "id" in model_data:
    #         config["reasoning_model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
    #     elif isinstance(model_data, str):
    #         config["reasoning_model"] = get_model(model_data)

    # --- Handle parser_model reconstruction ---
    # TODO: implement parser model deserialization
    # if "parser_model" in config:
    #     model_data = config["parser_model"]
    #     if isinstance(model_data, dict) and "id" in model_data:
    #         config["parser_model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
    #     elif isinstance(model_data, str):
    #         config["parser_model"] = get_model(model_data)

    # --- Handle output_model reconstruction ---
    # TODO: implement output model deserialization
    # if "output_model" in config:
    #     model_data = config["output_model"]
    #     if isinstance(model_data, dict) and "id" in model_data:
    #         config["output_model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
    #     elif isinstance(model_data, str):
    #         config["output_model"] = get_model(model_data)

    # --- Handle tools reconstruction ---
    if "tools" in config and config["tools"]:
        if registry:
            config["tools"] = [registry.rehydrate_function(t) for t in config["tools"]]
        else:
            log_warning("No registry provided, tools will not be rehydrated.")
            del config["tools"]

    # --- Handle DB reconstruction ---
    if "db" in config and isinstance(config["db"], dict):
        db_data = config["db"]
        db_id = db_data.get("id")

        # First try to get the db from the registry (preferred - reuses existing connection)
        if registry and db_id:
            registry_db = registry.get_db(db_id)
            if registry_db is not None:
                config["db"] = registry_db
            else:
                del config["db"]
        else:
            # No registry or no db_id, fall back to creating from dict
            config["db"] = db_from_dict(db_data)
            if config["db"] is None:
                del config["db"]

    # --- Handle Schema reconstruction ---
    if "input_schema" in config and isinstance(config["input_schema"], str):
        schema_cls = registry.get_schema(config["input_schema"]) if registry else None
        if schema_cls:
            config["input_schema"] = schema_cls
        else:
            log_warning(f"Input schema {config['input_schema']} not found in registry, skipping.")
            del config["input_schema"]

    if "output_schema" in config and isinstance(config["output_schema"], str):
        schema_cls = registry.get_schema(config["output_schema"]) if registry else None
        if schema_cls:
            config["output_schema"] = schema_cls
        else:
            log_warning(f"Output schema {config['output_schema']} not found in registry, skipping.")
            del config["output_schema"]

    # --- Handle MemoryManager reconstruction ---
    # TODO: implement memory manager deserialization
    # if "memory_manager" in config and isinstance(config["memory_manager"], dict):
    #     from agno.memory import MemoryManager
    #     config["memory_manager"] = MemoryManager.from_dict(config["memory_manager"])

    # --- Handle SessionSummaryManager reconstruction ---
    # TODO: implement session summary manager deserialization
    # if "session_summary_manager" in config and isinstance(config["session_summary_manager"], dict):
    #     from agno.session import SessionSummaryManager
    #     config["session_summary_manager"] = SessionSummaryManager.from_dict(config["session_summary_manager"])

    # --- Handle CultureManager reconstruction ---
    # TODO: implement culture manager deserialization
    # if "culture_manager" in config and isinstance(config["culture_manager"], dict):
    #     from agno.culture import CultureManager
    #     config["culture_manager"] = CultureManager.from_dict(config["culture_manager"])

    # --- Handle Knowledge reconstruction ---
    # TODO: implement knowledge deserialization
    # if "knowledge" in config and isinstance(config["knowledge"], dict):
    #     from agno.knowledge import Knowledge
    #     config["knowledge"] = Knowledge.from_dict(config["knowledge"])

    # --- Handle CompressionManager reconstruction ---
    # TODO: implement compression manager deserialization
    # if "compression_manager" in config and isinstance(config["compression_manager"], dict):
    #     from agno.compression.manager import CompressionManager
    #     config["compression_manager"] = CompressionManager.from_dict(config["compression_manager"])

    # Remove keys that aren't constructor parameters
    config.pop("team_id", None)
    config.pop("workflow_id", None)

    return cls(
        # --- Agent settings ---
        model=config.get("model"),
        name=config.get("name"),
        id=config.get("id"),
        # --- User settings ---
        user_id=config.get("user_id"),
        # --- Session settings ---
        session_id=config.get("session_id"),
        session_state=config.get("session_state"),
        add_session_state_to_context=config.get("add_session_state_to_context", False),
        enable_agentic_state=config.get("enable_agentic_state", False),
        overwrite_db_session_state=config.get("overwrite_db_session_state", False),
        cache_session=config.get("cache_session", False),
        search_session_history=config.get("search_session_history", False),
        num_history_sessions=config.get("num_history_sessions"),
        enable_session_summaries=config.get("enable_session_summaries", False),
        add_session_summary_to_context=config.get("add_session_summary_to_context"),
        # session_summary_manager=config.get("session_summary_manager"),  # TODO
        # --- Dependencies ---
        dependencies=config.get("dependencies"),
        add_dependencies_to_context=config.get("add_dependencies_to_context", False),
        # --- Agentic Memory settings ---
        # memory_manager=config.get("memory_manager"),  # TODO
        enable_agentic_memory=config.get("enable_agentic_memory", False),
        enable_user_memories=config.get("enable_user_memories", False),
        add_memories_to_context=config.get("add_memories_to_context"),
        # --- Database settings ---
        db=config.get("db"),
        # --- History settings ---
        add_history_to_context=config.get("add_history_to_context", False),
        num_history_runs=config.get("num_history_runs"),
        num_history_messages=config.get("num_history_messages"),
        max_tool_calls_from_history=config.get("max_tool_calls_from_history"),
        # --- Knowledge settings ---
        # knowledge=config.get("knowledge"),  # TODO
        knowledge_filters=config.get("knowledge_filters"),
        enable_agentic_knowledge_filters=config.get("enable_agentic_knowledge_filters", False),
        add_knowledge_to_context=config.get("add_knowledge_to_context", False),
        references_format=config.get("references_format", "json"),
        # --- Tools ---
        tools=config.get("tools"),
        tool_call_limit=config.get("tool_call_limit"),
        tool_choice=config.get("tool_choice"),
        # --- Reasoning settings ---
        reasoning=config.get("reasoning", False),
        # reasoning_model=config.get("reasoning_model"),  # TODO
        reasoning_min_steps=config.get("reasoning_min_steps", 1),
        reasoning_max_steps=config.get("reasoning_max_steps", 10),
        # --- Default tools settings ---
        read_chat_history=config.get("read_chat_history", False),
        search_knowledge=config.get("search_knowledge", True),
        add_search_knowledge_instructions=config.get("add_search_knowledge_instructions", True),
        update_knowledge=config.get("update_knowledge", False),
        read_tool_call_history=config.get("read_tool_call_history", False),
        send_media_to_model=config.get("send_media_to_model", True),
        store_media=config.get("store_media", True),
        store_tool_messages=config.get("store_tool_messages", True),
        store_history_messages=config.get("store_history_messages", False),
        # --- System message settings ---
        system_message=config.get("system_message"),
        system_message_role=config.get("system_message_role", "system"),
        build_context=config.get("build_context", True),
        # --- Context building settings ---
        description=config.get("description"),
        instructions=config.get("instructions"),
        expected_output=config.get("expected_output"),
        additional_context=config.get("additional_context"),
        markdown=config.get("markdown", False),
        add_name_to_context=config.get("add_name_to_context", False),
        add_datetime_to_context=config.get("add_datetime_to_context", False),
        add_location_to_context=config.get("add_location_to_context", False),
        timezone_identifier=config.get("timezone_identifier"),
        resolve_in_context=config.get("resolve_in_context", True),
        # --- User message settings ---
        user_message_role=config.get("user_message_role", "user"),
        build_user_context=config.get("build_user_context", True),
        # --- Response settings ---
        retries=config.get("retries", 0),
        delay_between_retries=config.get("delay_between_retries", 1),
        exponential_backoff=config.get("exponential_backoff", False),
        # --- Schema settings ---
        input_schema=config.get("input_schema"),
        output_schema=config.get("output_schema"),
        # --- Parser and output settings ---
        # parser_model=config.get("parser_model"),  # TODO
        parser_model_prompt=config.get("parser_model_prompt"),
        # output_model=config.get("output_model"),  # TODO
        output_model_prompt=config.get("output_model_prompt"),
        parse_response=config.get("parse_response", True),
        structured_outputs=config.get("structured_outputs"),
        use_json_mode=config.get("use_json_mode", False),
        save_response_to_file=config.get("save_response_to_file"),
        # --- Streaming settings ---
        stream=config.get("stream"),
        stream_events=config.get("stream_events"),
        store_events=config.get("store_events", False),
        role=config.get("role"),
        # --- Culture settings ---
        # culture_manager=config.get("culture_manager"),  # TODO
        # --- Metadata ---
        metadata=config.get("metadata"),
        # --- Compression settings ---
        compress_tool_results=config.get("compress_tool_results", False),
        # compression_manager=config.get("compression_manager"),  # TODO
        # --- Debug and telemetry settings ---
        debug_mode=config.get("debug_mode", False),
        debug_level=config.get("debug_level", 1),
        telemetry=config.get("telemetry", True),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save(
    agent: Agent,
    *,
    db: Optional[BaseDb] = None,
    stage: str = "published",
    label: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[int]:
    """
    Save the agent component and config.

    Args:
        agent: The Agent instance.
        db: The database to save the component and config to.
        stage: The stage of the component. Defaults to "published".
        label: The label of the component.
        notes: The notes of the component.

    Returns:
        Optional[int]: The version number of the saved config.
    """
    db_ = db or agent.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for save(). Use a sync database.")

    if agent.id is None:
        agent.id = generate_id_from_name(agent.name)

    try:
        # Create or update component
        db_.upsert_component(
            component_id=agent.id,
            component_type=ComponentType.AGENT,
            name=getattr(agent, "name", agent.id),
            description=getattr(agent, "description", None),
            metadata=getattr(agent, "metadata", None),
        )

        # Create or update config
        config = db_.upsert_config(
            component_id=agent.id,
            config=to_dict(agent),
            label=label,
            stage=stage,
            notes=notes,
        )

        return config.get("version")

    except Exception as e:
        log_error(f"Error saving Agent to database: {e}")
        raise


def load(
    cls: Type[Agent],
    id: str,
    *,
    db: BaseDb,
    registry: Optional[Registry] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional[Agent]:
    """
    Load an agent by id.

    Args:
        cls: The Agent class (or subclass) to instantiate.
        id: The id of the agent to load.
        db: The database to load the agent from.
        registry: Optional registry for rehydrating tools and schemas.
        label: The label of the agent to load.
        version: The version of the agent to load.

    Returns:
        The agent loaded from the database or None if not found.
    """

    data = db.get_config(component_id=id, label=label, version=version)
    if data is None:
        return None

    config = data.get("config")
    if config is None:
        return None

    agent = from_dict(cls, config, registry=registry)
    agent.id = id
    agent.db = db

    return agent


def delete(
    agent: Agent,
    *,
    db: Optional[BaseDb] = None,
    hard_delete: bool = False,
) -> bool:
    """
    Delete the agent component.

    Args:
        agent: The Agent instance.
        db: The database to delete the component from.
        hard_delete: Whether to hard delete the component.

    Returns:
        True if the component was deleted, False otherwise.
    """
    db_ = db or agent.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for delete(). Use a sync database.")
    if agent.id is None:
        raise ValueError("Cannot delete agent without an id")

    return db_.delete_component(component_id=agent.id, hard_delete=hard_delete)


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_run_output(agent: Agent, run_id: str, session_id: Optional[str] = None) -> Optional[RunOutput]:
    """
    Get a RunOutput from the database.

    Args:
        agent: The Agent instance.
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
    Returns:
        Optional[RunOutput]: The RunOutput from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, get_run_output_util(agent, run_id=run_id, session_id=session_id_to_load))


async def aget_run_output(agent: Agent, run_id: str, session_id: Optional[str] = None) -> Optional[RunOutput]:
    """
    Get a RunOutput from the database.

    Args:
        agent: The Agent instance.
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
    Returns:
        Optional[RunOutput]: The RunOutput from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, await aget_run_output_util(agent, run_id=run_id, session_id=session_id_to_load))


def get_last_run_output(agent: Agent, session_id: Optional[str] = None) -> Optional[RunOutput]:
    """
    Get the last run response from the database.

    Args:
        agent: The Agent instance.
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        Optional[RunOutput]: The last run response from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, get_last_run_output_util(agent, session_id=session_id_to_load))


async def aget_last_run_output(agent: Agent, session_id: Optional[str] = None) -> Optional[RunOutput]:
    """
    Get the last run response from the database.

    Args:
        agent: The Agent instance.
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        Optional[RunOutput]: The last run response from the database or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id
    return cast(RunOutput, await aget_last_run_output_util(agent, session_id=session_id_to_load))


def get_session(
    agent: Agent,
    session_id: Optional[str] = None,
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Load an AgentSession from database or cache.

    Args:
        agent: The Agent instance.
        session_id: The session_id to load from storage.

    Returns:
        AgentSession: The AgentSession loaded from the database/cache or None if not found.
    """
    from agno.agent import _init

    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id

    # If there is a cached session, return it
    if agent.cache_session and hasattr(agent, "_cached_session") and agent._cached_session is not None:
        if agent._cached_session.session_id == session_id_to_load:
            return agent._cached_session

    if _init.has_async_db(agent):
        raise ValueError("Async database not supported for get_session")

    # Load and return the session from the database
    if agent.db is not None:
        loaded_session = None

        # We have a standalone agent, so we are loading an AgentSession
        if agent.team_id is None and agent.workflow_id is None:
            loaded_session = cast(
                AgentSession,
                read_session(agent, session_id=session_id_to_load, session_type=SessionType.AGENT),  # type: ignore
            )

        # We have a team member agent, so we are loading a TeamSession
        if loaded_session is None and agent.team_id is not None:
            # Load session for team member agents
            loaded_session = cast(
                TeamSession,
                read_session(agent, session_id=session_id_to_load, session_type=SessionType.TEAM),  # type: ignore
            )

        # We have a workflow member agent, so we are loading a WorkflowSession
        if loaded_session is None and agent.workflow_id is not None:
            # Load session for workflow memberagents
            loaded_session = cast(
                WorkflowSession,
                read_session(agent, session_id=session_id_to_load, session_type=SessionType.WORKFLOW),  # type: ignore
            )

        # Cache the session if relevant
        if loaded_session is not None and agent.cache_session:
            agent._cached_session = loaded_session  # type: ignore

        return loaded_session

    log_debug(f"Session {session_id_to_load} not found in db")
    return None


async def aget_session(
    agent: Agent,
    session_id: Optional[str] = None,
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Load an AgentSession from database or cache.

    Args:
        agent: The Agent instance.
        session_id: The session_id to load from storage.

    Returns:
        AgentSession: The AgentSession loaded from the database/cache or None if not found.
    """
    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or agent.session_id

    # If there is a cached session, return it
    if agent.cache_session and hasattr(agent, "_cached_session") and agent._cached_session is not None:
        if agent._cached_session.session_id == session_id_to_load:
            return agent._cached_session

    # Load and return the session from the database
    if agent.db is not None:
        loaded_session = None

        # We have a standalone agent, so we are loading an AgentSession
        if agent.team_id is None and agent.workflow_id is None:
            loaded_session = cast(
                AgentSession,
                await aread_session(agent, session_id=session_id_to_load, session_type=SessionType.AGENT),  # type: ignore
            )

        # We have a team member agent, so we are loading a TeamSession
        if loaded_session is None and agent.team_id is not None:
            # Load session for team member agents
            loaded_session = cast(
                TeamSession,
                await aread_session(agent, session_id=session_id_to_load, session_type=SessionType.TEAM),  # type: ignore
            )

        # We have a workflow member agent, so we are loading a WorkflowSession
        if loaded_session is None and agent.workflow_id is not None:
            # Load session for workflow memberagents
            loaded_session = cast(
                WorkflowSession,
                await aread_session(agent, session_id=session_id_to_load, session_type=SessionType.WORKFLOW),  # type: ignore
            )

        # Cache the session if relevant
        if loaded_session is not None and agent.cache_session:
            agent._cached_session = loaded_session  # type: ignore

        return loaded_session

    log_debug(f"AgentSession {session_id_to_load} not found in db")
    return None


def save_session(agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]) -> None:
    """
    Save the AgentSession to storage
    """
    from agno.agent import _init

    if _init.has_async_db(agent):
        raise ValueError("Async database not supported for save_session")
    # If the agent is a member of a team, do not save the session to the database
    if (
        agent.db is not None
        and agent.team_id is None
        and agent.workflow_id is None
        and session.session_data is not None
    ):
        if session.session_data is not None and "session_state" in session.session_data:
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)

        upsert_session(agent, session=session)
        log_debug(f"Created or updated AgentSession record: {session.session_id}")


async def asave_session(agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]) -> None:
    """
    Save the AgentSession to storage
    """
    from agno.agent import _init

    # If the agent is a member of a team, do not save the session to the database
    if (
        agent.db is not None
        and agent.team_id is None
        and agent.workflow_id is None
        and session.session_data is not None
    ):
        if session.session_data is not None and "session_state" in session.session_data:
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)
        if _init.has_async_db(agent):
            await aupsert_session(agent, session=session)
        else:
            upsert_session(agent, session=session)
        log_debug(f"Created or updated AgentSession record: {session.session_id}")


# -*- Session Management Functions


def rename(agent: Agent, name: str, session_id: Optional[str] = None) -> None:
    """
    Rename the Agent and save to storage

    Args:
        agent: The Agent instance.
        name (str): The new name for the Agent.
        session_id (Optional[str]): The session_id of the session where to store the new name. If not provided, the current cached session ID is used.
    """
    from agno.agent import _init

    session_id = session_id or agent.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    if _init.has_async_db(agent):
        import asyncio

        session = asyncio.run(aget_session(agent, session_id=session_id))
    else:
        session = get_session(agent, session_id=session_id)

    if session is None:
        raise Exception("Session not found")

    if not hasattr(session, "agent_data"):
        raise Exception("Session is not an AgentSession")

    # -*- Rename Agent
    agent.name = name

    if session.agent_data is not None:  # type: ignore
        session.agent_data["name"] = name  # type: ignore
    else:
        session.agent_data = {"name": name}  # type: ignore

    # -*- Save to storage
    if _init.has_async_db(agent):
        import asyncio

        asyncio.run(asave_session(agent, session=session))
    else:
        save_session(agent, session=session)


def set_session_name(
    agent: Agent,
    session_id: Optional[str] = None,
    autogenerate: bool = False,
    session_name: Optional[str] = None,
) -> AgentSession:
    """
    Set the session name and save to storage

    Args:
        agent: The Agent instance.
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        AgentSession: The updated session.
    """
    session_id = session_id or agent.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        AgentSession,
        set_session_name_util(agent, session_id=session_id, autogenerate=autogenerate, session_name=session_name),
    )


async def aset_session_name(
    agent: Agent,
    session_id: Optional[str] = None,
    autogenerate: bool = False,
    session_name: Optional[str] = None,
) -> AgentSession:
    """
    Set the session name and save to storage

    Args:
        agent: The Agent instance.
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        AgentSession: The updated session.
    """
    session_id = session_id or agent.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        AgentSession,
        await aset_session_name_util(
            agent, session_id=session_id, autogenerate=autogenerate, session_name=session_name
        ),
    )


def generate_session_name(agent: Agent, session: AgentSession, max_retries: int = 3, _attempt: int = 0) -> str:
    """
    Generate a name for the session using the first 6 messages from the memory

    Args:
        agent: The Agent instance.
        session (AgentSession): The session to generate a name for.
        max_retries: Maximum number of retries if generation fails.
        _attempt: Current attempt number (used internally for recursion).
    Returns:
        str: The generated session name.
    """

    if agent.model is None:
        raise Exception("Model not set")

    gen_session_name_prompt = "Conversation\n"

    messages_for_generating_session_name = session.get_messages()

    for message in messages_for_generating_session_name:
        gen_session_name_prompt += f"{message.role.upper()}: {message.content}\n"

    gen_session_name_prompt += "\n\nConversation Name: "

    system_message = Message(
        role=agent.system_message_role,
        content="Please provide a suitable name for this conversation in maximum 5 words. "
        "Remember, do not exceed 5 words.",
    )
    user_message = Message(role=agent.user_message_role, content=gen_session_name_prompt)
    generate_name_messages = [system_message, user_message]

    # Generate name
    generated_name = agent.model.response(messages=generate_name_messages)
    content = generated_name.content
    if content is None:
        if _attempt >= max_retries:
            return "New Session"
        log_error("Generated name is None. Trying again.")
        return generate_session_name(agent, session=session, max_retries=max_retries, _attempt=_attempt + 1)

    if len(content.split()) > 5:
        if _attempt >= max_retries:
            return " ".join(content.split()[:5])
        log_error("Generated name is too long. It should be less than 5 words. Trying again.")
        return generate_session_name(agent, session=session, max_retries=max_retries, _attempt=_attempt + 1)
    return content.replace('"', "").strip()


def get_session_name(agent: Agent, session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_name_util(agent, session_id=session_id)


async def aget_session_name(agent: Agent, session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_name_util(agent, session_id=session_id)


def get_session_state(agent: Agent, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the session state for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_state_util(agent, session_id=session_id)


async def aget_session_state(agent: Agent, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the session state for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_state_util(agent, session_id=session_id)


def update_session_state(agent: Agent, session_state_updates: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        agent: The Agent instance.
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return update_session_state_util(agent, session_state_updates=session_state_updates, session_id=session_id)


async def aupdate_session_state(
    agent: Agent, session_state_updates: Dict[str, Any], session_id: Optional[str] = None
) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        agent: The Agent instance.
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aupdate_session_state_util(agent, session_state_updates=session_state_updates, session_id=session_id)


def get_session_metrics(agent: Agent, session_id: Optional[str] = None) -> Optional[Metrics]:
    """Get the session metrics for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[Metrics]: The session metrics.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return get_session_metrics_util(agent, session_id=session_id)


async def aget_session_metrics(agent: Agent, session_id: Optional[str] = None) -> Optional[Metrics]:
    """Get the session metrics for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[Metrics]: The session metrics.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return await aget_session_metrics_util(agent, session_id=session_id)


def delete_session(agent: Agent, session_id: str):
    """Delete the current session and save to storage"""
    if agent.db is None:
        return

    agent.db.delete_session(session_id=session_id)


async def adelete_session(agent: Agent, session_id: str):
    """Delete the current session and save to storage"""
    if agent.db is None:
        return
    await agent.db.delete_session(session_id=session_id)  # type: ignore


def get_session_messages(
    agent: Agent,
    session_id: Optional[str] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the messages for. If not provided, the latest used session ID is used.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = get_session(agent, session_id=session_id)
    if session is None:
        raise Exception("Session not found")

    # Handle the case in which the agent is reusing a team session
    if isinstance(session, TeamSession):
        return session.get_messages(
            member_ids=[agent.id] if agent.team_id and agent.id else None,
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=skip_roles,
            skip_statuses=skip_statuses,
            skip_history_messages=skip_history_messages,
        )

    return session.get_messages(
        # Only filter by agent_id if this is part of a team
        agent_id=agent.id if agent.team_id is not None else None,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
    )


async def aget_session_messages(
    agent: Agent,
    session_id: Optional[str] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the messages for. If not provided, the current cached session ID is used.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = await aget_session(agent, session_id=session_id)
    if session is None:
        raise Exception("Session not found")

    # Handle the case in which the agent is reusing a team session
    if isinstance(session, TeamSession):
        return session.get_messages(
            member_ids=[agent.id] if agent.team_id and agent.id else None,
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=skip_roles,
            skip_statuses=skip_statuses,
            skip_history_messages=skip_history_messages,
        )

    # Only filter by agent_id if this is part of a team
    return session.get_messages(
        agent_id=agent.id if agent.team_id is not None else None,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
    )


def get_chat_history(
    agent: Agent, session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Return the chat history (user and assistant messages) for the session.
    Use get_messages() for more filtering options.

    Returns:
        A list of user and assistant Messages belonging to the session.
    """
    return get_session_messages(agent, session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"])


async def aget_chat_history(
    agent: Agent, session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Return the chat history (user and assistant messages) for the session.
    Use get_messages() for more filtering options.

    Returns:
        A list of user and assistant Messages belonging to the session.
    """
    return await aget_session_messages(
        agent, session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"]
    )


def get_session_summary(agent: Agent, session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.

    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else agent.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = get_session(agent, session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore


async def aget_session_summary(agent: Agent, session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.
    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else agent.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = await aget_session(agent, session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore


def get_user_memories(agent: Agent, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        agent: The Agent instance.
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    if agent.memory_manager is None:
        agent._set_memory_manager()

    user_id = user_id if user_id is not None else agent.user_id
    if user_id is None:
        user_id = "default"

    return agent.memory_manager.get_user_memories(user_id=user_id)  # type: ignore


async def aget_user_memories(agent: Agent, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        agent: The Agent instance.
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    if agent.memory_manager is None:
        agent._set_memory_manager()

    user_id = user_id if user_id is not None else agent.user_id
    if user_id is None:
        user_id = "default"

    return await agent.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore


def get_culture_knowledge(agent: Agent) -> Optional[List[CulturalKnowledge]]:
    """Get the cultural knowledge the agent has access to

    Args:
        agent: The Agent instance.

    Returns:
        Optional[List[CulturalKnowledge]]: The cultural knowledge.
    """
    if agent.culture_manager is None:
        return None

    return agent.culture_manager.get_all_knowledge()


async def aget_culture_knowledge(agent: Agent) -> Optional[List[CulturalKnowledge]]:
    """Get the cultural knowledge the agent has access to

    Args:
        agent: The Agent instance.

    Returns:
        Optional[List[CulturalKnowledge]]: The cultural knowledge.
    """
    if agent.culture_manager is None:
        return None

    return await agent.culture_manager.aget_all_knowledge()


# ---------------------------------------------------------------------------
# Post-run cleanup
# ---------------------------------------------------------------------------


def scrub_run_output_for_storage(agent: Agent, run_response: RunOutput) -> None:
    """Scrub run output based on storage flags before persisting to database."""
    if not agent.store_media:
        scrub_media_from_run_output(run_response)

    if not agent.store_tool_messages:
        scrub_tool_results_from_run_output(run_response)

    if not agent.store_history_messages:
        scrub_history_messages_from_run_output(run_response)


def cleanup_and_store(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    from agno.agent import _hooks, _response

    # Scrub the stored run based on storage flags
    scrub_run_output_for_storage(agent, run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Update run_response.session_state before saving
    # This ensures RunOutput reflects all tool modifications
    if session.session_data is not None and run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state

    # Optional: Save output to file if save_response_to_file is set
    _response.save_run_response_to_file(
        agent,
        run_response=run_response,
        input=run_response.input.input_content_string() if run_response.input else "",
        session_id=session.session_id,
        user_id=user_id,
    )

    # Add RunOutput to Agent Session
    session.upsert_run(run=run_response)

    # Calculate session metrics
    _hooks.update_session_metrics(agent, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    save_session(agent, session=session)


async def acleanup_and_store(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    from agno.agent import _hooks, _response

    # Scrub the stored run based on storage flags
    scrub_run_output_for_storage(agent, run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Update run_response.session_state from session before saving
    # This ensures RunOutput reflects all tool modifications
    if session.session_data is not None and run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state

    # Optional: Save output to file if save_response_to_file is set
    _response.save_run_response_to_file(
        agent,
        run_response=run_response,
        input=run_response.input.input_content_string() if run_response.input else "",
        session_id=session.session_id,
        user_id=user_id,
    )

    # Add RunOutput to Agent Session
    session.upsert_run(run=run_response)

    # Calculate session metrics
    _hooks.update_session_metrics(agent, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    await asave_session(agent, session=session)
