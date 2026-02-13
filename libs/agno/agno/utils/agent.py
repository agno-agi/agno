import asyncio
from asyncio import Future, Task
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Type,
    Union,
)

from pydantic import BaseModel

from agno.db.base import AsyncBaseDb
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunEvent, RunInput, RunOutput, RunOutputEvent
from agno.run.team import RunOutputEvent as TeamRunOutputEvent
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.utils.common import is_typed_dict, validate_typed_dict
from agno.utils.events import (
    create_memory_update_completed_event,
    create_memory_update_started_event,
    create_team_memory_update_completed_event,
    create_team_memory_update_started_event,
    handle_event,
)
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.team.team import Team


def _has_async_db(entity: Union["Agent", "Team"]) -> bool:
    """Return True if the entity's db is an async implementation."""
    return entity.db is not None and isinstance(entity.db, AsyncBaseDb)


async def await_for_open_threads(
    memory_task: Optional[Task] = None,
    cultural_knowledge_task: Optional[Task] = None,
    learning_task: Optional[Task] = None,
) -> None:
    if memory_task is not None:
        try:
            await memory_task
        except Exception as e:
            log_warning(f"Error in memory creation: {str(e)}")

    if cultural_knowledge_task is not None:
        try:
            await cultural_knowledge_task
        except Exception as e:
            log_warning(f"Error in cultural knowledge creation: {str(e)}")

    if learning_task is not None:
        try:
            await learning_task
        except Exception as e:
            log_warning(f"Error in learning extraction: {str(e)}")


def wait_for_open_threads(
    memory_future: Optional[Future] = None,
    cultural_knowledge_future: Optional[Future] = None,
    learning_future: Optional[Future] = None,
) -> None:
    if memory_future is not None:
        try:
            memory_future.result()
        except Exception as e:
            log_warning(f"Error in memory creation: {str(e)}")

    # Wait for cultural knowledge creation
    if cultural_knowledge_future is not None:
        try:
            cultural_knowledge_future.result()
        except Exception as e:
            log_warning(f"Error in cultural knowledge creation: {str(e)}")

    if learning_future is not None:
        try:
            learning_future.result()
        except Exception as e:
            log_warning(f"Error in learning extraction: {str(e)}")


async def await_for_thread_tasks_stream(
    run_response: Union[RunOutput, TeamRunOutput],
    memory_task: Optional[Task] = None,
    cultural_knowledge_task: Optional[Task] = None,
    learning_task: Optional[Task] = None,
    stream_events: bool = False,
    events_to_skip: Optional[List[RunEvent]] = None,
    store_events: bool = False,
    get_memories_callback: Optional[Callable[[], Union[Optional[List[Any]], Awaitable[Optional[List[Any]]]]]] = None,
) -> AsyncIterator[RunOutputEvent]:
    if memory_task is not None:
        if stream_events:
            if isinstance(run_response, TeamRunOutput):
                yield handle_event(  # type: ignore
                    create_team_memory_update_started_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
            else:
                yield handle_event(  # type: ignore
                    create_memory_update_started_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
        try:
            await memory_task
        except Exception as e:
            log_warning(f"Error in memory creation: {str(e)}")
        if stream_events:
            # Get memories after update if callback provided
            memories = None
            if get_memories_callback is not None:
                try:
                    result = get_memories_callback()
                    # Handle both sync and async callbacks
                    if asyncio.iscoroutine(result):
                        memories = await result
                    else:
                        memories = result
                except Exception as e:
                    log_warning(f"Error getting memories: {str(e)}")

            if isinstance(run_response, TeamRunOutput):
                yield handle_event(  # type: ignore
                    create_team_memory_update_completed_event(from_run_response=run_response, memories=memories),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
            else:
                yield handle_event(  # type: ignore
                    create_memory_update_completed_event(from_run_response=run_response, memories=memories),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )

    if cultural_knowledge_task is not None:
        try:
            await cultural_knowledge_task
        except Exception as e:
            log_warning(f"Error in cultural knowledge creation: {str(e)}")

    if learning_task is not None:
        try:
            await learning_task
        except Exception as e:
            log_warning(f"Error in learning extraction: {str(e)}")


def wait_for_thread_tasks_stream(
    run_response: Union[TeamRunOutput, RunOutput],
    memory_future: Optional[Future] = None,
    cultural_knowledge_future: Optional[Future] = None,
    learning_future: Optional[Future] = None,
    stream_events: bool = False,
    events_to_skip: Optional[List[RunEvent]] = None,
    store_events: bool = False,
    get_memories_callback: Optional[Callable[[], Optional[List[Any]]]] = None,
) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent]]:
    if memory_future is not None:
        if stream_events:
            if isinstance(run_response, TeamRunOutput):
                yield handle_event(  # type: ignore
                    create_team_memory_update_started_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
            else:
                yield handle_event(  # type: ignore
                    create_memory_update_started_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
        try:
            memory_future.result()
        except Exception as e:
            log_warning(f"Error in memory creation: {str(e)}")
        if stream_events:
            # Get memories after update if callback provided
            memories = None
            if get_memories_callback is not None:
                try:
                    memories = get_memories_callback()
                except Exception as e:
                    log_warning(f"Error getting memories: {str(e)}")

            if isinstance(run_response, TeamRunOutput):
                yield handle_event(  # type: ignore
                    create_team_memory_update_completed_event(from_run_response=run_response, memories=memories),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
            else:
                yield handle_event(  # type: ignore
                    create_memory_update_completed_event(from_run_response=run_response, memories=memories),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )

    # Wait for cultural knowledge creation
    if cultural_knowledge_future is not None:
        # TODO: Add events
        try:
            cultural_knowledge_future.result()
        except Exception as e:
            log_warning(f"Error in cultural knowledge creation: {str(e)}")

    if learning_future is not None:
        try:
            learning_future.result()
        except Exception as e:
            log_warning(f"Error in learning extraction: {str(e)}")


def collect_joint_images(
    run_input: Optional[RunInput] = None,
    session: Optional[Union[AgentSession, TeamSession]] = None,
) -> Optional[Sequence[Image]]:
    """Collect images from input, session history, and current run response."""
    joint_images: List[Image] = []

    # 1. Add images from current input
    if run_input and run_input.images:
        joint_images.extend(run_input.images)
        log_debug(f"Added {len(run_input.images)} input images to joint list")

    # 2. Add images from session history (from both input and generated sources)
    try:
        if session and session.runs:
            for historical_run in session.runs:
                # Add generated images from previous runs
                if historical_run.images:
                    joint_images.extend(historical_run.images)
                    log_debug(
                        f"Added {len(historical_run.images)} generated images from historical run {historical_run.run_id}"
                    )

                # Add input images from previous runs
                if historical_run.input and historical_run.input.images:
                    joint_images.extend(historical_run.input.images)
                    log_debug(
                        f"Added {len(historical_run.input.images)} input images from historical run {historical_run.run_id}"
                    )
    except Exception as e:
        log_debug(f"Could not access session history for images: {e}")

    if joint_images:
        log_debug(f"Images Available to Model: {len(joint_images)} images")
    return joint_images if joint_images else None


def collect_joint_videos(
    run_input: Optional[RunInput] = None,
    session: Optional[Union[AgentSession, TeamSession]] = None,
) -> Optional[Sequence[Video]]:
    """Collect videos from input, session history, and current run response."""
    joint_videos: List[Video] = []

    # 1. Add videos from current input
    if run_input and run_input.videos:
        joint_videos.extend(run_input.videos)
        log_debug(f"Added {len(run_input.videos)} input videos to joint list")

    # 2. Add videos from session history (from both input and generated sources)
    try:
        if session and session.runs:
            for historical_run in session.runs:
                # Add generated videos from previous runs
                if historical_run.videos:
                    joint_videos.extend(historical_run.videos)
                    log_debug(
                        f"Added {len(historical_run.videos)} generated videos from historical run {historical_run.run_id}"
                    )

                # Add input videos from previous runs
                if historical_run.input and historical_run.input.videos:
                    joint_videos.extend(historical_run.input.videos)
                    log_debug(
                        f"Added {len(historical_run.input.videos)} input videos from historical run {historical_run.run_id}"
                    )
    except Exception as e:
        log_debug(f"Could not access session history for videos: {e}")

    if joint_videos:
        log_debug(f"Videos Available to Model: {len(joint_videos)} videos")
    return joint_videos if joint_videos else None


def collect_joint_audios(
    run_input: Optional[RunInput] = None,
    session: Optional[Union[AgentSession, TeamSession]] = None,
) -> Optional[Sequence[Audio]]:
    """Collect audios from input, session history, and current run response."""
    joint_audios: List[Audio] = []

    # 1. Add audios from current input
    if run_input and run_input.audios:
        joint_audios.extend(run_input.audios)
        log_debug(f"Added {len(run_input.audios)} input audios to joint list")

    # 2. Add audios from session history (from both input and generated sources)
    try:
        if session and session.runs:
            for historical_run in session.runs:
                # Add generated audios from previous runs
                if historical_run.audio:
                    joint_audios.extend(historical_run.audio)
                    log_debug(
                        f"Added {len(historical_run.audio)} generated audios from historical run {historical_run.run_id}"
                    )

                # Add input audios from previous runs
                if historical_run.input and historical_run.input.audios:
                    joint_audios.extend(historical_run.input.audios)
                    log_debug(
                        f"Added {len(historical_run.input.audios)} input audios from historical run {historical_run.run_id}"
                    )
    except Exception as e:
        log_debug(f"Could not access session history for audios: {e}")

    if joint_audios:
        log_debug(f"Audios Available to Model: {len(joint_audios)} audios")
    return joint_audios if joint_audios else None


def collect_joint_files(
    run_input: Optional[RunInput] = None,
) -> Optional[Sequence[File]]:
    """Collect files from input and session history."""
    from agno.utils.log import log_debug

    joint_files: List[File] = []

    # 1. Add files from current input
    if run_input and run_input.files:
        joint_files.extend(run_input.files)

    # TODO: Files aren't stored in session history yet and dont have a FileArtifact

    if joint_files:
        log_debug(f"Files Available to Model: {len(joint_files)} files")

    return joint_files if joint_files else None


def store_media_util(run_response: Union[RunOutput, TeamRunOutput], model_response: ModelResponse):
    """Store media from model response in run_response for persistence"""
    # Handle generated media fields from ModelResponse (generated media)
    if model_response.images is not None:
        for image in model_response.images:
            if run_response.images is None:
                run_response.images = []
            run_response.images.append(image)  # Generated images go to run_response.images

    if model_response.videos is not None:
        for video in model_response.videos:
            if run_response.videos is None:
                run_response.videos = []
            run_response.videos.append(video)  # Generated videos go to run_response.videos

    if model_response.audios is not None:
        for audio in model_response.audios:
            if run_response.audio is None:
                run_response.audio = []
            run_response.audio.append(audio)  # Generated audio go to run_response.audio

    if model_response.files is not None:
        for file in model_response.files:
            if run_response.files is None:
                run_response.files = []
            run_response.files.append(file)  # Generated files go to run_response.files


def validate_media_object_id(
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    audios: Optional[Sequence[Audio]] = None,
    files: Optional[Sequence[File]] = None,
) -> tuple:
    image_list = None
    if images:
        image_list = []
        for img in images:
            if not img.id:
                from uuid import uuid4

                img.id = str(uuid4())
            image_list.append(img)

    video_list = None
    if videos:
        video_list = []
        for vid in videos:
            if not vid.id:
                from uuid import uuid4

                vid.id = str(uuid4())
            video_list.append(vid)

    audio_list = None
    if audios:
        audio_list = []
        for aud in audios:
            if not aud.id:
                from uuid import uuid4

                aud.id = str(uuid4())
            audio_list.append(aud)

    file_list = None
    if files:
        file_list = []
        for file in files:
            if not file.id:
                from uuid import uuid4

                file.id = str(uuid4())
            file_list.append(file)

    return image_list, video_list, audio_list, file_list


def scrub_media_from_run_output(run_response: Union[RunOutput, TeamRunOutput]) -> None:
    """
    Completely remove all media from RunOutput when store_media=False.
    This includes media in input, output artifacts, and all messages.
    """
    # 1. Scrub RunInput media
    if run_response.input is not None:
        run_response.input.images = []
        run_response.input.videos = []
        run_response.input.audios = []
        run_response.input.files = []

    # 3. Scrub media from all messages
    if run_response.messages:
        for message in run_response.messages:
            scrub_media_from_message(message)

    # 4. Scrub media from additional_input messages if any
    if run_response.additional_input:
        for message in run_response.additional_input:
            scrub_media_from_message(message)

    # 5. Scrub media from reasoning_messages if any
    if run_response.reasoning_messages:
        for message in run_response.reasoning_messages:
            scrub_media_from_message(message)


def scrub_media_from_message(message: Message) -> None:
    """Remove all media from a Message object."""
    # Input media
    message.images = None
    message.videos = None
    message.audio = None
    message.files = None

    # Output media
    message.audio_output = None
    message.image_output = None
    message.video_output = None


def scrub_tool_results_from_run_output(run_response: Union[RunOutput, TeamRunOutput]) -> None:
    """
    Remove all tool-related data from RunOutput when store_tool_messages=False.
    This removes both the tool call and its corresponding result to maintain API consistency.
    """
    if not run_response.messages:
        return

    # Step 1: Collect all tool_call_ids from tool result messages
    tool_call_ids_to_remove = set()
    for message in run_response.messages:
        if message.role == "tool" and message.tool_call_id:
            tool_call_ids_to_remove.add(message.tool_call_id)

    # Step 2: Remove tool result messages (role="tool")
    run_response.messages = [msg for msg in run_response.messages if msg.role != "tool"]

    # Step 3: Remove assistant messages that made those tool calls
    filtered_messages = []
    for message in run_response.messages:
        # Check if this assistant message made any of the tool calls we're removing
        should_remove = False
        if message.role == "assistant" and message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.get("id") in tool_call_ids_to_remove:
                    should_remove = True
                    break

        if not should_remove:
            filtered_messages.append(message)

    run_response.messages = filtered_messages


def scrub_history_messages_from_run_output(run_response: Union[RunOutput, TeamRunOutput]) -> None:
    """
    Remove all history messages from TeamRunOutput when store_history_messages=False.
    This removes messages that were loaded from the team's memory.
    """
    # Remove messages with from_history=True
    if run_response.messages:
        run_response.messages = [msg for msg in run_response.messages if not msg.from_history]


def get_run_output_util(
    entity: Union["Agent", "Team"], run_id: str, session_id: Optional[str] = None
) -> Optional[
    Union[
        RunOutput,
        TeamRunOutput,
    ]
]:
    """
    Get a RunOutput from the database.

    Args:
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
    """
    if session_id is not None:
        if _has_async_db(entity):
            raise ValueError("Async database not supported for sync functions")

        session = entity.get_session(session_id=session_id)
        if session is not None:
            run_response = session.get_run(run_id=run_id)
            if run_response is not None:
                return run_response  # type: ignore
            else:
                log_warning(f"RunOutput {run_id} not found in Session {session_id}")
    elif entity.cached_session is not None:
        run_response = entity.cached_session.get_run(run_id=run_id)
        if run_response is not None:
            return run_response  # type: ignore
        else:
            log_warning(f"RunOutput {run_id} not found in Session {entity.cached_session.session_id}")
            return None
    return None


async def aget_run_output_util(
    entity: Union["Agent", "Team"], run_id: str, session_id: Optional[str] = None
) -> Optional[Union[RunOutput, TeamRunOutput]]:
    """
    Get a RunOutput from the database.

    Args:
        run_id (str): The run_id to load from storage.
        session_id (Optional[str]): The session_id to load from storage.
    """
    if session_id is not None:
        session = await entity.aget_session(session_id=session_id)
        if session is not None:
            run_response = session.get_run(run_id=run_id)
            if run_response is not None:
                return run_response  # type: ignore
            else:
                log_warning(f"RunOutput {run_id} not found in Session {session_id}")
    elif entity.cached_session is not None:
        run_response = entity.cached_session.get_run(run_id=run_id)
        if run_response is not None:
            return run_response
        else:
            log_warning(f"RunOutput {run_id} not found in Session {entity.cached_session.session_id}")
            return None
    return None


def get_last_run_output_util(
    entity: Union["Agent", "Team"], session_id: Optional[str] = None
) -> Optional[Union[RunOutput, TeamRunOutput]]:
    """
    Get the last run response from the database.

    Args:
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        RunOutput: The last run response from the database.
    """
    if session_id is not None:
        if _has_async_db(entity):
            raise ValueError("Async database not supported for sync functions")

        session = entity.get_session(session_id=session_id)
        if session is not None and session.runs is not None and len(session.runs) > 0:
            for run_output in reversed(session.runs):
                if entity.__class__.__name__ == "Agent":
                    if hasattr(run_output, "agent_id") and run_output.agent_id == entity.id:
                        return run_output  # type: ignore
                elif entity.__class__.__name__ == "Team":
                    if hasattr(run_output, "team_id") and run_output.team_id == entity.id:
                        return run_output  # type: ignore
        else:
            log_warning(f"No run responses found in Session {session_id}")

    elif (
        entity.cached_session is not None
        and entity.cached_session.runs is not None
        and len(entity.cached_session.runs) > 0
    ):
        for run_output in reversed(entity.cached_session.runs):
            if entity.__class__.__name__ == "Agent":
                if hasattr(run_output, "agent_id") and run_output.agent_id == entity.id:
                    return run_output  # type: ignore
            elif entity.__class__.__name__ == "Team":
                if hasattr(run_output, "team_id") and run_output.team_id == entity.id:
                    return run_output  # type: ignore
    return None


async def aget_last_run_output_util(
    entity: Union["Agent", "Team"], session_id: Optional[str] = None
) -> Optional[Union[RunOutput, TeamRunOutput]]:
    """
    Get the last run response from the database.

    Args:
        session_id (Optional[str]): The session_id to load from storage.

    Returns:
        RunOutput: The last run response from the database.
    """
    if session_id is not None:
        session = await entity.aget_session(session_id=session_id)
        if session is not None and session.runs is not None and len(session.runs) > 0:
            for run_output in reversed(session.runs):
                if entity.__class__.__name__ == "Agent":
                    if hasattr(run_output, "agent_id") and run_output.agent_id == entity.id:
                        return run_output  # type: ignore
                elif entity.__class__.__name__ == "Team":
                    if hasattr(run_output, "team_id") and run_output.team_id == entity.id:
                        return run_output  # type: ignore
        else:
            log_warning(f"No run responses found in Session {session_id}")

    elif (
        entity.cached_session is not None
        and entity.cached_session.runs is not None
        and len(entity.cached_session.runs) > 0
    ):
        for run_output in reversed(entity.cached_session.runs):
            if entity.__class__.__name__ == "Agent":
                if hasattr(run_output, "agent_id") and run_output.agent_id == entity.id:
                    return run_output  # type: ignore
            elif entity.__class__.__name__ == "Team":
                if hasattr(run_output, "team_id") and run_output.team_id == entity.id:
                    return run_output  # type: ignore
    return None


def set_session_name_util(
    entity: Union["Agent", "Team"], session_id: str, autogenerate: bool = False, session_name: Optional[str] = None
) -> Union[AgentSession, TeamSession, WorkflowSession]:
    """Set the session name and save to storage"""
    if _has_async_db(entity):
        raise ValueError("Async database not supported for sync functions")

    session = entity.get_session(session_id=session_id)  # type: ignore

    if session is None:
        raise Exception("No session found")

    # -*- Generate name for session
    if autogenerate:
        session_name = entity.generate_session_name(session=session)  # type: ignore
        log_debug(f"Generated Session Name: {session_name}")
    elif session_name is None:
        raise Exception("No session name provided")

    # -*- Rename session
    if session.session_data is None:
        session.session_data = {"session_name": session_name}
    else:
        session.session_data["session_name"] = session_name
    # -*- Save to storage
    entity.save_session(session=session)  # type: ignore

    return session


async def aset_session_name_util(
    entity: Union["Agent", "Team"], session_id: str, autogenerate: bool = False, session_name: Optional[str] = None
) -> Union[AgentSession, TeamSession, WorkflowSession]:
    """Set the session name and save to storage"""
    session = await entity.aget_session(session_id=session_id)  # type: ignore

    if session is None:
        raise Exception("Session not found")

    # -*- Generate name for session
    if autogenerate:
        session_name = entity.generate_session_name(session=session)  # type: ignore
        log_debug(f"Generated Session Name: {session_name}")
    elif session_name is None:
        raise Exception("No session name provided")

    # -*- Rename session
    if session.session_data is None:
        session.session_data = {"session_name": session_name}
    else:
        session.session_data["session_name"] = session_name

    # -*- Save to storage
    await entity.asave_session(session=session)  # type: ignore

    return session


def get_session_name_util(entity: Union["Agent", "Team"], session_id: str) -> str:
    """Get the session name for the given session ID and user ID."""

    if _has_async_db(entity):
        raise ValueError("Async database not supported for sync functions")

    session = entity.get_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")
    return session.session_data.get("session_name", "") if session.session_data is not None else ""  # type: ignore


async def aget_session_name_util(entity: Union["Agent", "Team"], session_id: str) -> str:
    """Get the session name for the given session ID and user ID."""
    session = await entity.aget_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")
    return session.session_data.get("session_name", "") if session.session_data is not None else ""  # type: ignore


def get_session_state_util(entity: Union["Agent", "Team"], session_id: str) -> Dict[str, Any]:
    """Get the session state for the given session ID and user ID."""
    if _has_async_db(entity):
        raise ValueError("Async database not supported for sync functions")

    session = entity.get_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")
    return session.session_data.get("session_state", {}) if session.session_data is not None else {}  # type: ignore


async def aget_session_state_util(entity: Union["Agent", "Team"], session_id: str) -> Dict[str, Any]:
    """Get the session state for the given session ID and user ID."""
    session = await entity.aget_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")
    return session.session_data.get("session_state", {}) if session.session_data is not None else {}  # type: ignore


def update_session_state_util(
    entity: Union["Agent", "Team"], session_state_updates: Dict[str, Any], session_id: str
) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    if _has_async_db(entity):
        raise ValueError("Async database not supported for sync functions")

    session = entity.get_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")

    if session.session_data is not None and "session_state" not in session.session_data:
        session.session_data["session_state"] = {}

    for key, value in session_state_updates.items():
        session.session_data["session_state"][key] = value  # type: ignore

    entity.save_session(session=session)  # type: ignore

    return session.session_data["session_state"]  # type: ignore


async def aupdate_session_state_util(
    entity: Union["Agent", "Team"], session_state_updates: Dict[str, Any], session_id: str
) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session = await entity.aget_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")

    if session.session_data is not None and "session_state" not in session.session_data:
        session.session_data["session_state"] = {}

    for key, value in session_state_updates.items():
        session.session_data["session_state"][key] = value  # type: ignore

    await entity.asave_session(session=session)  # type: ignore

    return session.session_data["session_state"]  # type: ignore


def get_session_metrics_util(entity: Union["Agent", "Team"], session_id: str) -> Optional[Metrics]:
    """Get the session metrics for the given session ID and user ID."""
    if _has_async_db(entity):
        raise ValueError("Async database not supported for sync functions")

    session = entity.get_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")

    if session.session_data is not None:
        if isinstance(session.session_data.get("session_metrics"), dict):
            return Metrics(**session.session_data.get("session_metrics", {}))
        elif isinstance(session.session_data.get("session_metrics"), Metrics):
            return session.session_data.get("session_metrics")
    return None


async def aget_session_metrics_util(entity: Union["Agent", "Team"], session_id: str) -> Optional[Metrics]:
    """Get the session metrics for the given session ID and user ID."""
    session = await entity.aget_session(session_id=session_id)  # type: ignore
    if session is None:
        raise Exception("Session not found")

    if session.session_data is not None:
        if isinstance(session.session_data.get("session_metrics"), dict):
            return Metrics(**session.session_data.get("session_metrics", {}))
        elif isinstance(session.session_data.get("session_metrics"), Metrics):
            return session.session_data.get("session_metrics")
    return None


def get_chat_history_util(entity: Union["Agent", "Team"], session_id: str) -> List[Message]:
    """Read the chat history from the session

    Args:
        session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.
    Returns:
        List[Message]: The chat history from the session.
    """
    if _has_async_db(entity):
        raise ValueError("Async database not supported for sync functions")

    session = entity.get_session(session_id=session_id)  # type: ignore

    if session is None:
        raise Exception("Session not found")

    return session.get_chat_history()  # type: ignore


async def aget_chat_history_util(entity: Union["Agent", "Team"], session_id: str) -> List[Message]:
    """Read the chat history from the session

    Args:
        session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.
    Returns:
        List[Message]: The chat history from the session.
    """
    session = await entity.aget_session(session_id=session_id)  # type: ignore

    if session is None:
        raise Exception("Session not found")

    return session.get_chat_history()  # type: ignore


def execute_instructions(
    instructions: Callable,
    agent: Optional[Union["Agent", "Team"]] = None,
    team: Optional["Team"] = None,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> Union[str, List[str]]:
    """Execute the instructions function."""
    import inspect

    signature = inspect.signature(instructions)
    instruction_args: Dict[str, Any] = {}

    # Check for agent parameter
    if "agent" in signature.parameters:
        instruction_args["agent"] = agent

    if "team" in signature.parameters:
        instruction_args["team"] = team

    # Check for session_state parameter
    if "session_state" in signature.parameters:
        instruction_args["session_state"] = session_state if session_state is not None else {}

    # Check for run_context parameter
    if "run_context" in signature.parameters:
        instruction_args["run_context"] = run_context or None

    # Run the instructions function, await if it's awaitable, otherwise run directly (in thread)
    if inspect.iscoroutinefunction(instructions):
        raise Exception("Instructions function is async, use `agent.arun()` instead")

    # Run the instructions function
    return instructions(**instruction_args)


def execute_system_message(
    system_message: Callable,
    agent: Optional[Union["Agent", "Team"]] = None,
    team: Optional["Team"] = None,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> str:
    """Execute the system message function."""
    import inspect

    signature = inspect.signature(system_message)
    system_message_args: Dict[str, Any] = {}

    # Check for agent parameter
    if "agent" in signature.parameters:
        system_message_args["agent"] = agent
    if "team" in signature.parameters:
        system_message_args["team"] = team
    if inspect.iscoroutinefunction(system_message):
        raise ValueError("System message function is async, use `agent.arun()` instead")

    return system_message(**system_message_args)


async def aexecute_instructions(
    instructions: Callable,
    agent: Optional[Union["Agent", "Team"]] = None,
    team: Optional["Team"] = None,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> Union[str, List[str]]:
    """Execute the instructions function."""
    import inspect

    signature = inspect.signature(instructions)
    instruction_args: Dict[str, Any] = {}

    # Check for agent parameter
    if "agent" in signature.parameters:
        instruction_args["agent"] = agent
    if "team" in signature.parameters:
        instruction_args["team"] = team

    # Check for session_state parameter
    if "session_state" in signature.parameters:
        instruction_args["session_state"] = session_state if session_state is not None else {}

    # Check for run_context parameter
    if "run_context" in signature.parameters:
        instruction_args["run_context"] = run_context or None

    if inspect.iscoroutinefunction(instructions):
        return await instructions(**instruction_args)
    else:
        return instructions(**instruction_args)


async def aexecute_system_message(
    system_message: Callable,
    agent: Optional[Union["Agent", "Team"]] = None,
    team: Optional["Team"] = None,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> str:
    import inspect

    signature = inspect.signature(system_message)
    system_message_args: Dict[str, Any] = {}

    # Check for agent parameter
    if "agent" in signature.parameters:
        system_message_args["agent"] = agent
    if "team" in signature.parameters:
        system_message_args["team"] = team

    if inspect.iscoroutinefunction(system_message):
        return await system_message(**system_message_args)
    else:
        return system_message(**system_message_args)


def validate_input(
    input: Union[str, List, Dict, Message, BaseModel], input_schema: Optional[Type[BaseModel]] = None
) -> Union[str, List, Dict, Message, BaseModel]:
    """Parse and validate input against input_schema if provided, otherwise return input as-is"""
    if input_schema is None:
        return input  # Return input unchanged if no schema is set

    if input is None:
        raise ValueError("Input required when input_schema is set")

    # Handle Message objects - extract content
    if isinstance(input, Message):
        input = input.content  # type: ignore

    # If input is a string, convert it to a dict
    if isinstance(input, str):
        import json

        try:
            input = json.loads(input)
        except Exception as e:
            raise ValueError(f"Failed to parse input. Is it a valid JSON string?: {e}")

    # Case 1: Message is already a BaseModel instance
    if isinstance(input, BaseModel):
        if isinstance(input, input_schema):
            try:
                return input
            except Exception as e:
                raise ValueError(f"BaseModel validation failed: {str(e)}")
        else:
            # Different BaseModel types
            raise ValueError(f"Expected {input_schema.__name__} but got {type(input).__name__}")

    # Case 2: Message is a dict
    elif isinstance(input, dict):
        try:
            # Check if the schema is a TypedDict
            if is_typed_dict(input_schema):
                validated_dict = validate_typed_dict(input, input_schema)
                return validated_dict
            else:
                validated_model = input_schema(**input)
                return validated_model
        except Exception as e:
            raise ValueError(f"Failed to parse dict into {input_schema.__name__}: {str(e)}")

    # Case 3: Other types not supported for structured input
    else:
        raise ValueError(
            f"Cannot validate {type(input)} against input_schema. Expected dict or {input_schema.__name__} instance."
        )
