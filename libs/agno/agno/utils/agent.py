from asyncio import Future, Task
from typing import AsyncIterator, Iterator, List, Optional, Sequence, Union

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.run.agent import RunEvent, RunInput, RunOutput, RunOutputEvent
from agno.run.team import RunOutputEvent as TeamRunOutputEvent
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.utils.events import (
    create_memory_update_completed_event,
    create_memory_update_started_event,
    create_team_memory_update_completed_event,
    create_team_memory_update_started_event,
    handle_event,
)
from agno.utils.log import log_debug, log_warning


async def await_for_background_tasks(
    memory_task: Optional[Task] = None,
    cultural_knowledge_task: Optional[Task] = None,
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


def wait_for_background_tasks(
    memory_future: Optional[Future] = None, cultural_knowledge_future: Optional[Future] = None
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


async def await_for_background_tasks_stream(
    run_response: Union[RunOutput, TeamRunOutput],
    memory_task: Optional[Task] = None,
    cultural_knowledge_task: Optional[Task] = None,
    stream_events: bool = False,
    events_to_skip: Optional[List[RunEvent]] = None,
    store_events: bool = False,
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
            if isinstance(run_response, TeamRunOutput):
                yield handle_event(  # type: ignore
                    create_team_memory_update_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
            else:
                yield handle_event(  # type: ignore
                    create_memory_update_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )

    if cultural_knowledge_task is not None:
        try:
            await cultural_knowledge_task
        except Exception as e:
            log_warning(f"Error in cultural knowledge creation: {str(e)}")


def wait_for_background_tasks_stream(
    run_response: Union[TeamRunOutput, RunOutput],
    memory_future: Optional[Future] = None,
    cultural_knowledge_future: Optional[Future] = None,
    stream_events: bool = False,
    events_to_skip: Optional[List[RunEvent]] = None,
    store_events: bool = False,
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
            if isinstance(run_response, TeamRunOutput):
                yield handle_event(  # type: ignore
                    create_team_memory_update_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=events_to_skip,  # type: ignore
                    store_events=store_events,
                )
            else:
                yield handle_event(  # type: ignore
                    create_memory_update_completed_event(from_run_response=run_response),
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
