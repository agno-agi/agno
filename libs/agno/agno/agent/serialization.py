"""Serialization and persistence functions for the Agent class.

Functions in this module handle converting agents to/from dictionaries,
saving/loading from databases, and deep copying. Each takes an Agent instance
as its first parameter (except from_dict and load which create new instances).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.db.base import BaseDb, ComponentType
from agno.models.base import Model
from agno.models.message import Message
from agno.registry.registry import Registry
from agno.run.agent import RunOutput
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import generate_id_from_name

if TYPE_CHECKING:
    from agno.agent.agent import Agent


def to_dict(agent: Agent) -> Dict[str, Any]:
    """
    Convert the Agent to a dictionary.

    Returns:
        Dict[str, Any]: Dictionary representation of the agent configuration
    """
    from agno.tools.function import Function

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
                from agno.utils.log import log_warning

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


def from_dict(data: Dict[str, Any], registry: Optional[Registry] = None) -> Agent:
    """
    Create an agent from a dictionary.

    Args:
        data: Dictionary containing agent configuration
        registry: Optional registry for rehydrating tools and schemas

    Returns:
        Agent: Reconstructed agent instance
    """
    from agno.agent.agent import Agent
    from agno.db.utils import db_from_dict
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

    return Agent(
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
        store_history_messages=config.get("store_history_messages", True),
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


# -*- Component and Config Functions
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
        agent: The agent to save.
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

    agent = from_dict(config, registry=registry)
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
        agent: The agent to delete.
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


def deep_copy(agent: Agent, *, update: Optional[Dict[str, Any]] = None) -> Agent:
    """Create and return a deep copy of this Agent, optionally updating fields.

    Args:
        agent: The agent to deep copy.
        update (Optional[Dict[str, Any]]): Optional dictionary of fields for the new Agent.

    Returns:
        Agent: A new Agent instance.
    """
    from dataclasses import fields

    # Extract the fields to set for the new Agent
    fields_for_new_agent: Dict[str, Any] = {}

    for f in fields(agent):
        # Skip private fields (not part of __init__ signature)
        if f.name.startswith("_"):
            continue

        field_value = getattr(agent, f.name)
        if field_value is not None:
            try:
                fields_for_new_agent[f.name] = _deep_copy_field(agent, f.name, field_value)
            except Exception as e:
                log_warning(f"Failed to deep copy field '{f.name}': {e}. Using original value.")
                fields_for_new_agent[f.name] = field_value

    # Update fields if provided
    if update:
        fields_for_new_agent.update(update)

    # Create a new Agent
    try:
        new_agent = agent.__class__(**fields_for_new_agent)
        log_debug(f"Created new {agent.__class__.__name__}")
        return new_agent
    except Exception as e:
        log_error(f"Failed to create deep copy of {agent.__class__.__name__}: {e}")
        raise


def _deep_copy_field(agent: Agent, field_name: str, field_value: Any) -> Any:
    """Helper function to deep copy a field based on its type."""
    from copy import copy, deepcopy

    # For memory and reasoning_agent, use their deep_copy methods
    if field_name == "reasoning_agent":
        return field_value.deep_copy()

    # For tools, share MCP tools but copy others
    if field_name == "tools" and field_value is not None:
        try:
            copied_tools = []
            for tool in field_value:
                try:
                    # Share MCP tools (they maintain server connections)
                    is_mcp_tool = hasattr(type(tool), "__mro__") and any(
                        c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                    )
                    if is_mcp_tool:
                        copied_tools.append(tool)
                    else:
                        try:
                            copied_tools.append(deepcopy(tool))
                        except Exception:
                            # Tool can't be deep copied, share by reference
                            copied_tools.append(tool)
                except Exception:
                    # MCP detection failed, share tool by reference to be safe
                    copied_tools.append(tool)
            return copied_tools
        except Exception as e:
            # If entire tools processing fails, log and return original list
            log_warning(f"Failed to process tools for deep copy: {e}")
            return field_value

    # Share heavy resources - these maintain connections/pools that shouldn't be duplicated
    if field_name in (
        "db",
        "model",
        "reasoning_model",
        "knowledge",
        "memory_manager",
        "parser_model",
        "output_model",
        "session_summary_manager",
        "culture_manager",
        "compression_manager",
        "learning",
        "skills",
    ):
        return field_value

    # For compound types, attempt a deep copy
    if isinstance(field_value, (list, dict, set)):
        try:
            return deepcopy(field_value)
        except Exception:
            try:
                return copy(field_value)
            except Exception as e:
                log_warning(f"Failed to copy field: {field_name} - {e}")
                return field_value

    # For pydantic models, attempt a model_copy
    if isinstance(field_value, BaseModel):
        try:
            return field_value.model_copy(deep=True)
        except Exception:
            try:
                return field_value.model_copy(deep=False)
            except Exception as e:
                log_warning(f"Failed to copy field: {field_name} - {e}")
                return field_value

    # For other types, attempt a shallow copy first
    try:
        return copy(field_value)
    except Exception:
        # If copy fails, return as is
        return field_value


def save_run_response_to_file(
    agent: Agent,
    run_response: RunOutput,
    input: Optional[Union[str, List, Dict, Message, List[Message]]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    if agent.save_response_to_file is not None and run_response is not None:
        message_str = None
        if input is not None:
            if isinstance(input, str):
                message_str = input
            else:
                log_warning("Did not use input in output file name: input is not a string")
        try:
            from pathlib import Path

            fn = agent.save_response_to_file.format(
                name=agent.name,
                session_id=session_id,
                user_id=user_id,
                message=message_str,
                run_id=run_response.run_id,
            )
            fn_path = Path(fn)
            if not fn_path.parent.exists():
                fn_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(run_response.content, str):
                fn_path.write_text(run_response.content)
            else:
                import json

                fn_path.write_text(json.dumps(run_response.content, indent=2))
        except Exception as e:
            log_warning(f"Failed to save output to file: {e}")
