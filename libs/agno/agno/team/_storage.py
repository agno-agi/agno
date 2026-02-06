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
from agno.db.base import AsyncBaseDb, BaseDb, ComponentType, SessionType, UserMemory
from agno.db.utils import db_from_dict
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.utils import get_model
from agno.registry.registry import Registry
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.run.team import (
    TeamRunOutput,
)
from agno.session import TeamSession, WorkflowSession
from agno.session.summary import SessionSummary
from agno.tools import Toolkit
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
from agno.utils.log import (
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.string import generate_id_from_name


def _cleanup_and_store(team: "Team", run_response: TeamRunOutput, session: TeamSession) -> None:
    #  Scrub the stored run based on storage flags
    team._scrub_run_output_for_storage(run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Add RunOutput to Agent Session
    session.upsert_run(run_response=run_response)

    # Calculate session metrics
    team._update_session_metrics(session=session, run_response=run_response)

    # Save session to memory
    team.save_session(session=session)


async def _acleanup_and_store(team: "Team", run_response: TeamRunOutput, session: TeamSession) -> None:
    #  Scrub the stored run based on storage flags
    team._scrub_run_output_for_storage(run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Add RunOutput to Agent Session
    session.upsert_run(run_response=run_response)

    # Calculate session metrics
    team._update_session_metrics(session=session, run_response=run_response)

    # Save session to memory
    await team.asave_session(session=session)


def _scrub_run_output_for_storage(team: "Team", run_response: TeamRunOutput) -> bool:
    """
    Scrub run output based on storage flags before persisting to database.
    Returns True if any scrubbing was done, False otherwise.
    """
    scrubbed = False

    if not team.store_media:
        scrub_media_from_run_output(run_response)
        scrubbed = True

    if not team.store_tool_messages:
        scrub_tool_results_from_run_output(run_response)
        scrubbed = True

    if not team.store_history_messages:
        scrub_history_messages_from_run_output(run_response)
        scrubbed = True

    return scrubbed


def _scrub_member_responses(team: "Team", member_responses: List[Union[TeamRunOutput, RunOutput]]) -> None:
    """
    Scrub member responses based on each member's storage flags.
    This is called when saving the team session to ensure member data is scrubbed per member settings.
    Recursively handles nested team's member responses.
    """
    from agno.team.team import Team

    for member_response in member_responses:
        member_id = None
        if isinstance(member_response, RunOutput):
            member_id = member_response.agent_id
        elif isinstance(member_response, TeamRunOutput):
            member_id = member_response.team_id

        if not member_id:
            log_info("Skipping member response with no ID")
            continue

        member_result = team._find_member_by_id(member_id)
        if not member_result:
            log_debug(f"Could not find member with ID: {member_id}")
            continue

        _, member = member_result

        if not member.store_media or not member.store_tool_messages or not member.store_history_messages:
            member._scrub_run_output_for_storage(member_response)  # type: ignore

        # If this is a nested team, recursively scrub its member responses
        if isinstance(member, Team) and isinstance(member_response, TeamRunOutput) and member_response.member_responses:
            member._scrub_member_responses(member_response.member_responses)  # type: ignore


def _parse_team_mode(value: Optional[str]) -> Optional["TeamMode"]:
    """Parse a TeamMode from a string value, or return None."""
    if value is None:
        return None
    from agno.team.mode import TeamMode

    return TeamMode(value)


def _read_session(
    team: "Team", session_id: str, session_type: SessionType = SessionType.TEAM
) -> Optional[Union[TeamSession, WorkflowSession]]:
    """Get a Session from the database."""
    try:
        if not team.db:
            raise ValueError("Db not initialized")
        session = team.db.get_session(session_id=session_id, session_type=session_type)
        return session  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error getting session from db: {e}")
        return None


async def _aread_session(
    team: "Team", session_id: str, session_type: SessionType = SessionType.TEAM
) -> Optional[Union[TeamSession, WorkflowSession]]:
    """Get a Session from the database."""
    try:
        if not team.db:
            raise ValueError("Db not initialized")
        team.db = cast(AsyncBaseDb, team.db)
        session = await team.db.get_session(session_id=session_id, session_type=session_type)
        return session  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error getting session from db: {e}")
        return None


def _upsert_session(team: "Team", session: TeamSession) -> Optional[TeamSession]:
    """Upsert a Session into the database."""

    try:
        if not team.db:
            raise ValueError("Db not initialized")
        return team.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting session into db: {e}")
    return None


async def _aupsert_session(team: "Team", session: TeamSession) -> Optional[TeamSession]:
    """Upsert a Session into the database."""

    try:
        if not team.db:
            raise ValueError("Db not initialized")
        return await team.db.upsert_session(session=session)  # type: ignore
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        log_warning(f"Error upserting session into db: {e}")
    return None


def _read_or_create_session(team: "Team", session_id: str, user_id: Optional[str] = None) -> TeamSession:
    """Load the TeamSession from storage

    Returns:
        Optional[TeamSession]: The loaded TeamSession or None if not found.
    """
    from time import time

    from agno.session.team import TeamSession

    # Return existing session if we have one
    if team._cached_session is not None and team._cached_session.session_id == session_id:
        return team._cached_session

    # Try to load from database
    team_session = None
    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        team_session = cast(TeamSession, team._read_session(session_id=session_id))

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
            team_data=team._get_team_data(),
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

    # Return existing session if we have one
    if team._cached_session is not None and team._cached_session.session_id == session_id:
        return team._cached_session

    # Try to load from database
    team_session = None
    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if team._has_async_db():
            team_session = cast(TeamSession, await team._aread_session(session_id=session_id))
        else:
            team_session = cast(TeamSession, team._read_session(session_id=session_id))

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
            team_data=team._get_team_data(),
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
    if team.members:
        serialized_members = []
        for member in team.members:
            if isinstance(member, Agent):
                serialized_members.append({"type": "agent", "agent_id": member.id})
            elif isinstance(member, Team):
                serialized_members.append({"type": "team", "team_id": member.id})
        if serialized_members:
            config["members"] = serialized_members

    # --- Execution settings (only if non-default) ---
    if team.mode is not None:
        config["mode"] = team.mode.value
    if team.respond_directly:
        config["respond_directly"] = team.respond_directly
    if team.delegate_to_all_members:
        config["delegate_to_all_members"] = team.delegate_to_all_members
    if not team.determine_input_for_members:  # default is True
        config["determine_input_for_members"] = team.determine_input_for_members
    if team.max_iterations != 10:
        config["max_iterations"] = team.max_iterations

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
    if team.tools:
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

    # --- Version ---
    if team.version is not None:
        config["version"] = team.version

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
            # --- Execution settings ---
            mode=_parse_team_mode(config.get("mode")),
            respond_directly=config.get("respond_directly", False),
            delegate_to_all_members=config.get("delegate_to_all_members", False),
            determine_input_for_members=config.get("determine_input_for_members", True),
            max_iterations=config.get("max_iterations", 10),
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

    # Set fields that are not constructor parameters
    if "version" in config:
        team.version = config["version"]

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
        for position, member in enumerate(team.members or []):
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


def get_session(
    team: "Team",
    session_id: Optional[str] = None,
) -> Optional[TeamSession]:
    """Load an TeamSession from database.

    Args:
        session_id: The session_id to load from storage.

    Returns:
        TeamSession: The TeamSession loaded from the database or created if it does not exist.
    """
    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or team.session_id

    # If there is a cached session, return it
    if team.cache_session and hasattr(team, "_cached_session") and team._cached_session is not None:
        if team._cached_session.session_id == session_id_to_load:
            return team._cached_session

    if team._has_async_db():
        raise ValueError("Async database not supported for get_session")

    # Load and return the session from the database
    if team.db is not None:
        loaded_session = None
        # We have a standalone team, so we are loading a TeamSession
        if team.workflow_id is None:
            loaded_session = cast(TeamSession, team._read_session(session_id=session_id_to_load))  # type: ignore
        # We have a workflow team, so we are loading a WorkflowSession
        else:
            loaded_session = cast(
                WorkflowSession,
                team._read_session(
                    session_id=session_id_to_load,  # type: ignore
                    session_type=SessionType.WORKFLOW,
                ),
            )

        # Cache the session if relevant
        if loaded_session is not None and team.cache_session:
            team._cached_session = loaded_session

        return loaded_session

    log_debug(f"TeamSession {session_id_to_load} not found in db")
    return None


async def aget_session(
    team: "Team",
    session_id: Optional[str] = None,
) -> Optional[TeamSession]:
    """Load an TeamSession from database.

    Args:
        session_id: The session_id to load from storage.

    Returns:
        TeamSession: The TeamSession loaded from the database or created if it does not exist.
    """
    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load = session_id or team.session_id

    # If there is a cached session, return it
    if team.cache_session and hasattr(team, "_cached_session") and team._cached_session is not None:
        if team._cached_session.session_id == session_id_to_load:
            return team._cached_session

    # Load and return the session from the database
    if team.db is not None:
        loaded_session = None
        # We have a standalone team, so we are loading a TeamSession
        if team.workflow_id is None:
            if team._has_async_db():
                loaded_session = cast(TeamSession, await team._aread_session(session_id=session_id_to_load))  # type: ignore
            else:
                loaded_session = cast(TeamSession, team._read_session(session_id=session_id_to_load))  # type: ignore
        # We have a workflow team, so we are loading a WorkflowSession
        else:
            if team._has_async_db():
                loaded_session = cast(
                    WorkflowSession,
                    await team._aread_session(
                        session_id=session_id_to_load,  # type: ignore
                        session_type=SessionType.WORKFLOW,
                    ),
                )
            else:
                loaded_session = cast(
                    WorkflowSession,
                    team._read_session(
                        session_id=session_id_to_load,  # type: ignore
                        session_type=SessionType.WORKFLOW,
                    ),
                )

        # Cache the session if relevant
        if loaded_session is not None and team.cache_session:
            team._cached_session = loaded_session

        return loaded_session

    log_debug(f"TeamSession {session_id_to_load} not found in db")
    return None


def save_session(team: "Team", session: TeamSession) -> None:
    """
    Save the TeamSession to storage

    Args:
        session: The TeamSession to save.
    """
    if team._has_async_db():
        raise ValueError("Async database not supported for save_session")

    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if session.session_data is not None and "session_state" in session.session_data:
            session.session_data["session_state"].pop("current_session_id", None)  # type: ignore
            session.session_data["session_state"].pop("current_user_id", None)  # type: ignore
            session.session_data["session_state"].pop("current_run_id", None)  # type: ignore

        # scrub the member responses based on storage settings
        if session.runs is not None:
            for run in session.runs:
                if hasattr(run, "member_responses"):
                    if not team.store_member_responses:
                        # Remove all member responses
                        run.member_responses = []
                    else:
                        # Scrub individual member responses based on their storage flags
                        team._scrub_member_responses(run.member_responses)
        team._upsert_session(session=session)
        log_debug(f"Created or updated TeamSession record: {session.session_id}")


async def asave_session(team: "Team", session: TeamSession) -> None:
    """
    Save the TeamSession to storage

    Args:
        session: The TeamSession to save.
    """
    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if session.session_data is not None and "session_state" in session.session_data:
            session.session_data["session_state"].pop("current_session_id", None)  # type: ignore
            session.session_data["session_state"].pop("current_user_id", None)  # type: ignore
            session.session_data["session_state"].pop("current_run_id", None)  # type: ignore

        # scrub the member responses based on storage settings
        if session.runs is not None:
            for run in session.runs:
                if hasattr(run, "member_responses"):
                    if not team.store_member_responses:
                        # Remove all member responses
                        run.member_responses = []
                    else:
                        # Scrub individual member responses based on their storage flags
                        team._scrub_member_responses(run.member_responses)

        if team._has_async_db():
            await team._aupsert_session(session=session)
        else:
            team._upsert_session(session=session)
        log_debug(f"Created or updated TeamSession record: {session.session_id}")


def generate_session_name(team: "Team", session: TeamSession, _retries: int = 0) -> str:
    """
    Generate a name for the team session

    Args:
        session: The TeamSession to generate a name for.
        _retries: Internal retry counter (do not set manually).
    Returns:
        str: The generated session name.
    """
    max_retries = 3

    if team.model is None:
        raise Exception("Model not set")

    gen_session_name_prompt = "Team Conversation\n"

    # Get team session messages for generating the name
    messages_for_generating_session_name = session.get_messages()

    for message in messages_for_generating_session_name:
        gen_session_name_prompt += f"{message.role.upper()}: {message.content}\n"

    gen_session_name_prompt += "\n\nTeam Session Name: "

    system_message = Message(
        role=team.system_message_role,
        content="Please provide a suitable name for this conversation in maximum 5 words. "
        "Remember, do not exceed 5 words.",
    )
    user_message = Message(role="user", content=gen_session_name_prompt)
    generate_name_messages = [system_message, user_message]

    # Generate name
    generated_name = team.model.response(messages=generate_name_messages)
    content = generated_name.content
    if content is None:
        if _retries < max_retries:
            log_error("Generated name is None. Trying again.")
            return generate_session_name(team, session=session, _retries=_retries + 1)
        log_error("Generated name is None after max retries. Using fallback.")
        return "Team Session"
    if len(content.split()) > 15:
        if _retries < max_retries:
            log_error("Generated name is too long. Trying again.")
            return generate_session_name(team, session=session, _retries=_retries + 1)
        log_error("Generated name is too long after max retries. Using fallback.")
        return "Team Session"
    return content.replace('"', "").strip()


def set_session_name(
    team: "Team", session_id: Optional[str] = None, autogenerate: bool = False, session_name: Optional[str] = None
) -> TeamSession:
    """
    Set the session name and save to storage

    Args:
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        TeamSession: The updated session.
    """
    session_id = session_id or team.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        TeamSession,
        set_session_name_util(
            cast(Any, team),
            session_id=session_id,
            autogenerate=autogenerate,
            session_name=session_name,
        ),
    )


async def aset_session_name(
    team: "Team", session_id: Optional[str] = None, autogenerate: bool = False, session_name: Optional[str] = None
) -> TeamSession:
    """
    Set the session name and save to storage

    Args:
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        TeamSession: The updated session.
    """
    session_id = session_id or team.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        TeamSession,
        await aset_session_name_util(
            cast(Any, team),
            session_id=session_id,
            autogenerate=autogenerate,
            session_name=session_name,
        ),
    )


def get_session_name(team: "Team", session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_name_util(cast(Any, team), session_id=session_id)


async def aget_session_name(team: "Team", session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_name_util(cast(Any, team), session_id=session_id)


def get_session_state(team: "Team", session_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the session state for the given session ID.

    Args:
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_state_util(cast(Any, team), session_id=session_id)


async def aget_session_state(team: "Team", session_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the session state for the given session ID.

    Args:
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_state_util(cast(Any, team), session_id=session_id)


def update_session_state(team: "Team", session_state_updates: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return update_session_state_util(
        cast(Any, team), session_state_updates=session_state_updates, session_id=session_id
    )


async def aupdate_session_state(
    team: "Team", session_state_updates: Dict[str, Any], session_id: Optional[str] = None
) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aupdate_session_state_util(
        entity=cast(Any, team),
        session_state_updates=session_state_updates,
        session_id=session_id,
    )


def get_session_metrics(team: "Team", session_id: Optional[str] = None) -> Optional[Metrics]:
    """Get the session metrics for the given session ID.

    Args:
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[Metrics]: The session metrics.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return get_session_metrics_util(cast(Any, team), session_id=session_id)


async def aget_session_metrics(team: "Team", session_id: Optional[str] = None) -> Optional[Metrics]:
    """Get the session metrics for the given session ID.

    Args:
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[Metrics]: The session metrics.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return await aget_session_metrics_util(cast(Any, team), session_id=session_id)


def delete_session(team: "Team", session_id: str):
    """Delete the current session and save to storage"""
    if team.db is None:
        return

    team.db.delete_session(session_id=session_id)


async def adelete_session(team: "Team", session_id: str):
    """Delete the current session and save to storage"""
    if team.db is None:
        return
    if team._has_async_db():
        await team.db.delete_session(session_id=session_id)  # type: ignore
    else:
        team.db.delete_session(session_id=session_id)


def get_session_messages(
    team: "Team",
    session_id: Optional[str] = None,
    member_ids: Optional[List[str]] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
    skip_member_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        session_id: The session ID to get the messages for. If not provided, the current cached session ID is used.
        member_ids: The ids of the members to get the messages from.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.
        skip_member_messages: Skip messages created by members of the team.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = team.get_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")

    return session.get_messages(
        team_id=team.id,
        member_ids=member_ids,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
        skip_member_messages=skip_member_messages,
    )


async def aget_session_messages(
    team: "Team",
    session_id: Optional[str] = None,
    member_ids: Optional[List[str]] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
    skip_member_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        session_id: The session ID to get the messages for. If not provided, the current cached session ID is used.
        member_ids: The ids of the members to get the messages from.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.
        skip_member_messages: Skip messages created by members of the team.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = await team.aget_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")

    return session.get_messages(
        team_id=team.id,
        member_ids=member_ids,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
        skip_member_messages=skip_member_messages,
    )


def get_chat_history(
    team: "Team", session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Return the chat history (user and assistant messages) for the session.
    Use get_messages() for more filtering options.

    Args:
        session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.

    Returns:
        List[Message]: The chat history from the session.
    """
    return team.get_session_messages(
        session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"], skip_member_messages=True
    )


async def aget_chat_history(
    team: "Team", session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Read the chat history from the session

    Args:
        session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.
    Returns:
        List[Message]: The chat history from the session.
    """
    return await team.aget_session_messages(
        session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"], skip_member_messages=True
    )


def get_session_summary(team: "Team", session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID.

    Args:
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.
    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else team.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = team.get_session(session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore


async def aget_session_summary(team: "Team", session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID.

    Args:
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.
    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else team.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = await team.aget_session(session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore


def get_user_memories(team: "Team", user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    if team.memory_manager is None:
        team._set_memory_manager()

    user_id = user_id if user_id is not None else team.user_id
    if user_id is None:
        user_id = "default"

    return team.memory_manager.get_user_memories(user_id=user_id)  # type: ignore


async def aget_user_memories(team: "Team", user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    if team.memory_manager is None:
        team._set_memory_manager()

    user_id = user_id if user_id is not None else team.user_id
    if user_id is None:
        user_id = "default"

    return await team.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore
