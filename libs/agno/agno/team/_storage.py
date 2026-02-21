"""Session persistence and serialization helpers for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.mode import TeamMode
    from agno.team.team import Team

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb, ComponentType, SessionType
from agno.db.utils import db_from_dict
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.utils import get_model
from agno.registry.registry import Registry
from agno.run.agent import RunOutput
from agno.run.team import (
    TeamRunOutput,
)
from agno.session import TeamSession, WorkflowSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.agent import (
    aget_last_run_output_util,
    aget_run_output_util,
    get_last_run_output_util,
    get_run_output_util,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_warning,
)
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.string import generate_id_from_name

# ---------------------------------------------------------------------------
# Run output accessors
# ---------------------------------------------------------------------------


def get_run_output(
    team: "Team", run_id: str, session_id: Optional[str] = None
) -> Optional[Union[TeamRunOutput, RunOutput]]:
    """
    Get a RunOutput or TeamRunOutput from the database.  Handles cached sessions.

    Args:
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
    """
    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or team.session_id
    return get_run_output_util(cast(Any, team), run_id=run_id, session_id=session_id_to_load)


async def aget_run_output(
    team: "Team", run_id: str, session_id: Optional[str] = None
) -> Optional[Union[TeamRunOutput, RunOutput]]:
    """
    Get a RunOutput or TeamRunOutput from the database.  Handles cached sessions.

    Args:
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
    """
    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or team.session_id
    return await aget_run_output_util(cast(Any, team), run_id=run_id, session_id=session_id_to_load)


def get_last_run_output(team: "Team", session_id: Optional[str] = None) -> Optional[TeamRunOutput]:
    """
    Get the last run response from the database.

    Args:
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        RunOutput: The last run response from the database.
    """
    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or team.session_id
    return cast(TeamRunOutput, get_last_run_output_util(cast(Any, team), session_id=session_id_to_load))


async def aget_last_run_output(team: "Team", session_id: Optional[str] = None) -> Optional[TeamRunOutput]:
    """
    Get the last run response from the database.

    Args:
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        RunOutput: The last run response from the database.
    """
    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or team.session_id
    return cast(TeamRunOutput, await aget_last_run_output_util(cast(Any, team), session_id=session_id_to_load))


# ---------------------------------------------------------------------------
# Session metrics (internal)
# ---------------------------------------------------------------------------


def get_session_metrics_internal(team: "Team", session: TeamSession) -> Metrics:
    # Get the session_metrics from the database
    if session.session_data is not None and "session_metrics" in session.session_data:
        session_metrics_from_db = session.session_data.get("session_metrics")
        if session_metrics_from_db is not None:
            if isinstance(session_metrics_from_db, dict):
                return Metrics(**session_metrics_from_db)
            elif isinstance(session_metrics_from_db, Metrics):
                return session_metrics_from_db

    return Metrics()


# ---------------------------------------------------------------------------
# Session read / write
# ---------------------------------------------------------------------------


def _read_session(
    team: "Team", session_id: str, session_type: SessionType = SessionType.TEAM, user_id: Optional[str] = None
) -> Optional[Union[TeamSession, WorkflowSession]]:
    """Get a Session from the database."""
    try:
        if not team.db:
            raise ValueError("Db not initialized")
        session = team.db.get_session(session_id=session_id, session_type=session_type, user_id=user_id)
        return session  # type: ignore
    except Exception as e:
        log_warning(f"Error getting session from db: {e}")
        return None


async def _aread_session(
    team: "Team", session_id: str, session_type: SessionType = SessionType.TEAM, user_id: Optional[str] = None
) -> Optional[Union[TeamSession, WorkflowSession]]:
    """Get a Session from the database."""
    from agno.team._init import _has_async_db

    try:
        if not team.db:
            raise ValueError("Db not initialized")
        if _has_async_db(team):
            team.db = cast(AsyncBaseDb, team.db)
            session = await team.db.get_session(session_id=session_id, session_type=session_type, user_id=user_id)
        else:
            session = team.db.get_session(session_id=session_id, session_type=session_type, user_id=user_id)  # type: ignore[assignment]
        return session  # type: ignore
    except Exception as e:
        log_warning(f"Error getting session from db: {e}")
        return None


def _upsert_session(team: "Team", session: TeamSession) -> Optional[TeamSession]:
    """Upsert a Session into the database."""

    try:
        if not team.db:
            raise ValueError("Db not initialized")
        return team.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        log_warning(f"Error upserting session into db: {e}")
    return None


async def _aupsert_session(team: "Team", session: TeamSession) -> Optional[TeamSession]:
    """Upsert a Session into the database."""
    from agno.team._init import _has_async_db

    try:
        if not team.db:
            raise ValueError("Db not initialized")
        if _has_async_db(team):
            return await team.db.upsert_session(session=session)  # type: ignore
        else:
            return team.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        log_warning(f"Error upserting session into db: {e}")
    return None


def _read_or_create_session(team: "Team", session_id: str, user_id: Optional[str] = None) -> TeamSession:
    """Load the TeamSession from storage

    Returns:
        Optional[TeamSession]: The loaded TeamSession or None if not found.
    """
    from time import time

    from agno.session.team import TeamSession
    from agno.team._telemetry import get_team_data

    # Return existing session if we have one
    if (
        team._cached_session is not None
        and team._cached_session.session_id == session_id
        and (user_id is None or team._cached_session.user_id == user_id)
    ):
        return team._cached_session

    # Try to load from database
    team_session = None
    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        team_session = cast(TeamSession, _read_session(team, session_id=session_id, user_id=user_id))

    # Create new session if none found
    if team_session is None:
        log_debug(f"Creating new TeamSession: {session_id}")
        session_data = {}
        if team.session_state is not None:
            from copy import deepcopy

            session_data["session_state"] = deepcopy(team.session_state)
        team_session = TeamSession(
            session_id=session_id,
            team_id=team.id,
            user_id=user_id,
            team_data=get_team_data(team),
            session_data=session_data,
            metadata=team.metadata,
            created_at=int(time()),
        )
        if team.introduction is not None:
            from uuid import uuid4

            team_session.upsert_run(
                TeamRunOutput(
                    run_id=str(uuid4()),
                    team_id=team.id,
                    session_id=session_id,
                    user_id=user_id,
                    team_name=team.name,
                    content=team.introduction,
                    messages=[Message(role=team.model.assistant_message_role, content=team.introduction)],  # type: ignore
                )
            )

    # Cache the session if relevant
    if team_session is not None and team.cache_session:
        team._cached_session = team_session

    return team_session


async def _aread_or_create_session(team: "Team", session_id: str, user_id: Optional[str] = None) -> TeamSession:
    """Load the TeamSession from storage

    Returns:
        Optional[TeamSession]: The loaded TeamSession or None if not found.
    """
    from time import time

    from agno.session.team import TeamSession
    from agno.team._init import _has_async_db
    from agno.team._telemetry import get_team_data

    # Return existing session if we have one
    if (
        team._cached_session is not None
        and team._cached_session.session_id == session_id
        and (user_id is None or team._cached_session.user_id == user_id)
    ):
        return team._cached_session

    # Try to load from database
    team_session = None
    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if _has_async_db(team):
            team_session = cast(TeamSession, await _aread_session(team, session_id=session_id, user_id=user_id))
        else:
            team_session = cast(TeamSession, _read_session(team, session_id=session_id, user_id=user_id))

    # Create new session if none found
    if team_session is None:
        log_debug(f"Creating new TeamSession: {session_id}")
        session_data = {}
        if team.session_state is not None:
            from copy import deepcopy

            session_data["session_state"] = deepcopy(team.session_state)
        team_session = TeamSession(
            session_id=session_id,
            team_id=team.id,
            user_id=user_id,
            team_data=get_team_data(team),
            session_data=session_data,
            metadata=team.metadata,
            created_at=int(time()),
        )
        if team.introduction is not None:
            from uuid import uuid4

            team_session.upsert_run(
                TeamRunOutput(
                    run_id=str(uuid4()),
                    team_id=team.id,
                    session_id=session_id,
                    user_id=user_id,
                    team_name=team.name,
                    content=team.introduction,
                    messages=[Message(role=team.model.assistant_message_role, content=team.introduction)],  # type: ignore
                )
            )

    # Cache the session if relevant
    if team_session is not None and team.cache_session:
        team._cached_session = team_session

    return team_session


def _load_session_state(team: "Team", session: TeamSession, session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Load and return the stored session_state from the database, optionally merging it with the given one"""

    # Get the session_state from the database and merge with proper precedence
    # At this point session_state contains: agent_defaults + run_params
    if session.session_data is not None and "session_state" in session.session_data:
        session_state_from_db = session.session_data.get("session_state")

        if (
            session_state_from_db is not None
            and isinstance(session_state_from_db, dict)
            and len(session_state_from_db) > 0
            and not team.overwrite_db_session_state
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


def _update_metadata(team: "Team", session: TeamSession):
    """Update the extra_data in the session"""

    # Read metadata from the database
    if session.metadata is not None:
        # If metadata is set in the agent, update the database metadata with the agent's metadata
        if team.metadata is not None:
            # Updates agent's session metadata in place
            merge_dictionaries(session.metadata, team.metadata)
        # Update the current metadata with the metadata from the database which is updated in place
        team.metadata = session.metadata


def to_dict(team: "Team") -> Dict[str, Any]:
    """
    Convert the Team to a dictionary.

    Returns:
        Dict[str, Any]: Dictionary representation of the team configuration
    """
    from agno.team.team import Team

    config: Dict[str, Any] = {}

    # --- Team Settings ---
    if team.id is not None:
        config["id"] = team.id
    if team.name is not None:
        config["name"] = team.name
    if team.role is not None:
        config["role"] = team.role
    if team.description is not None:
        config["description"] = team.description

    # --- Model ---
    if team.model is not None:
        config["model"] = team.model.to_dict() if isinstance(team.model, Model) else str(team.model)

    # --- Members ---
    if team.members and isinstance(team.members, list):
        serialized_members = []
        for member in team.members:
            if isinstance(member, Agent):
                serialized_members.append({"type": "agent", "agent_id": member.id})
            elif isinstance(member, Team):
                serialized_members.append({"type": "team", "team_id": member.id})
        if serialized_members:
            config["members"] = serialized_members

    # --- Mode ---
    if team.mode is not None:
        config["mode"] = team.mode.value if hasattr(team.mode, "value") else str(team.mode)
    if team.max_iterations != 10:
        config["max_iterations"] = team.max_iterations

    # --- Execution settings (only if non-default) ---
    if team.respond_directly:
        config["respond_directly"] = team.respond_directly
    if team.delegate_to_all_members:
        config["delegate_to_all_members"] = team.delegate_to_all_members
    if not team.determine_input_for_members:  # default is True
        config["determine_input_for_members"] = team.determine_input_for_members

    # --- User settings ---
    if team.user_id is not None:
        config["user_id"] = team.user_id

    # --- Session settings ---
    if team.session_id is not None:
        config["session_id"] = team.session_id
    if team.session_state is not None:
        config["session_state"] = team.session_state
    if team.add_session_state_to_context:
        config["add_session_state_to_context"] = team.add_session_state_to_context
    if team.enable_agentic_state:
        config["enable_agentic_state"] = team.enable_agentic_state
    if team.overwrite_db_session_state:
        config["overwrite_db_session_state"] = team.overwrite_db_session_state
    if team.cache_session:
        config["cache_session"] = team.cache_session

    # --- Team history settings ---
    if team.add_team_history_to_members:
        config["add_team_history_to_members"] = team.add_team_history_to_members
    if team.num_team_history_runs != 3:  # default is 3
        config["num_team_history_runs"] = team.num_team_history_runs
    if team.share_member_interactions:
        config["share_member_interactions"] = team.share_member_interactions
    if team.search_session_history:
        config["search_session_history"] = team.search_session_history
    if team.num_history_sessions is not None:
        config["num_history_sessions"] = team.num_history_sessions
    if team.read_chat_history:
        config["read_chat_history"] = team.read_chat_history

    # --- System message settings ---
    if team.system_message is not None and isinstance(team.system_message, str):
        config["system_message"] = team.system_message
    if team.system_message_role != "system":  # default is "system"
        config["system_message_role"] = team.system_message_role
    if team.introduction is not None:
        config["introduction"] = team.introduction
    if team.instructions is not None and not callable(team.instructions):
        config["instructions"] = team.instructions
    if team.expected_output is not None:
        config["expected_output"] = team.expected_output
    if team.additional_context is not None:
        config["additional_context"] = team.additional_context

    # --- Context settings ---
    if team.markdown:
        config["markdown"] = team.markdown
    if team.add_datetime_to_context:
        config["add_datetime_to_context"] = team.add_datetime_to_context
    if team.add_location_to_context:
        config["add_location_to_context"] = team.add_location_to_context
    if team.timezone_identifier is not None:
        config["timezone_identifier"] = team.timezone_identifier
    if team.add_name_to_context:
        config["add_name_to_context"] = team.add_name_to_context
    if team.add_member_tools_to_context:
        config["add_member_tools_to_context"] = team.add_member_tools_to_context
    if not team.resolve_in_context:  # default is True
        config["resolve_in_context"] = team.resolve_in_context

    # --- Database settings ---
    if team.db is not None and hasattr(team.db, "to_dict"):
        config["db"] = team.db.to_dict()

    # --- Dependencies ---
    if team.dependencies is not None:
        config["dependencies"] = team.dependencies
    if team.add_dependencies_to_context:
        config["add_dependencies_to_context"] = team.add_dependencies_to_context

    # --- Knowledge settings ---
    # TODO: implement knowledge serialization
    # if team.knowledge is not None:
    #     config["knowledge"] = team.knowledge.to_dict()
    if team.knowledge_filters is not None:
        config["knowledge_filters"] = team.knowledge_filters
    if team.enable_agentic_knowledge_filters:
        config["enable_agentic_knowledge_filters"] = team.enable_agentic_knowledge_filters
    if team.update_knowledge:
        config["update_knowledge"] = team.update_knowledge
    if team.add_knowledge_to_context:
        config["add_knowledge_to_context"] = team.add_knowledge_to_context
    if not team.search_knowledge:  # default is True
        config["search_knowledge"] = team.search_knowledge
    if not team.add_search_knowledge_instructions:  # default is True
        config["add_search_knowledge_instructions"] = team.add_search_knowledge_instructions
    if team.references_format != "json":  # default is "json"
        config["references_format"] = team.references_format

    # --- Tools ---
    if team.tools and isinstance(team.tools, list):
        serialized_tools = []
        for tool in team.tools:
            try:
                if isinstance(tool, Function):
                    serialized_tools.append(tool.to_dict())
                elif isinstance(tool, Toolkit):
                    for func in tool.functions.values():
                        serialized_tools.append(func.to_dict())
                elif callable(tool):
                    func = Function.from_callable(tool)
                    serialized_tools.append(func.to_dict())
            except Exception as e:
                log_warning(f"Could not serialize tool {tool}: {e}")
        if serialized_tools:
            config["tools"] = serialized_tools
    if team.tool_choice is not None:
        config["tool_choice"] = team.tool_choice
    if team.tool_call_limit is not None:
        config["tool_call_limit"] = team.tool_call_limit
    if team.get_member_information_tool:
        config["get_member_information_tool"] = team.get_member_information_tool

    # --- Schema settings ---
    if team.input_schema is not None:
        if issubclass(team.input_schema, BaseModel):
            config["input_schema"] = team.input_schema.__name__
        elif isinstance(team.input_schema, dict):
            config["input_schema"] = team.input_schema
    if team.output_schema is not None:
        if isinstance(team.output_schema, type) and issubclass(team.output_schema, BaseModel):
            config["output_schema"] = team.output_schema.__name__
        elif isinstance(team.output_schema, dict):
            config["output_schema"] = team.output_schema

    # --- Parser and output settings ---
    if team.parser_model is not None:
        if isinstance(team.parser_model, Model):
            config["parser_model"] = team.parser_model.to_dict()
        else:
            config["parser_model"] = str(team.parser_model)
    if team.parser_model_prompt is not None:
        config["parser_model_prompt"] = team.parser_model_prompt
    if team.output_model is not None:
        if isinstance(team.output_model, Model):
            config["output_model"] = team.output_model.to_dict()
        else:
            config["output_model"] = str(team.output_model)
    if team.output_model_prompt is not None:
        config["output_model_prompt"] = team.output_model_prompt
    if team.use_json_mode:
        config["use_json_mode"] = team.use_json_mode
    if not team.parse_response:  # default is True
        config["parse_response"] = team.parse_response

    # --- Memory settings ---
    # TODO: implement memory manager serialization
    # if team.memory_manager is not None:
    #     config["memory_manager"] = team.memory_manager.to_dict()
    if team.enable_agentic_memory:
        config["enable_agentic_memory"] = team.enable_agentic_memory
    if team.enable_user_memories:
        config["enable_user_memories"] = team.enable_user_memories
    if team.add_memories_to_context is not None:
        config["add_memories_to_context"] = team.add_memories_to_context
    if team.enable_session_summaries:
        config["enable_session_summaries"] = team.enable_session_summaries
    if team.add_session_summary_to_context is not None:
        config["add_session_summary_to_context"] = team.add_session_summary_to_context
    # TODO: implement session summary manager serialization
    # if team.session_summary_manager is not None:
    #     config["session_summary_manager"] = team.session_summary_manager.to_dict()

    # --- Learning settings ---
    if team.learning is not None:
        if team.learning is True:
            config["learning"] = True
        elif team.learning is False:
            config["learning"] = False
        elif hasattr(team.learning, "to_dict"):
            config["learning"] = team.learning.to_dict()
        else:
            config["learning"] = True if team.learning else False
    if not team.add_learnings_to_context:  # default is True
        config["add_learnings_to_context"] = team.add_learnings_to_context

    # --- History settings ---
    if team.add_history_to_context:
        config["add_history_to_context"] = team.add_history_to_context
    if team.num_history_runs is not None:
        config["num_history_runs"] = team.num_history_runs
    if team.num_history_messages is not None:
        config["num_history_messages"] = team.num_history_messages
    if team.max_tool_calls_from_history is not None:
        config["max_tool_calls_from_history"] = team.max_tool_calls_from_history

    # --- Media/storage settings ---
    if not team.send_media_to_model:  # default is True
        config["send_media_to_model"] = team.send_media_to_model
    if not team.store_media:  # default is True
        config["store_media"] = team.store_media
    if not team.store_tool_messages:  # default is True
        config["store_tool_messages"] = team.store_tool_messages
    if team.store_history_messages:  # default is False
        config["store_history_messages"] = team.store_history_messages

    # --- Compression settings ---
    if team.compress_tool_results:
        config["compress_tool_results"] = team.compress_tool_results
    # TODO: implement compression manager serialization
    # if team.compression_manager is not None:
    #     config["compression_manager"] = team.compression_manager.to_dict()

    # --- Reasoning settings ---
    if team.reasoning:
        config["reasoning"] = team.reasoning
    # TODO: implement reasoning model serialization
    # if team.reasoning_model is not None:
    #     config["reasoning_model"] = team.reasoning_model.to_dict() if isinstance(team.reasoning_model, Model) else str(team.reasoning_model)
    if team.reasoning_min_steps != 1:  # default is 1
        config["reasoning_min_steps"] = team.reasoning_min_steps
    if team.reasoning_max_steps != 10:  # default is 10
        config["reasoning_max_steps"] = team.reasoning_max_steps

    # --- Streaming settings ---
    if team.stream is not None:
        config["stream"] = team.stream
    if team.stream_events is not None:
        config["stream_events"] = team.stream_events
    if not team.stream_member_events:  # default is True
        config["stream_member_events"] = team.stream_member_events
    if team.store_events:
        config["store_events"] = team.store_events
    if team.store_member_responses:
        config["store_member_responses"] = team.store_member_responses

    # --- Retry settings ---
    if team.retries > 0:
        config["retries"] = team.retries
    if team.delay_between_retries != 1:  # default is 1
        config["delay_between_retries"] = team.delay_between_retries
    if team.exponential_backoff:
        config["exponential_backoff"] = team.exponential_backoff

    # --- Metadata ---
    if team.metadata is not None:
        config["metadata"] = team.metadata

    # --- Debug and telemetry settings ---
    if team.debug_mode:
        config["debug_mode"] = team.debug_mode
    if team.debug_level != 1:  # default is 1
        config["debug_level"] = team.debug_level
    if team.show_members_responses:
        config["show_members_responses"] = team.show_members_responses
    if not team.telemetry:  # default is True
        config["telemetry"] = team.telemetry

    return config


def _deserialize_learning(value: Any) -> Any:
    """Deserialize a learning config value from to_dict output.

    Returns True, False, None, or a LearningMachine instance.
    """
    if value is None or value is True or value is False:
        return value
    if isinstance(value, dict):
        from agno.learn.machine import LearningMachine

        return LearningMachine.from_dict(value)
    return value


def _parse_team_mode(value: Optional[str]) -> Optional["TeamMode"]:
    """Parse a string into a TeamMode enum, returning None if not provided."""
    if value is None:
        return None
    from agno.team.mode import TeamMode

    return TeamMode(value)


def from_dict(
    cls,
    data: Dict[str, Any],
    db: Optional["BaseDb"] = None,
    registry: Optional["Registry"] = None,
) -> "Team":
    """
    Create a Team from a dictionary.

    Args:
        data: Dictionary containing team configuration
        db: Optional database for loading agents in members
        registry: Optional registry for rehydrating tools

    Returns:
        Team: Reconstructed team instance
    """
    config = data.copy()

    # --- Handle Model reconstruction ---
    if "model" in config:
        model_data = config["model"]
        if isinstance(model_data, dict) and "id" in model_data:
            config["model"] = get_model(f"{model_data['provider']}:{model_data['id']}")
        elif isinstance(model_data, str):
            config["model"] = get_model(model_data)

    # --- Handle Members reconstruction ---
    members: Optional[List[Union[Agent, "Team"]]] = None
    from agno.agent import get_agent_by_id
    from agno.team import get_team_by_id

    if "members" in config and config["members"]:
        members = []
        for member_data in config["members"]:
            member_type = member_data.get("type")
            if member_type == "agent":
                # TODO: Make sure to pass the correct version to get_agent_by_id. Right now its returning the latest version.
                if db is None:
                    log_warning(f"Cannot load member agent {member_data['agent_id']}: db is None")
                    continue
                agent = get_agent_by_id(id=member_data["agent_id"], db=db, registry=registry)
                if agent:
                    members.append(agent)
                else:
                    log_warning(f"Agent not found: {member_data['agent_id']}")
            elif member_type == "team":
                # Handle nested teams as members
                if db is None:
                    log_warning(f"Cannot load member team {member_data['team_id']}: db is None")
                    continue
                nested_team = get_team_by_id(id=member_data["team_id"], db=db, registry=registry)
                if nested_team:
                    members.append(nested_team)
                else:
                    log_warning(f"Team not found: {member_data['team_id']}")

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

    team = cast(
        "Team",
        cls(
            # --- Team settings ---
            id=config.get("id"),
            name=config.get("name"),
            role=config.get("role"),
            description=config.get("description"),
            # --- Model ---
            model=config.get("model"),
            # --- Members ---
            members=members or [],
            # --- Mode ---
            mode=_parse_team_mode(config.get("mode")),
            max_iterations=config.get("max_iterations", 10),
            # --- Execution settings ---
            respond_directly=config.get("respond_directly", False),
            delegate_to_all_members=config.get("delegate_to_all_members", False),
            determine_input_for_members=config.get("determine_input_for_members", True),
            # --- User settings ---
            user_id=config.get("user_id"),
            # --- Session settings ---
            session_id=config.get("session_id"),
            session_state=config.get("session_state"),
            add_session_state_to_context=config.get("add_session_state_to_context", False),
            enable_agentic_state=config.get("enable_agentic_state", False),
            overwrite_db_session_state=config.get("overwrite_db_session_state", False),
            cache_session=config.get("cache_session", False),
            add_team_history_to_members=config.get("add_team_history_to_members", False),
            num_team_history_runs=config.get("num_team_history_runs", 3),
            share_member_interactions=config.get("share_member_interactions", False),
            search_session_history=config.get("search_session_history", False),
            num_history_sessions=config.get("num_history_sessions"),
            read_chat_history=config.get("read_chat_history", False),
            # --- System message settings ---
            system_message=config.get("system_message"),
            system_message_role=config.get("system_message_role", "system"),
            introduction=config.get("introduction"),
            instructions=config.get("instructions"),
            expected_output=config.get("expected_output"),
            additional_context=config.get("additional_context"),
            markdown=config.get("markdown", False),
            add_datetime_to_context=config.get("add_datetime_to_context", False),
            add_location_to_context=config.get("add_location_to_context", False),
            timezone_identifier=config.get("timezone_identifier"),
            add_name_to_context=config.get("add_name_to_context", False),
            add_member_tools_to_context=config.get("add_member_tools_to_context", False),
            resolve_in_context=config.get("resolve_in_context", True),
            # --- Database settings ---
            db=config.get("db"),
            # --- Dependencies ---
            dependencies=config.get("dependencies"),
            add_dependencies_to_context=config.get("add_dependencies_to_context", False),
            # --- Knowledge settings ---
            # knowledge=config.get("knowledge"),  # TODO
            knowledge_filters=config.get("knowledge_filters"),
            enable_agentic_knowledge_filters=config.get("enable_agentic_knowledge_filters", False),
            add_knowledge_to_context=config.get("add_knowledge_to_context", False),
            update_knowledge=config.get("update_knowledge", False),
            search_knowledge=config.get("search_knowledge", True),
            add_search_knowledge_instructions=config.get("add_search_knowledge_instructions", True),
            references_format=config.get("references_format", "json"),
            # --- Tools ---
            tools=config.get("tools"),
            tool_call_limit=config.get("tool_call_limit"),
            tool_choice=config.get("tool_choice"),
            get_member_information_tool=config.get("get_member_information_tool", False),
            # --- Schema settings ---
            input_schema=config.get("input_schema"),
            output_schema=config.get("output_schema"),
            # --- Parser and output settings ---
            # parser_model=config.get("parser_model"),  # TODO
            parser_model_prompt=config.get("parser_model_prompt"),
            # output_model=config.get("output_model"),  # TODO
            output_model_prompt=config.get("output_model_prompt"),
            use_json_mode=config.get("use_json_mode", False),
            parse_response=config.get("parse_response", True),
            # --- Memory settings ---
            # memory_manager=config.get("memory_manager"),  # TODO
            enable_agentic_memory=config.get("enable_agentic_memory", False),
            enable_user_memories=config.get("enable_user_memories"),
            add_memories_to_context=config.get("add_memories_to_context"),
            enable_session_summaries=config.get("enable_session_summaries", False),
            add_session_summary_to_context=config.get("add_session_summary_to_context"),
            # session_summary_manager=config.get("session_summary_manager"),  # TODO
            # --- Learning settings ---
            learning=_deserialize_learning(config.get("learning")),
            add_learnings_to_context=config.get("add_learnings_to_context", True),
            # --- History settings ---
            add_history_to_context=config.get("add_history_to_context", False),
            num_history_runs=config.get("num_history_runs"),
            num_history_messages=config.get("num_history_messages"),
            max_tool_calls_from_history=config.get("max_tool_calls_from_history"),
            # --- Compression settings ---
            compress_tool_results=config.get("compress_tool_results", False),
            # compression_manager=config.get("compression_manager"),  # TODO
            # --- Reasoning settings ---
            reasoning=config.get("reasoning", False),
            # reasoning_model=config.get("reasoning_model"),  # TODO
            reasoning_min_steps=config.get("reasoning_min_steps", 1),
            reasoning_max_steps=config.get("reasoning_max_steps", 10),
            # --- Streaming settings ---
            stream=config.get("stream"),
            stream_events=config.get("stream_events"),
            stream_member_events=config.get("stream_member_events", True),
            store_events=config.get("store_events", False),
            store_member_responses=config.get("store_member_responses", False),
            # --- Media settings ---
            send_media_to_model=config.get("send_media_to_model", True),
            store_media=config.get("store_media", True),
            store_tool_messages=config.get("store_tool_messages", True),
            store_history_messages=config.get("store_history_messages", False),
            # --- Retry settings ---
            retries=config.get("retries", 0),
            delay_between_retries=config.get("delay_between_retries", 1),
            exponential_backoff=config.get("exponential_backoff", False),
            # --- Metadata ---
            metadata=config.get("metadata"),
            # --- Debug and telemetry settings ---
            debug_mode=config.get("debug_mode", False),
            debug_level=config.get("debug_level", 1),
            show_members_responses=config.get("show_members_responses", False),
            telemetry=config.get("telemetry", True),
        ),
    )

    return team


def save(
    team: "Team",
    *,
    db: Optional["BaseDb"] = None,
    stage: str = "published",
    label: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[int]:
    """
    Save the team component and config to the database, including member agents/teams.

    Args:
        db: The database to save the component and config to.
        stage: The stage of the component. Defaults to "published".
        label: The label of the component.
        notes: The notes of the component.

    Returns:
        Optional[int]: The version number of the saved config.
    """
    from agno.agent.agent import Agent

    db_ = db or team.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for save(). Use a sync database.")
    if team.id is None:
        team.id = generate_id_from_name(team.name)

    try:
        # Collect all links for members
        all_links: List[Dict[str, Any]] = []

        # Save each member (Agent or nested Team) and collect links
        # Only iterate if members is a static list (not a callable factory)
        members_list = team.members if isinstance(team.members, list) else []
        for position, member in enumerate(members_list):
            # Save member first - returns version
            member_version = member.save(db=db_, stage=stage, label=label, notes=notes)

            # Add link
            all_links.append(
                {
                    "link_kind": "member",
                    "link_key": f"member_{position}",
                    "child_component_id": member.id,
                    "child_version": member_version,
                    "position": position,
                    "meta": {"type": "agent" if isinstance(member, Agent) else "team"},
                }
            )

        # Create or update component
        db_.upsert_component(
            component_id=team.id,
            component_type=ComponentType.TEAM,
            name=getattr(team, "name", team.id),
            description=getattr(team, "description", None),
            metadata=getattr(team, "metadata", None),
        )

        # Create or update config with links
        config = db_.upsert_config(
            component_id=team.id,
            config=team.to_dict(),
            links=all_links if all_links else None,
            label=label,
            stage=stage,
            notes=notes,
        )

        return config["version"]

    except Exception as e:
        log_error(f"Error saving Team to database: {e}")
        raise


def _hydrate_from_graph(
    cls,
    graph: Dict[str, Any],
    *,
    db: "BaseDb",
    registry: Optional["Registry"] = None,
) -> Optional["Team"]:
    """
    Hydrate a team and its members from an already-loaded component graph.

    This avoids re-querying the DB for nested teams whose graphs are already available.
    """
    from agno.agent.agent import Agent

    config = graph["config"].get("config")
    if config is None:
        return None

    team = cls.from_dict(config, db=db, registry=registry)
    team.id = graph["component"]["component_id"]
    team.db = db

    # Hydrate members from graph children
    team.members = []
    for child in graph.get("children", []):
        child_graph = child.get("graph")
        if child_graph is None:
            continue

        child_config = child_graph["config"].get("config")
        if child_config is None:
            continue

        link_meta = child["link"].get("meta", {})
        member_type = link_meta.get("type")

        if member_type == "agent":
            agent = Agent.from_dict(child_config)
            agent.id = child_graph["component"]["component_id"]
            agent.db = db
            team.members.append(agent)
        elif member_type == "team":
            # Recursively hydrate nested teams from the already-loaded child graph
            nested_team = _hydrate_from_graph(cls, child_graph, db=db, registry=registry)
            if nested_team:
                team.members.append(nested_team)

    return team


def load(
    cls,
    id: str,
    *,
    db: "BaseDb",
    registry: Optional["Registry"] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional["Team"]:
    """
    Load a team by id, with hydrated members.

    Args:
        id: The id of the team to load.
        db: The database to load the team from.
        label: The label of the team to load.

    Returns:
        The team loaded from the database with hydrated members, or None if not found.
    """
    # Use graph to load team + all members in a single DB call
    graph = db.load_component_graph(id, version=version, label=label)
    if graph is None:
        return None

    return _hydrate_from_graph(cls, graph, db=db, registry=registry)


def delete(
    team: "Team",
    *,
    db: Optional["BaseDb"] = None,
    hard_delete: bool = False,
) -> bool:
    """
    Delete the team component.

    Args:
        db: The database to delete the component from.
        hard_delete: Whether to hard delete the component.

    Returns:
        True if the component was deleted, False otherwise.
    """
    db_ = db or team.db
    if not db_:
        raise ValueError("Db not initialized or provided")
    if not isinstance(db_, BaseDb):
        raise ValueError("Async databases not yet supported for delete(). Use a sync database.")
    if team.id is None:
        raise ValueError("Cannot delete team without an id")

    return db_.delete_component(component_id=team.id, hard_delete=hard_delete)
